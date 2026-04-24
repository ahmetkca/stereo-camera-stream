import pytest

from publisher import PublisherConfig, build_message


def test_build_message_matches_lerobot_schema():
    msg = build_message(
        encoded_frames={"left": "aaa", "right": "bbb"},
        timestamps={"left": 1.25, "right": 1.5},
    )

    assert msg == {
        "timestamps": {"left": 1.25, "right": 1.5},
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
        )
