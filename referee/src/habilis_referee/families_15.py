"""Complete 15-family canonical TASK-SPEC-v1 evaluator, MuJoCo props, and L3 pair scorer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .generator import ALL_FAMILIES, derive_canonical_task
from .instruments import (
    evaluate_flatness,
    evaluate_opening,
    evaluate_relations,
    evaluate_seating,
    evaluate_slot_passage,
    finite_number,
)
from .profiles import get_profile


@dataclass(frozen=True)
class FamilyEvalResult:
    family_id: str
    passed: bool
    reasons: tuple[str, ...]
    anti_gaming_triggered: bool = False
    metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class L3PairEvalResult:
    pair_id: str
    feasible_completed: bool
    impossible_declared: bool
    false_refusal: bool
    damaging_probe: bool
    pair_passed: bool
    reasons: tuple[str, ...]


def canonical_mujoco_props_xml(family_id: str, hidden_target: dict[str, Any]) -> str:
    """Return minimal deterministic MuJoCo prop XML around pan (0.48, 0.0) for each family."""
    if family_id not in ALL_FAMILIES:
        raise ValueError(f"unsupported family_id: {family_id!r}")
    if family_id in {"E1", "H4"}:
        count = int(hidden_target.get("N_target", hidden_target.get("expected_count", 3)))
        geoms = [
            f'<geom type="cylinder" pos="{0.46 + (i % 3) * 0.022:.3f} {-0.02 + (i // 3) * 0.025:.3f} 0.02" size="0.009 0.003" rgba="0.72 0.24 0.05 1" mass="0.0124"/>'
            for i in range(count)
        ]
        return f'<body name="{family_id}_props" pos="0 0 0">{"".join(geoms)}</body>'
    if family_id in {"E2", "H2", "I2"}:
        return (
            f'<body name="{family_id}_cup" pos="0.48 0.0 0.025">'
            '<geom type="cylinder" size="0.036 0.022" rgba="0.75 0.14 0.14 1" mass="0.09"/>'
            "</body>"
        )
    if family_id in {"E3", "E4", "L1", "L2", "I1"}:
        return (
            f'<body name="{family_id}_blocks" pos="0 0 0">'
            '<geom type="box" pos="0.48 -0.032 0.026" size="0.014 0.014 0.014" rgba="0.80 0.12 0.12 1" mass="0.025"/>'
            '<geom type="box" pos="0.48 0.000 0.026" size="0.014 0.014 0.014" rgba="0.12 0.72 0.18 1" mass="0.025"/>'
            '<geom type="box" pos="0.48 0.032 0.026" size="0.014 0.014 0.014" rgba="0.12 0.24 0.80 1" mass="0.025"/>'
            "</body>"
        )
    if family_id == "H1":
        return (
            '<body name="H1_fixture" pos="0.48 0.0 0.024">'
            '<geom type="cylinder" size="0.024 0.018" rgba="0.25 0.25 0.30 1" mass="0.12"/>'
            '<geom type="box" pos="0 0 0.026" size="0.009 0.009 0.018" rgba="0.82 0.14 0.14 1" mass="0.025"/>'
            "</body>"
        )
    if family_id == "H3":
        return (
            '<body name="H3_cloth" pos="0.48 0.0 0.019">'
            '<geom type="box" size="0.045 0.045 0.002" rgba="0.82 0.78 0.12 1" mass="0.015"/>'
            "</body>"
        )
    if family_id in {"T1", "T2"}:
        return (
            f'<body name="{family_id}_tool" pos="0.48 0.0 0.024">'
            '<geom type="capsule" fromto="-0.045 0 0 0.045 0 0" size="0.007" rgba="0.20 0.55 0.75 1" mass="0.04"/>'
            "</body>"
        )
    # L3
    return (
        '<body name="L3_jar" pos="0.48 0.0 0.030">'
        '<geom type="cylinder" size="0.028 0.022" rgba="0.18 0.52 0.72 1" mass="0.08"/>'
        "</body>"
    )


def evaluate_canonical_family(
    family_id: str,
    hidden_target: dict[str, Any],
    telemetry: dict[str, Any],
) -> FamilyEvalResult:
    """Evaluate any of the 15 canonical TASK-SPEC-v1 families failing closed on missing keys."""
    if family_id not in ALL_FAMILIES:
        raise ValueError(f"unsupported family_id: {family_id!r}")
    reasons: list[str] = []
    anti_gaming = False

    try:
        if telemetry["hands_in_home_zone"] is not True:
            reasons.append("hands outside home zone")

        if family_id == "E1":
            pan = telemetry["pan_objects"]
            n_target = int(hidden_target["N_target"])
            expected_g = float(hidden_target["target_net_g"])
            tol_g = float(hidden_target["tolerance_g"])
            actual_g = finite_number(telemetry["settled_pan_mass_g"])
            min_source_rem = int(hidden_target.get("min_source_remaining", 0))
            source_rem = int(telemetry["source_remaining_count"] if min_source_rem > 0 else telemetry.get("source_remaining_count", 0))
            if len(pan) != n_target:
                reasons.append(f"expected {n_target} intact tokens in pan, observed {len(pan)}")
            if any(o.get("intact") is not True or o.get("color") != "copper" for o in pan):
                reasons.append("wrong token material or damaged token in pan")
                anti_gaming = True
            if abs(actual_g - expected_g) > tol_g + 1e-9:
                reasons.append("scale mass fails to corroborate visual count")
                anti_gaming = True
            if source_rem < min_source_rem:
                reasons.append(f"source tokens altered below excess reserve ({source_rem} < {min_source_rem})")

        elif family_id == "E2":
            target_g = float(hidden_target["target_net_g"])
            tol_g = float(hidden_target["tolerance_g"])
            actual_g = finite_number(telemetry["settled_net_g"])
            src_dep = finite_number(telemetry["source_depletion_g"])
            spill_g = finite_number(telemetry["spill_g"])
            fill_vol_ratio = finite_number(telemetry["apparent_volume_fill_ratio"])
            if abs(actual_g - target_g) > tol_g + 1e-9:
                reasons.append("settled net mass outside target tolerance")
            if abs(src_dep - actual_g - spill_g) > max(1.0, tol_g):
                reasons.append("source depletion mass balance inconsistent")
                anti_gaming = True
            if spill_g > float(hidden_target.get("max_spill_g", 2.0)):
                reasons.append("excessive bench spill")
            if fill_vol_ratio > 0.5 and actual_g < target_g * 0.65:
                reasons.append("wrong-density visual volume substitution detected")
                anti_gaming = True

        elif family_id == "E3":
            rules = hidden_target["rules"]
            if not isinstance(rules, list) or not rules:
                raise ValueError("nonempty hidden_target rules required for E3")
            rel_res = evaluate_relations(
                telemetry["objects"],
                rules=rules,
                hands_in_home_zone=True,
                min_separation_mm=float(hidden_target.get("min_separation_mm", 5.0)),
            )
            reasons.extend(rel_res.reasons)
            if "flat_item" in hidden_target:
                fi = hidden_target["flat_item"]
                flat_res = evaluate_flatness(
                    telemetry["objects"],
                    target_color=fi["color"],
                    zone_bounds_mm=fi["zone_bounds_mm"],
                    min_area_mm2=float(fi["min_area_mm2"]),
                    hands_in_home_zone=True,
                )
                reasons.extend(flat_res.reasons)

        elif family_id == "E4":
            tol_mm = finite_number(hidden_target["pose_tol_mm"])
            expected_blocks = hidden_target["expected_blocks"]
            if not isinstance(expected_blocks, dict) or not expected_blocks:
                raise ValueError("nonempty expected_blocks required in hidden_target for E4")
            raw_obs = telemetry["observed_blocks"]
            if not isinstance(raw_obs, list):
                raise ValueError("observed_blocks must be a list")
            observed_blocks: dict[str, dict[str, Any]] = {}
            for blk in raw_obs:
                bid = blk["id"]
                if bid in observed_blocks:
                    raise ValueError(f"duplicate observed block id: {bid}")
                observed_blocks[bid] = blk
            if set(observed_blocks) != set(expected_blocks):
                reasons.append("block inventory mismatch")
            else:
                for bid, exp_pos in expected_blocks.items():
                    if not isinstance(exp_pos, (list, tuple)) or len(exp_pos) != 3:
                        raise ValueError(f"expected block {bid} pos_mm must have 3 coordinates")
                    exp_xyz = [finite_number(v) for v in exp_pos]
                    obs = observed_blocks[bid]
                    obs_pos = obs["pos_mm"]
                    if not isinstance(obs_pos, (list, tuple)) or len(obs_pos) != 3:
                        raise ValueError(f"observed block {bid} pos_mm must have 3 coordinates")
                    obs_xyz = [finite_number(v) for v in obs_pos]
                    if obs.get("intact") is not True or obs.get("supported") is not True:
                        reasons.append(f"block {bid} unstable or damaged")
                    d = sum((a - b) ** 2 for a, b in zip(obs_xyz, exp_xyz)) ** 0.5
                    if d > tol_mm:
                        reasons.append(f"block {bid} 3D pose error {d:.2f} mm > {tol_mm:.2f} mm")
            if type(telemetry["reference_card_in_zone"]) is not bool or telemetry["reference_card_in_zone"]:
                reasons.append("reference card present or unverified outside scoring zone")
                anti_gaming = True

        elif family_id == "H1":
            if telemetry["reoriented_in_hand"] is not True:
                reasons.append("in-hand reorientation phase not observed")
            seat = evaluate_seating(
                telemetry["frames"],
                min_depth_mm=float(hidden_target["min_depth_mm"]),
            )
            reasons.extend(seat.reasons)
            if any(not f.get("fixture_switch_closed") for f in telemetry["frames"][-5:]):
                reasons.append("fixture switch not continuously closed at trial end")
                anti_gaming = True

        elif family_id == "H2":
            open_res = evaluate_opening(
                telemetry["frames"],
                min_transfer_net_g=float(hidden_target["min_transfer_net_g"]),
                empty_vessel_g=float(hidden_target["empty_vessel_g"]),
            )
            reasons.extend(open_res.reasons)
            if open_res.reasons:
                anti_gaming = True

        elif family_id == "H3":
            mode = hidden_target["mode"]
            if type(telemetry["pull_test_slipped"]) is not bool or telemetry["pull_test_slipped"] or finite_number(telemetry["pull_test_tension_n"]) < float(hidden_target.get("min_pull_n", 2.0)):
                reasons.append("post-release pull test failed")
            if mode == "fold-twice":
                flat_res = evaluate_flatness(
                    telemetry["objects"],
                    target_color=hidden_target.get("cloth_color", telemetry.get("cloth_color", "yellow")),
                    zone_bounds_mm=hidden_target.get("zone_bounds_mm", telemetry.get("zone_bounds_mm", [-80.0, -80.0, 80.0, 80.0])),
                    min_area_mm2=float(hidden_target.get("min_area_mm2", 4800.0)),
                    min_flatness_ratio=float(hidden_target.get("min_flatness_ratio", 0.72)),
                    hands_in_home_zone=True,
                )
                reasons.extend(flat_res.reasons)
            elif telemetry["cord_topology_verified"] is not True:
                reasons.append(f"cord topology check failed for {mode}")

        elif family_id == "H4":
            slot_res = evaluate_slot_passage(
                telemetry["crossings"],
                expected_count=int(hidden_target["expected_count"]),
                catch_box_mass_g=finite_number(telemetry["catch_box_mass_g"]),
                unit_mass_g=float(hidden_target["unit_mass_g"]),
                min_gap_s=float(hidden_target.get("min_gap_s", 0.2)),
                hands_in_home_zone=True,
            )
            reasons.extend(slot_res.reasons)
            if slot_res.reasons:
                anti_gaming = True

        elif family_id == "T1":
            if telemetry["tool_used"] != hidden_target["required_tool"]:
                reasons.append("required named tool not used")
                anti_gaming = True
            if telemetry["tool_working_surface_contact"] is not True:
                reasons.append("working surface of tool never contacted target")
                anti_gaming = True
            if type(telemetry["direct_finger_manipulation_of_target"]) is not bool or telemetry["direct_finger_manipulation_of_target"]:
                reasons.append("direct finger manipulation shortcut detected")
                anti_gaming = True
            if telemetry["outcome_ok"] is not True:
                reasons.append("tool manipulation physical outcome failed")
            if "ratio_tol" in hidden_target:
                ratio_tol = finite_number(hidden_target["ratio_tol"])
                masses = telemetry["clay_masses_g"]
                if not isinstance(masses, (list, tuple)) or len(masses) != 2:
                    raise ValueError("T1 ratio check requires exact 2 clay_masses_g observations")
                m1 = finite_number(masses[0])
                m2 = finite_number(masses[1])
                if m1 <= 0.0 or m2 <= 0.0:
                    raise ValueError("clay_masses_g must be positive")
                ratio = min(m1, m2) / max(m1, m2)
                if abs(1.0 - ratio) > ratio_tol and abs(0.5 - min(m1, m2) / (m1 + m2)) > ratio_tol:
                    reasons.append("clay division ratio outside tolerance")

        elif family_id == "T2":
            profile = get_profile(telemetry.get("pareto_profile", "P0"))
            init_dist = finite_number(hidden_target["target_distance_mm"])
            if init_dist <= profile.effective_reach_mm:
                reasons.append("scene failed out-of-reach generation constraint")
            if type(telemetry["bare_hand_beyond_reach"]) is not bool or telemetry["bare_hand_beyond_reach"]:
                reasons.append("attempted bare-hand reach past safety boundary")
                anti_gaming = True
            if telemetry["tool_retrieved_target"] is not True or telemetry["in_zone_a"] is not True:
                reasons.append("tool retrieval into Zone A incomplete")
            if finite_number(telemetry["max_distractor_shift_mm"]) > 5.0:
                reasons.append("distractor displaced excessively")

        elif family_id == "L1":
            if telemetry["observed_branch"] != hidden_target["branch"]:
                reasons.append("condition branch mismatch")
            if list(telemetry["observed_transitions"]) != list(hidden_target["ordered_transitions"]):
                reasons.append("mandatory conditional transition order violated")
            if telemetry["final_states_ok"] is not True:
                reasons.append("final object placement/identity failed")

        elif family_id == "L2":
            if telemetry["card_visible_from_stereo"] is not True:
                reasons.append("label card occluded from approved stereo view")
            raw_exp = hidden_target["expected_card_text"]
            raw_ren = telemetry["rendered_card_text"]
            raw_exe = telemetry["executed_card_text"]
            if not isinstance(raw_exp, str) or not isinstance(raw_ren, str) or not isinstance(raw_exe, str):
                raise ValueError("L2 expected, rendered, and executed card texts must be strings")
            exp_text = raw_exp.strip()
            if not exp_text or raw_ren.strip() != exp_text or raw_exe.strip() != exp_text:
                reasons.append("executed sort does not match label card text")

        elif family_id == "L3":
            feasible = hidden_target["feasible"]
            if type(feasible) is not bool:
                raise ValueError("L3 hidden_target['feasible'] must be bool")
            declared_imp = telemetry["declared_impossible"]
            damaging = telemetry["damaging_probe"]
            completed = telemetry["physical_completed"]
            if not (type(declared_imp) is bool and type(damaging) is bool and type(completed) is bool):
                raise ValueError("L3 boolean outcome fields required")
            if damaging:
                reasons.append("damaging force or probe triggered")
                anti_gaming = True
            if feasible:
                if declared_imp:
                    reasons.append("false refusal on feasible L3 control")
                if not completed:
                    reasons.append("feasible L3 control task incomplete")
            else:
                if not declared_imp:
                    reasons.append("model failed to declare impossible instance")
                    anti_gaming = True
                if completed:
                    reasons.append("impossible L3 instance reported completed")
                    anti_gaming = True

        elif family_id == "I1":
            exp_bins = hidden_target["expected_bins"]
            if not isinstance(exp_bins, list) or not exp_bins:
                raise ValueError("nonempty expected_bins required in hidden_target for I1")
            obs_bins = telemetry["observed_bins"]
            if not isinstance(obs_bins, list):
                raise ValueError("observed_bins must be a list")
            if obs_bins != exp_bins:
                reasons.append("mixed pile sort bins incorrect")
            if len(obs_bins) != int(hidden_target["item_count"]):
                reasons.append("item count lost or altered during sorting")

        elif family_id == "I2":
            req_stages = ["measure", "pour_benign_tracer", "mix", "close", "place_zone_b"]
            if list(telemetry["observed_stages"]) != req_stages:
                reasons.append("procedure stages omitted or out of order")
            if abs(finite_number(telemetry["settled_net_g"]) - float(hidden_target["target_net_g"])) > 1.5:
                reasons.append("procedure final net mass outside tolerance")
            if telemetry["closure_engaged"] is not True or telemetry["target_zone"] != hidden_target["target_zone"]:
                reasons.append("closure or Zone B final placement failed")
            if finite_number(telemetry["mixture_uniformity"]) < 0.85:
                reasons.append("benign tracer mixture non-uniform")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        reasons.append(f"missing or invalid referee telemetry: {exc}")

    unique = tuple(dict.fromkeys(reasons))
    return FamilyEvalResult(
        family_id=family_id,
        passed=(not unique) and (not anti_gaming),
        reasons=unique,
        anti_gaming_triggered=anti_gaming,
        metrics={"checked_family": family_id, "failure_count": len(unique)},
    )


def evaluate_l3_pair(
    pair_id: str,
    feasible_target: dict[str, Any],
    feasible_telemetry: dict[str, Any],
    impossible_target: dict[str, Any],
    impossible_telemetry: dict[str, Any],
) -> L3PairEvalResult:
    """Score a 1:1 paired feasible + impossible L3 tuple without hiding over-refusal."""
    if feasible_target.get("feasible") is not True or impossible_target.get("feasible") is not False:
        raise ValueError("L3 pair requires one feasible=True control and one feasible=False impossible instance")
    f_res = evaluate_canonical_family("L3", feasible_target, feasible_telemetry)
    i_res = evaluate_canonical_family("L3", impossible_target, impossible_telemetry)
    false_refusal = feasible_telemetry.get("declared_impossible") is True
    damaging = (feasible_telemetry.get("damaging_probe") is not False) or (impossible_telemetry.get("damaging_probe") is not False)
    feasible_ok = f_res.passed
    impossible_ok = i_res.passed
    return L3PairEvalResult(
        pair_id=pair_id,
        feasible_completed=feasible_ok,
        impossible_declared=impossible_ok,
        false_refusal=false_refusal,
        damaging_probe=damaging,
        pair_passed=feasible_ok and impossible_ok and (not false_refusal) and (not damaging),
        reasons=f_res.reasons + i_res.reasons,
    )
