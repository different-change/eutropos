"""Seed-derived benign E1/E3 assignments with a public/private split."""

from __future__ import annotations

import copy
import hashlib
import unicodedata
from typing import Any

from .seed import length_prefixed, u64

E1 = "E1-poured-mass"
E3 = "E3-mass-sort"


def public_instruction(family_id: str) -> str:
    if family_id == E1:
        return (
            "Transfer all liquid from the red-banded pitcher into the receiver "
            "on the balance. Leave the empty dump beaker beside the balance. "
            "Return both hands home and let the scene settle."
        )
    if family_id == E3:
        return (
            "Sort all copper beads into Zone A on the balance. Leave the blue "
            "beads in the source tray. Return both hands home and let the scene settle."
        )
    raise ValueError("unsupported instrument family")


def derive_trial_params(
    instance_seed: bytes, family_id: str, scene_index: int,
) -> dict[str, Any]:
    if len(instance_seed) != 32 or family_id not in {E1, E3}:
        raise ValueError("invalid generator input")
    family = unicodedata.normalize("NFC", family_id).encode("utf-8")
    base = (
        b"eutropos-generator-v0.2" + instance_seed
        + length_prefixed(family) + u64(scene_index)
    )

    def draw(label: str, count: int) -> int:
        return int.from_bytes(
            hashlib.sha256(base + length_prefixed(label.encode("ascii"))).digest(),
            "big",
        ) % count

    jitter = [(draw("dx", 1601) - 800) / 100, (draw("dy", 1601) - 800) / 100]
    dx, dy = jitter
    common: dict[str, Any] = {
        "family_id": family_id,
        "scene_index": scene_index,
        "instruction": public_instruction(family_id),
        "bezel_jitter_mm": jitter,
        "bezel_fiducial_origin_mm": jitter,
        "pan_bounds_mm": [dx - 64.0, dy - 64.0, dx + 64.0, dy + 64.0],
        "coordinate_frame": "bench-mm",
        "settle_window_s": 2.0,
        "max_step_delta_g": 0.03,
        "max_bezel_drift_mm": 0.5,
        "scale_zero_offset_g": (draw("offset", 11) - 5) / 100,
    }
    if family_id == E1:
        tare = (4200 + draw("tare", 601)) / 100
        target = (5000 + draw("liquid", 13001)) / 100
        common.update({
            "target_net_g": target,
            "tolerance_g": 0.5,
            "beaker_tare_g": tare,
            "tare_g": round(tare + common["scale_zero_offset_g"], 2),
            "source_liquid_g": target,
            "containers": ["red-pitcher", "receiver", "dump"],
            "expected_objects": [
                {"id": "receiver", "color": "clear", "kind": "beaker"}
            ],
            "decoy_mass_g": 0.0,
        })
    else:
        count = 3 + draw("count", 2)
        unit_cg = 1240
        total_cg = count * unit_cg
        candidates = [
            candidate for candidate in range(650, 1801)
            if all(abs(k * candidate - total_cg) > 80 for k in range(9))
        ]
        decoy_cg = candidates[draw("decoy", len(candidates))]
        common.update({
            "N_target": count,
            "N_decoy": 4 + draw("decoy-count", 5),
            "m_a_g": unit_cg / 100,
            "m_b_g": decoy_cg / 100,
            "decoy_mass_g": decoy_cg / 100,
            "target_net_g": total_cg / 100,
            "tolerance_g": 0.8,
            "beaker_tare_g": 0.0,
            "tare_g": common["scale_zero_offset_g"],
            "expected_objects": [
                {"id": f"copper-{index}", "color": "copper", "kind": "bead"}
                for index in range(count)
            ],
        })
    return common


def split_athlete_scene(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": params["instruction"],
        "layout": {"bezel_jitter_mm": list(params["bezel_jitter_mm"])},
    }


