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
    args = parser.parse_args(argv)
    return PublisherConfig(**vars(args))


def build_message(encoded_frames: dict[str, str], timestamps: dict[str, float]) -> dict[str, dict[str, Any]]:
    return {
        "timestamps": timestamps,
        "images": encoded_frames,
    }


def encode_frame_to_base64_jpeg(frame: Any, quality: int) -> str:
    try:
        import simplejpeg

        encoded = simplejpeg.encode_jpeg(frame, quality=quality, colorspace="BGR")
    except ImportError:
        import cv2

        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("Failed to JPEG-encode frame.")
        encoded = bytes(buffer)
    return base64.b64encode(encoded).decode("utf-8")


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
    main = {"size": (config.width, config.height), "format": "BGR888"}
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
    first_left = True
    first_right = True

    try:
        while True:
            left_frame = left_cam.capture_array("main")
            left_ts = time.time()
            right_frame = right_cam.capture_array("main")
            right_ts = time.time()

            if first_left:
                LOGGER.info("First frame captured for %s", config.left_camera_name)
                first_left = False
            if first_right:
                LOGGER.info("First frame captured for %s", config.right_camera_name)
                first_right = False

            message = build_message(
                encoded_frames={
                    config.left_camera_name: encode_frame_to_base64_jpeg(left_frame, config.jpeg_quality),
                    config.right_camera_name: encode_frame_to_base64_jpeg(right_frame, config.jpeg_quality),
                },
                timestamps={
                    config.left_camera_name: left_ts,
                    config.right_camera_name: right_ts,
                },
            )

            try:
                socket.send_string(json.dumps(message), zmq.NOBLOCK)
            except zmq.Again:
                LOGGER.debug("Dropped one publish cycle because the ZMQ send buffer was full.")
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
