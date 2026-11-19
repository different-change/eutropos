"""Binary multi-scorer results and Wilson 95 percent intervals."""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

Z_95 = 1.959963984540054


def wilson_95(passes: int, trials: int) -> list[float]:
    if type(passes) is not int or type(trials) is not int or trials <= 0 or not 0 <= passes <= trials:
        raise ValueError("invalid Wilson counts")
    p = passes / trials
    denominator = 1 + Z_95**2 / trials
    center = (p + Z_95**2 / (2 * trials)) / denominator
    radius = Z_95 * math.sqrt(
        p * (1 - p) / trials + Z_95**2 / (4 * trials**2)
    ) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def diagnostics(trials: list[dict[str, Any]]) -> dict[str, Any]:
    steps = [trial["step_count"] for trial in trials]
    if any(type(value) is not int or value < 0 for value in steps):
        raise ValueError("invalid step count")
    latencies = [value for trial in trials for value in trial["inference_latencies_s"]]
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
        for value in latencies
    ):
        raise ValueError("invalid inference latency")
    return {
        "total_steps": sum(steps),
        "mean_inference_latency_s": mean(latencies) if latencies else None,
    }


def _summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    names = set(trials[0]["scores"])
    if not names or any(set(trial["scores"]) != names for trial in trials):
        raise ValueError("inconsistent scorer set")
    for trial in trials:
        if any(
            type(value) not in (int, float) or value not in (0, 1)
            for value in trial["scores"].values()
        ):
            raise ValueError("scores must be binary")
    passes = sum(all(value == 1 for value in trial["scores"].values()) for trial in trials)
    return {
        "passes": passes, "trials": len(trials),
        "pass_rate": passes / len(trials),
        "wilson_95": wilson_95(passes, len(trials)),
        "scorer_means": {
            name: mean(trial["scores"][name] for trial in trials) for name in sorted(names)
        },
        "diagnostics": diagnostics(trials),
    }


def summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    if not trials:
        raise ValueError("cannot summarize an empty run")
    scenes: dict[str, list[dict]] = {}
    families: dict[str, list[dict]] = {}
    for trial in trials:
        scenes.setdefault(trial["scene_id"], []).append(trial)
        families.setdefault(trial["family_id"], []).append(trial)
    return {
        "overall": _summary(trials),
        "per_scene": [
            {"scene_id": name, "family_id": group[0]["family_id"], **_summary(group)}
            for name, group in scenes.items()
        ],
        "per_family": [
            {"family_id": name, **_summary(group)} for name, group in families.items()
        ],
        "diagnostics": diagnostics(trials),
        "body_ceiling": {"status": "not_measured", "season": "mock-v0.2"},
        "scripted_floor": {
            "status": "not_measured", "reference_policy": "scripted",
            "season": "mock-v0.2",
        },
    }
