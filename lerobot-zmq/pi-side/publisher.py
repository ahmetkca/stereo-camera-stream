#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zmq

from pipeline_stats import PipelineStats, format_summary

LOGGER = logging.getLogger("lerobot_zmq_pi")
SENSOR_SIZE = (3280, 2464)


@dataclass
class PublisherConfig:
    bind_host: str
    port: int
    width: int
    height: int
    fps: int
    left_index: int
    right_index: int
    left_camera_name: str
    right_camera_name: str
    jpeg_quality: int
    log_level: str
    stats_interval: int

    def __post_init__(self) -> None:
        if self.left_camera_name == self.right_camera_name:
            raise ValueError("Camera names must be unique.")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive.")
        if self.fps <= 0:
            raise ValueError("FPS must be positive.")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("JPEG quality must be between 1 and 100.")
        if self.stats_interval < 0:
            raise ValueError("Stats interval must be zero or positive.")


@dataclass
class CapturedFrame:
    frame: Any
    wall_time_s: float
    sensor_timestamp_ns: int | None

    @property
    def metadata(self) -> dict[str, float | int]:
        data: dict[str, float | int] = {"wall_time_s": self.wall_time_s}
        if self.sensor_timestamp_ns is not None:
            data["sensor_timestamp_ns"] = self.sensor_timestamp_ns
        return data


def parse_args(argv: list[str] | None = None) -> PublisherConfig:
    parser = argparse.ArgumentParser(description="Publish stereo Picamera2 frames using LeRobot's ZMQ schema.")
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--left-index", type=int, default=0)
    parser.add_argument("--right-index", type=int, default=1)
    parser.add_argument("--left-camera-name", default="left")
    parser.add_argument("--right-camera-name", default="right")
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--stats-interval",
        type=int,
        default=0,
        help="Log aggregate pipeline timings every N frames. Disabled when 0.",
    )
    args = parser.parse_args(argv)
    return PublisherConfig(**vars(args))


def build_message(
    encoded_frames: dict[str, str],
    timestamps: dict[str, float],
    metadata: dict[str, dict[str, float | int]] | None = None,
) -> dict[str, dict[str, Any]]:
    message = {
        "timestamps": timestamps,
        "images": encoded_frames,
    }
    if metadata is not None:
        message["metadata"] = metadata
    return message


def get_main_stream_format() -> str:
    return "RGB888"


def get_capture_colorspace() -> str:
    return "BGR"


def encode_frame_to_base64_jpeg(frame: Any, quality: int) -> str:
    try:
        import simplejpeg

        encoded = simplejpeg.encode_jpeg(frame, quality=quality, colorspace=get_capture_colorspace())
    except ImportError:
        import cv2

        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("Failed to JPEG-encode frame.")
        encoded = bytes(buffer)
    return base64.b64encode(encoded).decode("utf-8")


def capture_frame_with_metadata(cam: Any, wall_time=time.time) -> CapturedFrame:
    request = cam.capture_request()
    try:
        frame = request.make_array("main")
        captured_wall_time = wall_time()
        metadata = request.get_metadata()
    finally:
        request.release()

    sensor_timestamp_ns = metadata.get("SensorTimestamp")
    return CapturedFrame(
        frame=frame,
        wall_time_s=captured_wall_time,
        sensor_timestamp_ns=int(sensor_timestamp_ns) if sensor_timestamp_ns is not None else None,
    )


def _import_picamera2_modules():
    try:
        from libcamera import Transform
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError(
            "Picamera2/libcamera is required on the Raspberry Pi. "
            "Install the system packages before running the Pi-side publisher."
        ) from exc
    return Picamera2, Transform


def start_stereo_cameras(config: PublisherConfig):
    Picamera2, Transform = _import_picamera2_modules()

    tuning_file = Path(__file__).resolve().parents[2] / "shared" / "imx219_waveshare.json"
    tuning = Picamera2.load_tuning_file(str(tuning_file))

    left_cam = Picamera2(config.left_index, tuning=tuning)
    right_cam = Picamera2(config.right_index, tuning=tuning)
    flip = Transform(hflip=True, vflip=True)
    sensor = {"output_size": SENSOR_SIZE, "bit_depth": 10}
    main = {"size": (config.width, config.height), "format": get_main_stream_format()}
    controls = {"FrameRate": config.fps}

    left_cfg = left_cam.create_video_configuration(main=main, sensor=sensor, transform=flip, controls=controls)
    right_cfg = right_cam.create_video_configuration(main=main, sensor=sensor, transform=flip, controls=controls)

    left_cam.configure(left_cfg)
    right_cam.configure(right_cfg)
    left_cam.start()
    right_cam.start()

    LOGGER.info(
        "Started stereo cameras left=%s right=%s at %sx%s %sfps",
        config.left_index,
        config.right_index,
        config.width,
        config.height,
        config.fps,
    )
    return left_cam, right_cam


def make_socket(config: PublisherConfig) -> tuple[zmq.Context, zmq.Socket]:
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.setsockopt(zmq.SNDHWM, 20)
    socket.setsockopt(zmq.LINGER, 0)
    socket.bind(f"tcp://{config.bind_host}:{config.port}")
    return context, socket


def publish_loop(config: PublisherConfig) -> None:
    context, socket = make_socket(config)
    left_cam, right_cam = start_stereo_cameras(config)
    stats = PipelineStats(interval_frames=config.stats_interval)
    first_left = True
    first_right = True

    try:
        while True:
            if stats.enabled:
                loop_start = time.perf_counter_ns()
                left_capture = capture_frame_with_metadata(left_cam)
                left_capture_end = time.perf_counter_ns()
                right_capture = capture_frame_with_metadata(right_cam)
                right_capture_end = time.perf_counter_ns()
            else:
                left_capture = capture_frame_with_metadata(left_cam)
                right_capture = capture_frame_with_metadata(right_cam)

            if first_left:
                LOGGER.info("First frame captured for %s", config.left_camera_name)
                first_left = False
            if first_right:
                LOGGER.info("First frame captured for %s", config.right_camera_name)
                first_right = False

            if stats.enabled:
                left_encoded = encode_frame_to_base64_jpeg(left_capture.frame, config.jpeg_quality)
                left_encode_end = time.perf_counter_ns()
                right_encoded = encode_frame_to_base64_jpeg(right_capture.frame, config.jpeg_quality)
                right_encode_end = time.perf_counter_ns()
                message = build_message(
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
            else:
                message = build_message(
                    encoded_frames={
                        config.left_camera_name: encode_frame_to_base64_jpeg(left_capture.frame, config.jpeg_quality),
                        config.right_camera_name: encode_frame_to_base64_jpeg(right_capture.frame, config.jpeg_quality),
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

            if stats.enabled:
                payload = json.dumps(message)
                json_end = time.perf_counter_ns()
            else:
                payload = json.dumps(message)

            try:
                socket.send_string(payload, zmq.NOBLOCK)
            except zmq.Again:
                LOGGER.debug("Dropped one publish cycle because the ZMQ send buffer was full.")

            if stats.enabled:
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
                summary = stats.record(sample)
                if summary is not None:
                    LOGGER.info(format_summary(summary))
    finally:
        left_cam.stop()
        right_cam.stop()
        socket.close()
        context.term()


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info("Binding publisher to tcp://%s:%s", config.bind_host, config.port)
    try:
        publish_loop(config)
    except KeyboardInterrupt:
        LOGGER.info("Stopping publisher on user interrupt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
