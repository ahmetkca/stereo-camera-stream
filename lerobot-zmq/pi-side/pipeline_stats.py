from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean, median


def _stage_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "p95": round(ordered[p95_index], 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


@dataclass
class PipelineStats:
    interval_frames: int = 0
    _frames: int = 0
    _samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    @property
    def enabled(self) -> bool:
        return self.interval_frames > 0

    def record(self, sample: dict[str, float]) -> dict[str, object] | None:
        if not self.enabled:
            return None

        self._frames += 1
        for key, value in sample.items():
            self._samples[key].append(float(value))

        if self._frames < self.interval_frames:
            return None

        summary = self.summary()
        self.reset()
        return summary

    def summary(self) -> dict[str, object]:
        summary: dict[str, object] = {"frames": self._frames}
        for key, values in self._samples.items():
            if values:
                summary[key] = _stage_summary(values)
        return summary

    def reset(self) -> None:
        self._frames = 0
        self._samples.clear()


def format_summary(summary: dict[str, object]) -> str:
    parts = [f"frames={summary['frames']}"]
    for key, value in summary.items():
        if key == "frames" or not isinstance(value, dict):
            continue
        mean_value = value.get("mean")
        p95_value = value.get("p95")
        if mean_value is not None and p95_value is not None:
            parts.append(f"{key}_mean={mean_value} {key}_p95={p95_value}")
    return "pipeline stats: " + " ".join(parts)
