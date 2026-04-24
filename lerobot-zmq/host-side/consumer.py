#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import logging
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
import zmq

LOGGER = logging.getLogger("lerobot_zmq_host")


@dataclass
class ConsumerConfig:
    server_address: str
    port: int
    left_camera_name: str
    right_camera_name: str
    window_name: str
    max_width: int | None
    log_level: str

    def __post_init__(self) -> None:
        if not self.server_address:
            raise ValueError("Server address is required.")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if self.left_camera_name == self.right_camera_name:
            raise ValueError("Camera names must be unique.")
        if self.max_width is not None and self.max_width <= 0:
            raise ValueError("max_width must be positive when provided.")


def parse_args(argv: list[str] | None = None) -> ConsumerConfig:
    parser = argparse.ArgumentParser(description="Consume and preview LeRobot-style stereo ZMQ frames.")
    parser.add_argument("--server-address", required=True)
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--left-camera-name", default="left")
    parser.add_argument("--right-camera-name", default="right")
    parser.add_argument("--window-name", default="LeRobot ZMQ Stereo Consumer")
    parser.add_argument("--max-width", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    return ConsumerConfig(**vars(args))


def extract_named_images(data: dict, left_name: str, right_name: str) -> tuple[str, str, float, float]:
    images = data["images"]
    timestamps = data["timestamps"]
    return images[left_name], images[right_name], timestamps[left_name], timestamps[right_name]


def compute_skew_ms(left_ts: float, right_ts: float) -> float:
    return round((right_ts - left_ts) * 1000, 3)


def decode_base64_jpeg(payload: str) -> np.ndarray:
    raw = base64.b64decode(payload)
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Failed to decode JPEG payload.")
    return frame


def update_fps(samples: deque[float], timestamp: float) -> float:
    samples.append(timestamp)
    if len(samples) < 2:
        return 0.0
    elapsed = samples[-1] - samples[0]
    if elapsed <= 0:
        return 0.0
    return round((len(samples) - 1) / elapsed, 2)


def maybe_scale_frame(frame: np.ndarray, max_width: int | None) -> np.ndarray:
    if max_width is None or frame.shape[1] <= max_width:
        return frame
    scale = max_width / frame.shape[1]
    new_size = (int(frame.shape[1] * scale), int(frame.shape[0] * scale))
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def overlay_lines(frame: np.ndarray, lines: list[str]) -> np.ndarray:
    output = frame.copy()
    y = 24
    for line in lines:
        cv2.putText(output, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2, cv2.LINE_AA)
        y += 26
    return output


def make_socket(config: ConsumerConfig) -> tuple[zmq.Context, zmq.Socket]:
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.setsockopt_string(zmq.SUBSCRIBE, "")
    socket.setsockopt(zmq.RCVTIMEO, 1000)
    socket.setsockopt(zmq.CONFLATE, True)
    socket.connect(f"tcp://{config.server_address}:{config.port}")
    return context, socket


def run_consumer(config: ConsumerConfig) -> None:
    context, socket = make_socket(config)
    left_samples: deque[float] = deque(maxlen=60)
    right_samples: deque[float] = deque(maxlen=60)
    decode_errors = 0

    try:
        while True:
            try:
                message = socket.recv_string()
            except zmq.Again:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            received_at = time.time()
            try:
                data = json.loads(message)
                left_b64, right_b64, left_ts, right_ts = extract_named_images(
                    data, config.left_camera_name, config.right_camera_name
                )
                left_frame = decode_base64_jpeg(left_b64)
                right_frame = decode_base64_jpeg(right_b64)
            except Exception as exc:
                decode_errors += 1
                LOGGER.warning("Message decode failed (%s total): %s", decode_errors, exc)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            left_fps = update_fps(left_samples, received_at)
            right_fps = update_fps(right_samples, received_at)
            skew_ms = compute_skew_ms(left_ts, right_ts)

            left_frame = maybe_scale_frame(left_frame, config.max_width)
            right_frame = maybe_scale_frame(right_frame, config.max_width)
            preview = np.hstack([left_frame, right_frame])

            lines = [
                f"left fps: {left_fps:.2f}",
                f"right fps: {right_fps:.2f}",
                f"left ts: {left_ts:.6f}",
                f"right ts: {right_ts:.6f}",
                f"skew ms: {skew_ms:.3f}",
                f"decode errors: {decode_errors}",
            ]
            preview = overlay_lines(preview, lines)

            cv2.imshow(config.window_name, preview)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        socket.close()
        context.term()
        cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info("Connecting to tcp://%s:%s", config.server_address, config.port)
    try:
        run_consumer(config)
    except KeyboardInterrupt:
        LOGGER.info("Stopping consumer on user interrupt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