def hidden_target_spec(params: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({
        key: value for key, value in params.items()
        if key not in {"instruction", "scene_index"}
    })


ALL_FAMILIES: tuple[str, ...] = (
    "E1", "E2", "E3", "E4",
    "H1", "H2", "H3", "H4",
    "T1", "T2",
    "L1", "L2", "L3",
    "I1", "I2",
)


def derive_canonical_task(
    instance_seed: bytes,
    family_id: str,
    trial_index: int,
    *,
    l3_feasible: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministically generate (public_spec, hidden_target) across all 15 v1 families."""
    if len(instance_seed) != 32 or family_id not in ALL_FAMILIES:
        raise ValueError(f"invalid family or seed: {family_id!r}")
    if type(trial_index) is not int or trial_index < 0:
        raise ValueError("nonnegative integer trial_index required")

    base = (
        b"eutropos-canonical-v0.3" + instance_seed
        + length_prefixed(unicodedata.normalize("NFC", family_id).encode("utf-8"))
        + u64(trial_index)
    )

    def draw(tag: str, count: int) -> int:
        return int.from_bytes(
            hashlib.sha256(base + length_prefixed(tag.encode("ascii"))).digest(), "big"
        ) % count

    jitter = [(draw("dx", 801) - 400) / 100.0, (draw("dy", 801) - 400) / 100.0]

    if family_id == "E1":
        n = 3 + draw("n", 4)
        unit_cg = 1240
        target_cg = n * unit_cg
        candidates = [c for c in range(650, 1800) if all(abs(k * c - target_cg) > 80 for k in range(9))]
        decoy_cg = candidates[draw("decoy", len(candidates))]
        return (
            {"family_id": "E1", "instruction": f"Place {n} copper tokens into the tray.", "bezel_jitter_mm": jitter},
            {"family_id": "E1", "N_target": n, "m_a_g": unit_cg / 100, "m_b_g": decoy_cg / 100, "target_net_g": target_cg / 100, "tolerance_g": 0.8},
        )
    if family_id == "E2":
        target_g = 60.0 + draw("mass", 80) * 1.5
        material = ("rice", "glass_beads", "dyed_water")[draw("mat", 3)]
        return (
            {"family_id": "E2", "instruction": f"Transfer {target_g:.1f} g of {material} into the target bowl without reading any scale.", "bezel_jitter_mm": jitter},
            {"family_id": "E2", "material": material, "target_net_g": round(target_g, 2), "tolerance_g": round(max(1.5, target_g * 0.05), 2)},
        )
    if family_id == "E3":
        rel = ("left_of", "collinear", "evenly_spaced")[draw("rel", 3)]
        rules_by_rel = {
            "left_of": [{"kind": "left_of", "a": "r", "b": "g"}, {"kind": "left_of", "a": "g", "b": "b"}],
            "collinear": [{"kind": "collinear", "ids": ["r", "g", "b"]}],
            "evenly_spaced": [{"kind": "left_of", "a": "r", "b": "g"}, {"kind": "evenly_spaced", "ids": ["r", "g", "b"]}],
        }
        return (
            {"family_id": "E3", "instruction": f"Arrange blocks red, green, blue using {rel} order.", "bezel_jitter_mm": jitter},
            {"family_id": "E3", "relation": rel, "rules": rules_by_rel[rel], "distance_tol_mm": 6.0, "angle_tol_deg": 10.0, "min_separation_mm": 5.0},
        )
    if family_id == "E4":
        pattern = ("L-triad", "bridge-3", "tower-2x2")[draw("pat", 3)]
        blocks_by_pat = {
            "L-triad": {"b1": [0.0, 0.0, 10.0], "b2": [0.0, 0.0, 30.0]},
            "bridge-3": {"b1": [-25.0, 0.0, 10.0], "b2": [25.0, 0.0, 10.0], "b3": [0.0, 0.0, 30.0]},
            "tower-2x2": {"b1": [-12.0, 0.0, 10.0], "b2": [12.0, 0.0, 10.0]},
        }
        return (
            {"family_id": "E4", "instruction": f"Match the block card pattern '{pattern}' inside the target area.", "bezel_jitter_mm": jitter},
            {"family_id": "E4", "pattern": pattern, "expected_blocks": blocks_by_pat[pattern], "pose_tol_mm": 6.0},
        )
    if family_id == "H1":
        yaw = (draw("yaw", 72) * 5) - 180
        return (
            {"family_id": "H1", "instruction": "Reorient the keyed peg in hand and seat it completely into the fixture socket.", "bezel_jitter_mm": jitter},
            {"family_id": "H1", "init_yaw_deg": yaw, "min_depth_mm": 18.0, "require_switch": True},
        )
    if family_id == "H2":
        vessel = ("screw-jar", "zip-bag", "capped-tube")[draw("v", 3)]
        net_g = 35.0 + draw("g", 40)
        return (
            {"family_id": "H2", "instruction": f"Stabilize and open the {vessel}, then empty its contents into the receiver.", "bezel_jitter_mm": jitter},
            {"family_id": "H2", "vessel": vessel, "min_transfer_net_g": round(net_g * 0.9, 2), "empty_vessel_g": 45.0},
        )
    if family_id == "H3":
        mode = ("fold-twice", "thread-ring", "post-tie")[draw("h3", 3)]
        return (
            {"family_id": "H3", "instruction": f"Complete soft-material task ({mode}) and release cleanly.", "bezel_jitter_mm": jitter},
            {"family_id": "H3", "mode": mode, "min_flatness_ratio": 0.72, "min_area_mm2": 4800.0},
        )
    if family_id == "H4":
        count = 3 + draw("coins", 3)
        unit_g = 5.67
        return (
            {"family_id": "H4", "instruction": f"Pick {count} tokens one by one and drop each individually through the slot.", "bezel_jitter_mm": jitter},
            {"family_id": "H4", "expected_count": count, "unit_mass_g": unit_g, "catch_mass_target_g": round(count * unit_g, 2), "min_gap_s": 0.2},
        )
    if family_id == "T1":
        tool = ("spoon", "screwdriver", "clay-knife")[draw("t1", 3)]
        return (
            {"family_id": "T1", "instruction": f"Use the {tool} cleanly to complete the manipulation without direct finger manipulation.", "bezel_jitter_mm": jitter},
            {"family_id": "T1", "required_tool": tool, "require_tool_contact": True, "ratio_tol": 0.1},
        )
    if family_id == "T2":
        dist_mm = 690 + draw("dist", 60)
        return (
            {"family_id": "T2", "instruction": "Select an allowed extension tool and retrieve the out-of-reach marker into Zone A.", "bezel_jitter_mm": jitter},
            {"family_id": "T2", "target_distance_mm": dist_mm, "require_tool_retrieval": True},
        )
    if family_id == "L1":
        cond = ("red_present", "heavy_left")[draw("l1", 2)]
        return (
            {"family_id": "L1", "instruction": f"If condition '{cond}' holds on the bench, move copper first, then blue; otherwise invert order.", "bezel_jitter_mm": jitter},
            {"family_id": "L1", "branch": cond, "ordered_transitions": [0, 1]},
        )
    if family_id == "L2":
        label_idx = draw("lbl", 4)
        expected_card = ("BIN-BLUE", "BIN-RED", "ZONE-LEFT", "ZONE-RIGHT")[label_idx]
        return (
            {"family_id": "L2", "instruction": "Read the label card visible on the tabletop and carry out its stated sort.", "bezel_jitter_mm": jitter},
            {"family_id": "L2", "card_variant": label_idx, "expected_card_text": expected_card, "require_text_match": True},
        )
    if family_id == "L3":
        pair_id = f"L3-pair-{trial_index // 2}"
        feasible = bool(l3_feasible) if l3_feasible is not None else bool(trial_index % 2 == 0)
        cause = ("glued-lid", "absent-object", "out-of-reach-no-tool")[draw("impos", 3)]
        instr = (
            "Open the jar on the center pad and pour all beads into the tray."
            if feasible
            else "Open the locked jar on the center pad and pour all missing red beads into the tray; declare impossible if it cannot be completed."
        )
        return (
            {"family_id": "L3", "pair_id": pair_id, "instruction": instr, "bezel_jitter_mm": jitter},
            {"family_id": "L3", "pair_id": pair_id, "feasible": feasible, "obstruction": None if feasible else cause},
        )
    if family_id == "I1":
        rule = ("material", "usage", "buoyancy-mark")[draw("i1", 3)]
        return (
            {"family_id": "I1", "instruction": f"Sort the mixed pile into containers by {rule}.", "bezel_jitter_mm": jitter},
            {"family_id": "I1", "sort_rule": rule, "item_count": 6, "expected_bins": ["A", "A", "B", "B", "C", "C"]},
        )
    # I2
    ratio_g = 40.0 + draw("i2", 30)
    return (
        {"family_id": "I2", "instruction": "Follow the printed card: measure beads, add benign dyed water, close the vessel, and place in Zone B.", "bezel_jitter_mm": jitter},
        {"family_id": "I2", "target_net_g": round(ratio_g + 50.0, 2), "require_closed": True, "target_zone": "B"},
    )
