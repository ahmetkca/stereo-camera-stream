import pytest

from publisher import (
    PublisherConfig,
    build_message,
    capture_frame_with_metadata,
    get_capture_colorspace,
    get_main_stream_format,
)


class FakeRequest:
    def __init__(self):
        self.released = False

    def make_array(self, stream_name):
        assert stream_name == "main"
        return "frame"

    def get_metadata(self):
        return {"SensorTimestamp": 123456789}

    def release(self):
        self.released = True


class FakeCamera:
    def __init__(self):
        self.request = FakeRequest()

    def capture_request(self):
        return self.request


def test_build_message_matches_lerobot_schema():
    msg = build_message(
        encoded_frames={"left": "aaa", "right": "bbb"},
        timestamps={"left": 1.25, "right": 1.5},
        metadata={
            "left": {"wall_time_s": 1.25, "sensor_timestamp_ns": 100},
            "right": {"wall_time_s": 1.5, "sensor_timestamp_ns": 200},
        },
    )

    assert msg == {
        "timestamps": {"left": 1.25, "right": 1.5},
        "metadata": {
            "left": {"wall_time_s": 1.25, "sensor_timestamp_ns": 100},
            "right": {"wall_time_s": 1.5, "sensor_timestamp_ns": 200},
        },
        "images": {"left": "aaa", "right": "bbb"},
    }


def test_duplicate_camera_names_are_rejected():
    with pytest.raises(ValueError):
        PublisherConfig(
            bind_host="0.0.0.0",
            port=5555,
            width=1280,
            height=720,
            fps=15,
            left_index=0,
            right_index=1,
            left_camera_name="left",
            right_camera_name="left",
            jpeg_quality=80,
            log_level="INFO",
            stats_interval=0,
        )


def test_picamera2_main_stream_format_matches_known_good_rgb_path():
    assert get_main_stream_format() == "RGB888"


def test_jpeg_encoder_colorspace_matches_known_good_rgb_path():
    assert get_capture_colorspace() == "BGR"


def test_parse_args_accepts_optional_stats_interval():
    config = PublisherConfig(
        bind_host="0.0.0.0",
        port=5555,
        width=1280,
        height=720,
        fps=15,
        left_index=0,
        right_index=1,
        left_camera_name="left",
        right_camera_name="right",
        jpeg_quality=80,
        log_level="INFO",
        stats_interval=60,
    )

    assert config.stats_interval == 60


def test_capture_frame_uses_picamera2_request_metadata():
    camera = FakeCamera()

    captured = capture_frame_with_metadata(camera, wall_time=lambda: 12.5)

    assert captured.frame == "frame"
    assert captured.wall_time_s == 12.5
    assert captured.sensor_timestamp_ns == 123456789
    assert camera.request.released is True
    assert captured.metadata == {
        "wall_time_s": 12.5,
        "sensor_timestamp_ns": 123456789,
    }
