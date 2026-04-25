#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import zmq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline_stats import PipelineStats, format_summary  # noqa: E402
from publisher import (  # noqa: E402
    PublisherConfig,
    build_message,
    capture_frame_with_metadata,
    encode_frame_to_base64_jpeg,
    make_socket,
    start_stereo_cameras,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile the Pi-side stereo camera publishing pipeline.")
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5560)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--left-index", type=int, default=0)
    parser.add_argument("--right-index", type=int, default=1)
    parser.add_argument("--left-camera-name", default="left")
    parser.add_argument("--right-camera-name", default="right")
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


def make_config(args: argparse.Namespace) -> PublisherConfig:
    return PublisherConfig(
        bind_host=args.bind_host,
        port=args.port,
        width=args.width,
        height=args.height,
        fps=args.fps,
        left_index=args.left_index,
        right_index=args.right_index,
        left_camera_name=args.left_camera_name,
        right_camera_name=args.right_camera_name,
        jpeg_quality=args.jpeg_quality,
        log_level="WARNING",
        stats_interval=args.frames,
    )


def capture_sample(config: PublisherConfig, left_cam: Any, right_cam: Any, socket: zmq.Socket) -> dict[str, float]:
    loop_start = time.perf_counter_ns()
    left_capture = capture_frame_with_metadata(left_cam)
    left_capture_end = time.perf_counter_ns()
    right_capture = capture_frame_with_metadata(right_cam)
    right_capture_end = time.perf_counter_ns()

    left_encoded = encode_frame_to_base64_jpeg(left_capture.frame, config.jpeg_quality)
    left_encode_end = time.perf_counter_ns()
    right_encoded = encode_frame_to_base64_jpeg(right_capture.frame, config.jpeg_quality)
    right_encode_end = time.perf_counter_ns()

    payload = json.dumps(
        build_message(
            encoded_frames={
                config.left_camera_name: left_encoded,
                config.right_camera_name: right_encoded,
            },
            timestamps={
                config.left_camera_name: left_capture.wall_time_s,
                config.right_camera_name: right_capture.wall_time_s,
            },
            metadata={
                config.left_camera_name: left_capture.metadata,
                config.right_camera_name: right_capture.metadata,
            },
        )
    )
    json_end = time.perf_counter_ns()
    socket.send_string(payload, zmq.NOBLOCK)
    send_end = time.perf_counter_ns()

    sample = {
        "left_capture_ms": (left_capture_end - loop_start) / 1_000_000,
        "right_capture_ms": (right_capture_end - left_capture_end) / 1_000_000,
        "capture_total_ms": (right_capture_end - loop_start) / 1_000_000,
        "wall_skew_ms": (right_capture.wall_time_s - left_capture.wall_time_s) * 1000,
        "left_encode_ms": (left_encode_end - right_capture_end) / 1_000_000,
        "right_encode_ms": (right_encode_end - left_encode_end) / 1_000_000,
        "encode_total_ms": (right_encode_end - right_capture_end) / 1_000_000,
        "json_dump_ms": (json_end - right_encode_end) / 1_000_000,
        "zmq_send_ms": (send_end - json_end) / 1_000_000,
        "loop_total_ms": (send_end - loop_start) / 1_000_000,
        "payload_bytes": len(payload),
    }
    if left_capture.sensor_timestamp_ns is not None and right_capture.sensor_timestamp_ns is not None:
        sample["sensor_skew_ms"] = (
            right_capture.sensor_timestamp_ns - left_capture.sensor_timestamp_ns
        ) / 1_000_000
    return sample


def run_benchmark(config: PublisherConfig, frames: int, warmup_frames: int) -> dict[str, object]:
    context = socket = left_cam = right_cam = None
    stats = PipelineStats(interval_frames=frames)
    try:
        context, socket = make_socket(config)
        left_cam, right_cam = start_stereo_cameras(config)

        for _ in range(warmup_frames):
            left_capture = capture_frame_with_metadata(left_cam)
            right_capture = capture_frame_with_metadata(right_cam)
            encode_frame_to_base64_jpeg(left_capture.frame, config.jpeg_quality)
            encode_frame_to_base64_jpeg(right_capture.frame, config.jpeg_quality)

        summary: dict[str, object] | None = None
        for _ in range(frames):
            summary = stats.record(capture_sample(config, left_cam, right_cam, socket))
        if summary is None:
            summary = stats.summary()

        return {
            "config": {
                "width": config.width,
                "height": config.height,
                "fps": config.fps,
                "jpeg_quality": config.jpeg_quality,
                "frames": frames,
                "warmup_frames": warmup_frames,
            },
            "summary": summary,
        }
    finally:
        if left_cam is not None:
            left_cam.stop()
        if right_cam is not None:
            right_cam.stop()
        if socket is not None:
            socket.close()
        if context is not None:
            context.term()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.frames <= 0:
        raise ValueError("--frames must be positive.")
    if args.warmup_frames < 0:
        raise ValueError("--warmup-frames must be zero or positive.")

    result = run_benchmark(make_config(args), frames=args.frames, warmup_frames=args.warmup_frames)
    print(format_summary(result["summary"]))

    if args.output_json is not None:
        args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
