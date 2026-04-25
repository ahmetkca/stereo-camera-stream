from pipeline_stats import PipelineStats


def test_pipeline_stats_summarizes_recorded_stage_durations():
    stats = PipelineStats(interval_frames=10)

    stats.record(
        {
            "left_capture_ms": 10.0,
            "right_capture_ms": 12.0,
            "loop_total_ms": 30.0,
            "payload_bytes": 1000,
        }
    )
    stats.record(
        {
            "left_capture_ms": 20.0,
            "right_capture_ms": 14.0,
            "loop_total_ms": 40.0,
            "payload_bytes": 2000,
        }
    )

    summary = stats.summary()

    assert summary["frames"] == 2
    assert summary["left_capture_ms"]["mean"] == 15.0
    assert summary["left_capture_ms"]["max"] == 20.0
    assert summary["right_capture_ms"]["mean"] == 13.0
    assert summary["loop_total_ms"]["mean"] == 35.0
    assert summary["payload_bytes"]["mean"] == 1500.0


def test_pipeline_stats_flushes_only_on_configured_interval():
    stats = PipelineStats(interval_frames=3)

    assert stats.record({"loop_total_ms": 10.0}) is None
    assert stats.record({"loop_total_ms": 20.0}) is None

    summary = stats.record({"loop_total_ms": 30.0})

    assert summary is not None
    assert summary["frames"] == 3
    assert summary["loop_total_ms"]["mean"] == 20.0
    assert stats.summary()["frames"] == 0


def test_pipeline_stats_disabled_has_no_hot_path_storage():
    stats = PipelineStats(interval_frames=0)

    assert stats.enabled is False
    assert stats.record({"loop_total_ms": 10.0}) is None
    assert stats.summary()["frames"] == 0
