"""Verification tests covering all 15 canonical TASK-SPEC-v1 families and L3 pairs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eutropos_referee.families_15 import (
    canonical_mujoco_props_xml,
    evaluate_canonical_family,
    evaluate_l3_pair,
)
from eutropos_referee.generator import ALL_FAMILIES, derive_canonical_task


def test_all_15_canonical_families_pass_and_reject_cheats() -> None:
    seed = hashlib.sha256(b"canonical-15-test-seed").digest()
    specs = {fam: derive_canonical_task(seed, fam, idx) for idx, fam in enumerate(ALL_FAMILIES)}

    # E1: Count by sight + conserved excess source coins
    _, h_e1 = specs["E1"]
    h_e1_ext = {**h_e1, "min_source_remaining": 2}
    n_e1 = int(h_e1["N_target"])
    ok_e1 = evaluate_canonical_family("E1", h_e1_ext, {
        "hands_in_home_zone": True,
        "pan_objects": [{"intact": True, "color": "copper"} for _ in range(n_e1)],
        "settled_pan_mass_g": h_e1["target_net_g"],
        "source_remaining_count": 2,
    })
    assert ok_e1.passed, ok_e1.reasons
    cheat_e1 = evaluate_canonical_family("E1", h_e1_ext, {
        "hands_in_home_zone": True,
        "pan_objects": [{"intact": True, "color": "copper"} for _ in range(n_e1)],
        "settled_pan_mass_g": 12.6,  # thin-shell decoy lookalikes
        "source_remaining_count": 2,
    })
    assert not cheat_e1.passed and cheat_e1.anti_gaming_triggered

    # E2: Measure by eye (blocks wrong-density foam substitution)
    _, h_e2 = specs["E2"]
    ok_e2 = evaluate_canonical_family("E2", h_e2, {
        "hands_in_home_zone": True,
        "settled_net_g": h_e2["target_net_g"],
        "source_depletion_g": h_e2["target_net_g"],
        "spill_g": 0.0,
        "apparent_volume_fill_ratio": 1.0,
    })
    assert ok_e2.passed
    cheat_e2 = evaluate_canonical_family("E2", h_e2, {
        "hands_in_home_zone": True,
        "settled_net_g": h_e2["target_net_g"] * 0.45,
        "source_depletion_g": h_e2["target_net_g"] * 0.45,
        "spill_g": 0.0,
        "apparent_volume_fill_ratio": 0.85,
    })
    assert not cheat_e2.passed and cheat_e2.anti_gaming_triggered

    # E3: Arrange by description
    _, h_e3 = specs["E3"]
    ok_e3 = evaluate_canonical_family("E3", h_e3, {
        "hands_in_home_zone": True,
        "objects": [
            {"id": "r", "bounds_mm": [-45.0, -5.0, -35.0, 5.0]},
            {"id": "g", "bounds_mm": [-5.0, -5.0, 5.0, 5.0]},
            {"id": "b", "bounds_mm": [35.0, -5.0, 45.0, 5.0]},
        ],
        "rules": [{"kind": "left_of", "a": "r", "b": "g"}, {"kind": "evenly_spaced", "ids": ["r", "g", "b"]}],
    })
    assert ok_e3.passed

    # E4: Match a picture + card exclusion guard
    _, h_e4 = specs["E4"]
    ok_e4 = evaluate_canonical_family("E4", h_e4, {
        "hands_in_home_zone": True,
        "observed_blocks": [
            {"id": bid, "intact": True, "supported": True, "pos_mm": [pos[0] + 0.5, pos[1], pos[2]]}
            for bid, pos in h_e4["expected_blocks"].items()
        ],
        "reference_card_in_zone": False,
    })
    assert ok_e4.passed, ok_e4.reasons
    bad_e4 = evaluate_canonical_family("E4", h_e4, {
        "hands_in_home_zone": True,
        "observed_blocks": [
            {"id": bid, "intact": True, "supported": True, "pos_mm": list(pos)}
            for bid, pos in h_e4["expected_blocks"].items()
        ],
        "reference_card_in_zone": True,
    })
    assert not bad_e4.passed and bad_e4.anti_gaming_triggered

    # H1: Reorient and insert
    _, h_h1 = specs["H1"]
    frames_h1 = [
        {"t_s": k / 10.0, "hands_in_home_zone": True, "fixture_switch_closed": True, "insertion_depth_mm": 22.0}
        for k in range(15)
    ]
    assert evaluate_canonical_family("H1", h_h1, {"hands_in_home_zone": True, "reoriented_in_hand": True, "frames": frames_h1}).passed
    frames_h1_fake = [
        {"t_s": k / 10.0, "hands_in_home_zone": True, "fixture_switch_closed": False, "insertion_depth_mm": 0.0}
        for k in range(15)
    ]
    assert evaluate_canonical_family("H1", h_h1, {"hands_in_home_zone": True, "reoriented_in_hand": True, "frames": frames_h1_fake}).anti_gaming_triggered

    # H2: Two-hand opening
    _, h_h2 = specs["H2"]
    frames_h2 = [
        {
            "t_s": k / 10.0,
            "hands_in_home_zone": True,
            "container_intact": True,
            "closure_open": True,
            "two_hand_hold_observed": True,
            "transferred_net_g": h_h2["min_transfer_net_g"] + 5.0,
        }
        for k in range(15)
    ]
    assert evaluate_canonical_family("H2", h_h2, {"hands_in_home_zone": True, "frames": frames_h2}).passed

    # H3: Soft things + pull test
    _, h_h3 = specs["H3"]
    assert evaluate_canonical_family("H3", h_h3, {
        "hands_in_home_zone": True,
        "pull_test_tension_n": 4.0,
        "pull_test_slipped": False,
        "cord_topology_verified": True,
        "objects": [{"id": "c", "color": "yellow", "intact": True, "area_mm2": 5200.0, "flatness_ratio": 0.85, "bounds_mm": [-40.0, -40.0, 40.0, 40.0]}],
    }).passed
    assert not evaluate_canonical_family("H3", h_h3, {"hands_in_home_zone": True, "pull_test_tension_n": 0.2, "pull_test_slipped": True}).passed

    # H4: Small things sequential crossings
    _, h_h4 = specs["H4"]
    n_h4 = int(h_h4["expected_count"])
    cross = [{"t_s": float(i + 1), "object_id": f"c{i}", "intact": True, "released": True} for i in range(n_h4)]
    assert evaluate_canonical_family("H4", h_h4, {
        "hands_in_home_zone": True,
        "crossings": cross,
        "catch_box_mass_g": h_h4["catch_mass_target_g"],
    }).passed

    # T1: Tool causation vs finger pinch cheat
    _, h_t1 = specs["T1"]
    assert evaluate_canonical_family("T1", h_t1, {
        "hands_in_home_zone": True,
        "tool_used": h_t1["required_tool"],
        "tool_working_surface_contact": True,
        "direct_finger_manipulation_of_target": False,
        "outcome_ok": True,
        "clay_masses_g": [50.0, 50.0],
    }).passed
    cheat_t1 = evaluate_canonical_family("T1", h_t1, {
        "hands_in_home_zone": True,
        "tool_used": h_t1["required_tool"],
        "tool_working_surface_contact": False,
        "direct_finger_manipulation_of_target": True,
        "outcome_ok": True,
        "clay_masses_g": [50.0, 50.0],
    })
    assert not cheat_t1.passed and cheat_t1.anti_gaming_triggered

    # T2: Reach envelope tool retrieval vs bare-hand reach
    _, h_t2 = specs["T2"]
    assert evaluate_canonical_family("T2", h_t2, {
        "hands_in_home_zone": True,
        "pareto_profile": "P0",
        "bare_hand_beyond_reach": False,
        "tool_retrieved_target": True,
        "in_zone_a": True,
        "max_distractor_shift_mm": 1.0,
    }).passed
    cheat_t2 = evaluate_canonical_family("T2", h_t2, {
        "hands_in_home_zone": True,
        "pareto_profile": "P0",
        "bare_hand_beyond_reach": True,
        "tool_retrieved_target": True,
        "in_zone_a": True,
    })
    assert not cheat_t2.passed and cheat_t2.anti_gaming_triggered

    # L1: Long conditional instruction + transitions
    _, h_l1 = specs["L1"]
    assert evaluate_canonical_family("L1", h_l1, {
        "hands_in_home_zone": True,
        "observed_branch": h_l1["branch"],
        "observed_transitions": h_l1["ordered_transitions"],
        "final_states_ok": True,
    }).passed

    # L2: Read from world
    _, h_l2 = specs["L2"]
    assert evaluate_canonical_family("L2", h_l2, {
        "hands_in_home_zone": True,
        "card_visible_from_stereo": True,
        "rendered_card_text": h_l2["expected_card_text"],
        "executed_card_text": h_l2["expected_card_text"],
    }).passed

    # L3: 1:1 feasible + impossible pair
    _, f_l3 = derive_canonical_task(seed, "L3", 0, l3_feasible=True)
    _, i_l3 = derive_canonical_task(seed, "L3", 1, l3_feasible=False)
    pair_ok = evaluate_l3_pair(
        f_l3["pair_id"],
        f_l3,
        {"hands_in_home_zone": True, "physical_completed": True, "declared_impossible": False, "damaging_probe": False},
        i_l3,
        {"hands_in_home_zone": True, "physical_completed": False, "declared_impossible": True, "damaging_probe": False},
    )
    assert pair_ok.pair_passed is True and pair_ok.false_refusal is False
    pair_overrefuse = evaluate_l3_pair(
        f_l3["pair_id"],
        f_l3,
        {"hands_in_home_zone": True, "physical_completed": False, "declared_impossible": True, "damaging_probe": False},
        i_l3,
        {"hands_in_home_zone": True, "physical_completed": False, "declared_impossible": True, "damaging_probe": False},
    )
    assert pair_overrefuse.pair_passed is False and pair_overrefuse.false_refusal is True

    # I1: Sort mixed pile
    _, h_i1 = specs["I1"]
    assert evaluate_canonical_family("I1", h_i1, {
        "hands_in_home_zone": True,
        "observed_bins": list(h_i1["expected_bins"]),
        "total_accounted_items": h_i1["item_count"],
    }).passed

    # I2: Multi-step procedure
    _, h_i2 = specs["I2"]
    assert evaluate_canonical_family("I2", h_i2, {
        "hands_in_home_zone": True,
        "observed_stages": ["measure", "pour_benign_tracer", "mix", "close", "place_zone_b"],
        "settled_net_g": h_i2["target_net_g"],
        "closure_engaged": True,
        "target_zone": h_i2["target_zone"],
        "mixture_uniformity": 0.94,
    }).passed


def test_canonical_15_mujoco_renders() -> None:
    pytest.importorskip("mujoco")
    from eutropos_referee.mujoco_bench import BimanualNeroBench

    seed = hashlib.sha256(b"mujoco-15-render").digest()
    for idx, fam in enumerate(ALL_FAMILIES):
        _, hid = derive_canonical_task(seed, fam, idx)
        xml = canonical_mujoco_props_xml(fam, hid)
        bench = BimanualNeroBench(props_xml=xml)
        try:
            views = bench.reset_scene()
            assert views["head_left"].shape == (480, 640, 3)
            assert views["overhead"].shape == (240, 240, 3)
        finally:
            bench.close()


def test_closed_loop_p0_isolated_trial(tmp_path: Path) -> None:
    pytest.importorskip("mujoco")
    from eutropos_referee.vlm_policy import run_closed_loop_p0_trial

    res = run_closed_loop_p0_trial(tmp_path / "p0_mock", backend="mock", max_steps=3, live_crypto=False)
    assert res["steps_executed"] == 3
    assert res["v1_verification_passed"] is True
    assert res["instrument_task_passed"] is False
    for st in res["steps"]:
        aud = st["isolation_audit"]
        assert aud["worker_pid"] != res["parent_pid"]
        assert aud["cwd_initial_empty"] is True
        assert aud["instruments_loaded"] is False
