"""Tests for multi-lab A4 VLM harness, Gemini REST adapter, blind inbox, and pairwise McNemar."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from eutropos_referee.a4_harness import (
    analyze_a4_results,
    export_blind_inbox,
    export_blinded_trial_frames,
    run_gemini_vision,
    score_trial_claude_opus,
    score_trial_datacenterbench_dual,
    score_trial_gemini_neon,
    score_trial_robodojo_astra,
)


def test_gemini_vision_mock_and_blind_inbox(tmp_path: Path) -> None:
    frames = [np.full((32, 32, 3), 180, dtype=np.uint8) for _ in range(3)]
    pkg = export_blinded_trial_frames(
        tmp_path / "inbox",
        "tr_00_123456",
        "Place 3 copper coins in the tray leaving remaining coins untouched.",
        frames,
        frames,
    )
    manifest_p = export_blind_inbox(tmp_path / "inbox", [pkg])
    raw_txt = manifest_p.read_text(encoding="utf-8")
    doc = json.loads(raw_txt)
    assert len(doc["trials"]) == 1
    assert set(doc["trials"][0]) == {"opaque_id", "instruction", "left_frames", "right_frames"}
    assert "S1" not in raw_txt and "ground_truth" not in raw_txt and "family" not in raw_txt

    seen_urls: list[str] = []

    def fake_transport(url: str, body: dict) -> dict:
        seen_urls.append(url)
        assert len(body["contents"][0]["parts"]) == 7  # 6 images + 1 prompt
        return {"candidates": [{"content": {"parts": [{"text": '{"verdict":"PASS","reason":"ok"}'}]}}]}

    text, lat = run_gemini_vision(
        "Judge this trial.",
        list(pkg.head_left_paths) + list(pkg.head_right_paths),
        model="gemini-4-neon",
        api_key="test-key",
        transport=fake_transport,
    )
    assert '"verdict":"PASS"' in text
    assert lat >= 0.0 and "gemini-4-neon" in seen_urls[0]


def test_four_judge_a4_analysis_and_pairwise_mcnemar(tmp_path: Path) -> None:
    frames = [np.zeros((16, 16, 3), dtype=np.uint8) for _ in range(3)]
    pkg = export_blinded_trial_frames(tmp_path / "f", "tr_99_654321", "Task.", frames, frames)
    r_pass = lambda _p, _i: ('{"verdict":"PASS","reason":"ok"}', 0.1)
    r_fail = lambda _p, _i: ('{"verdict":"FAIL","reason":"no"}', 0.1)

    records = []
    for idx, (fam, strat, gt) in enumerate([
        ("E1", "S1", 1), ("E1", "S2", 0), ("E1", "S3", 0), ("E1", "S4", 0),
        ("E2", "S1", 1), ("E2", "S2", 0), ("E2", "S3", 0), ("E2", "S4", 0),
    ]):
        records.append({
            "opaque_id": f"tr_{idx:02d}_111111",
            "family_id": fam,
            "stratum": strat,
            "ground_truth": gt,
            "robodojo_astra": score_trial_robodojo_astra(pkg, runner=r_pass if gt else r_fail),
            "claude_opus_5_5": score_trial_claude_opus(pkg, runner=r_pass if gt else r_fail),
            "datacenterbench_dual": score_trial_datacenterbench_dual(
                pkg, astra_runner=r_pass if gt else r_fail, claude_runner=r_pass if gt else r_fail
            ),
            "gemini_4_neon": score_trial_gemini_neon(
                pkg, runner=r_pass if (gt or strat == "S4") else r_fail
            ),
        })

    stats = analyze_a4_results(
        records,
        judge_keys=("robodojo_astra", "claude_opus_5_5", "datacenterbench_dual", "gemini_4_neon"),
        bootstrap_n=200,
    )
    assert stats["n_trials"] == 8
    assert stats["judges"]["robodojo_astra"]["stop_use_triggered"] is False
    assert stats["judges"]["gemini_4_neon"]["stop_use_triggered"] is True
    assert "robodojo_astra__vs__gemini_4_neon" in stats["pairwise_mcnemar"]
    assert stats["pairwise_mcnemar"]["robodojo_astra__vs__gemini_4_neon"]["only_second_fp"] == 2
