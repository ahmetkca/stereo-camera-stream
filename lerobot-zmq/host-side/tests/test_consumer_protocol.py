from consumer import compute_skew_ms, extract_named_images


def test_extract_named_images_uses_requested_camera_names():
    data = {
        "timestamps": {"left": 10.0, "right": 10.01},
        "images": {"left": "aaa", "right": "bbb"},
    }

    left_b64, right_b64, left_ts, right_ts = extract_named_images(data, "left", "right")

    assert left_b64 == "aaa"
    assert right_b64 == "bbb"
    assert left_ts == 10.0
    assert right_ts == 10.01


def test_compute_skew_ms_is_signed_right_minus_left():
    assert compute_skew_ms(10.0, 10.012) == 12.0
