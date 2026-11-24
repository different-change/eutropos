"""Generate sanitized static JSON and evidence bundle datasets for site/ and pitch/."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "referee" / "src"))

from eutropos_referee import __version__  # noqa: E402
from eutropos_referee.disclosure import DISCLOSURE_HAZARD  # noqa: E402
from eutropos_referee.generator import ALL_FAMILIES  # noqa: E402
from eutropos_referee.manifest import read_json, write_json  # noqa: E402
from eutropos_referee.profiles import PROFILES  # noqa: E402

SITE_DATA = REPO / "site" / "data"
SHOWCASE_IDS = (
    "tr_57_962127",
    "tr_40_574742",
    "tr_10_919818",
    "tr_23_604214",
    "tr_05_763838",
    "tr_58_849446",
)

_FAMILY_META: dict[str, tuple[str, str]] = {
    "E1": ("Count by sight", "N intact tokens, hands-clear settled CBCP-01 mass corroborates visual count."),
    "E2": ("Measure by eye", "Material identity, source depletion, destination net gain, spill limit, stable mass."),
    "E3": ("Arrange by description", "Named poses in declared frame, minimum span, footprint separation, flatness."),
    "E4": ("Match a picture", "Complete inventory, 3D block poses, support relations, hands-clear stability."),
    "H1": ("Reorient and insert", "Keyed peg orientation, >= 18 mm hidden seating depth, collar switch closed."),
    "H2": ("Two-hand opening", "Holding hand stabilization, intact opening transition, >= min net transfer mass."),
    "H3": ("Soft things", "Material integrity, fold layers or cord topology, post-release pull test."),
    "H4": ("Small things", "Individual coin/screw pickup, >= 0.2 s slot crossings, isolated catch mass."),
    "T1": ("Use a named tool", "Working-surface tool causation vs direct pinching, mass/screw/split ratio."),
    "T2": ("Find a tool", "Beyond bare-hand reach envelope retrieval via allowed tool, Zone A containment."),
    "L1": ("Long instruction with conditions", "Scene-dependent branch order, intermediate transitions, final object states."),
    "L2": ("Read from the world", "Counterbalanced visible card text recorded alongside sorted target state."),
    "L3": ("Know when to stop", "1:1 paired impossible vs feasible controls; abstention score; probe rejection."),
    "I1": ("Sort a mixed pile", "Spoken property rule sort, complete bin membership, benign float cues."),
    "I2": ("Procedure from written card", "Multi-step benign liquid/bead measure, mix, seal closure, Zone B placement."),
}


def _export_bundle(src_dir: Path, pubkey_path: Path, dst_dir: Path, *, hazard: bool = False) -> None:
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    rel_files: list[str] = []
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src_dir).as_posix()
        if hazard and rel in {"seed_reveal.json", "referee_targets.json"}:
            raise RuntimeError(f"forbidden secret file inside hazard bundle: {rel}")
        out = dst_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        rel_files.append(rel)
    shutil.copy2(pubkey_path, dst_dir.parent / f"{dst_dir.name}.trusted.pem")
    write_json(
        dst_dir.parent / f"{dst_dir.name}.index.json",
        {
            "version": __version__,
            "disclosure_mode": DISCLOSURE_HAZARD if hazard else "general-open",
            "trusted_public_key": f"{dst_dir.name}.trusted.pem",
            "files": rel_files,
        },
    )


def _export_a4_study_and_showcase() -> None:
    src_study = read_json(REPO / "sandbox" / "logs" / "a4-three-lab-60" / "study_results.json")
    blind_dir = REPO / "sandbox" / "logs" / "a4-three-lab-60" / "blind_inbox"
    showcase_dir = SITE_DATA / "a4_showcase"
    if showcase_dir.exists():
        shutil.rmtree(showcase_dir)
    showcase_dir.mkdir(parents=True, exist_ok=True)

    judge_order = ("robodojo_astra", "claude_opus_5_5", "datacenterbench_dual", "gemini_4_neon")
    sanitized_trials: list[dict[str, Any]] = []
    showcase_rows: list[dict[str, Any]] = []

    for tr in src_study["trials"]:
        oid = tr["opaque_id"]
        verdicts: dict[str, Any] = {}
        for j in judge_order:
            entry = tr[j]
            reason = entry.get("reason")
            if not reason and "astra" in entry and "claude" in entry:
                reason = (
                    f"Astra [{entry['astra']['category']}]: {entry['astra']['reason']} "
                    f"| Opus [{entry['claude']['category']}]: {entry['claude']['reason']}"
                )
            verdicts[j] = {
                "category": entry["category"],
                "v_binary": entry["v_binary"],
                "abstained": entry["abstained"],
                "reason": reason or "",
            }
        row = {
            "opaque_id": oid,
            "family_id": tr["family_id"],
            "stratum": tr["stratum"],
            "instruction": tr["instruction"],
            "ground_truth": tr["ground_truth"],
            "gt_reason": tr["gt_reason"],
            "mass_eval_passed": tr.get("mass_eval_passed"),
            "overhead_drift_mm": tr.get("overhead_drift_mm"),
            "verdicts": verdicts,
        }
        sanitized_trials.append(row)

        if oid in SHOWCASE_IDS:
            t_dir = blind_dir / oid
            lefts = sorted(t_dir.glob("cam_left_*.png"))
            rights = sorted(t_dir.glob("cam_right_*.png"))
            out_l = showcase_dir / f"{oid}_left.jpg"
            out_r = showcase_dir / f"{oid}_right.jpg"
            with Image.open(lefts[-1]) as im_l:
                im_l.convert("RGB").resize((360, 270)).save(out_l, format="JPEG", quality=84)
            with Image.open(rights[-1]) as im_r:
                im_r.convert("RGB").resize((360, 270)).save(out_r, format="JPEG", quality=84)
            showcase_rows.append({
                **row,
                "left_img": f"data/a4_showcase/{oid}_left.jpg",
                "right_img": f"data/a4_showcase/{oid}_right.jpg",
            })

    out_doc = {
        "cohort": {
            "n_trials": 60,
            "families": ["E1", "E2", "E3", "H1", "H2", "H4"],
            "strata": {"S1": 15, "S2": 15, "S3": 15, "S4": 15},
            "scope_note": "Synthetic 3D AgileX NERO MuJoCo stereo renders paired with simulated CBCP-01 and hidden overhead geometry. Confirmatory physical 240-trial experiment awaits hardware purchase.",
            "instrument_fpr": 0.0,
            "instrument_ffr": 0.0,
        },
        "statistics": src_study["statistics"],
        "showcase": showcase_rows,
        "trials": sanitized_trials,
    }
    write_json(SITE_DATA / "a4_study.json", out_doc)


def _export_rig_frontier() -> None:
    profiles = []
    for p in PROFILES.values():
        divisions = (
            ["blind-stereo-tactile", "blind-stereo-nontactile (mask_tactile=True)"]
            if p.has_tactile
            else ["blind-stereo-nontactile"]
        )
        profiles.append({
            "profile_id": p.profile_id,
            "title": p.title,
            "arms": p.arm_model,
            "hands": p.hand_model,
            "arm_dof": p.arm_dof,
            "finger_dof_per_hand": p.finger_dof_per_hand,
            "total_dof": p.total_dof,
            "has_tactile": p.has_tactile,
            "nominal_reach_mm": p.nominal_reach_mm,
            "effective_reach_mm": p.effective_reach_mm,
            "nominal_payload_kg": p.nominal_payload_kg,
            "listed_subtotal_usd": p.cost_tier_usd,
            "licence_summary": p.open_cad_licence,
            "divisions": divisions,
        })

    doc = {
        "a4_sensor_bench": {
            "name": "Minimal Physical A4 Core Sensor Subtotal",
            "total_usd": 1291,
            "items": [
                {"item": "Radwag WTC 2000 Precision Balance (CBCP-01 RS232/USB, 2000 g, 0.01 g)", "price_usd": 466, "source": "radwagusa.com"},
                {"item": "Basler ace 2 a2A2448-75ucBAS USB3 + Computar V0828-MPY 8 mm C-mount lens", "price_usd": 825, "source": "baslerweb.com + edmundoptics.com"},
            ],
            "note": "Covers the balance and overhead pose channels for the pre-registered 240-trial physical A4 validation before arm/hand capital expenditure; head stereo camera and H1/H4 fixtures are budgeted separately.",
        },
        "profiles": profiles,
        "bom_basis": [
            {
                "id": "BOM-C-P1",
                "label": "P1 Open-Commercial Bimanual Rig (YAM Ultra 2 + ORCA v2.1 Base)",
                "arms_usd": 8798,
                "hands_usd": 7000,
                "peripherals_est_usd": 10688,
                "total_est_usd": 26486,
                "divisions": ["blind-stereo-nontactile"],
                "open_rfqs": "I2RT YAM Ultra 2 full-reach payload, repeatability, flange; ORCA v2.1 hand mass.",
            },
            {
                "id": "BOM-C-P2",
                "label": "P2 Precision-Tactile Dual-Division Rig (UFACTORY 850 + ORCA v2.1 Touch)",
                "arms_usd": 17998,
                "hands_usd": 12200,
                "peripherals_est_usd": 10688,
                "total_est_usd": 40886,
                "divisions": ["blind-stereo-tactile", "blind-stereo-nontactile (via mask_tactile=True)"],
                "open_rfqs": "ORCA v2.1 Touch SDK licence, thermal duty, ISO 9409-1-50-4-M6 adapter; UFACTORY 850 dual sync rate.",
            },
        ],
        "camera_options": [
            {"model": "Stereolabs ZED 2i (2 mm IP66)", "price_usd": 529, "delta_vs_baseline_usd": -1478},
            {"model": "Luxonis OAK-D Long Range PoE", "price_usd": 809, "delta_vs_baseline_usd": -1198},
        ],
        "excluded_candidates": [
            {"candidate": "Aero Hand Open", "reason": "Tetheria sales discontinued; CC BY-NC-SA 4.0 non-commercial licence; 7 actuated DoF, lacks tactile array."},
            {"candidate": "Wuji Hand 2.2 (Beta)", "reason": "$29,200 pair; Beta manual warns against continuous high-load operation (~40 min thermal envelope)."},
            {"candidate": "Allegro Hand V5 Sense", "reason": "$28,600 pair (total BOM B ~$59,786); 4 fingers miss 5-finger human opposable thumb baseline."},
        ],
        "families": [
            {"family_id": fam, "name": _FAMILY_META[fam][0], "predicates": _FAMILY_META[fam][1]}
            for fam in ALL_FAMILIES
        ],
    }
    write_json(SITE_DATA / "rig_frontier.json", doc)


def main() -> int:
    v1_root = REPO / "sandbox" / "logs" / "eutropos-v100-live"
    if not (v1_root / "evidence_open").is_dir():
        raise SystemExit(f"Missing live proof directory: {v1_root}. Run `eutropos-referee prove-v1 --live-crypto` first.")
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    _export_bundle(
        v1_root / "evidence_open",
        v1_root / "trusted-v1-open.pem",
        SITE_DATA / "bundles" / "open_live",
        hazard=False,
    )
    _export_bundle(
        v1_root / "evidence_hazard",
        v1_root / "trusted-v1-hazard.pem",
        SITE_DATA / "bundles" / "hazard_live",
        hazard=True,
    )
    _export_a4_study_and_showcase()
    _export_rig_frontier()
    print(f"SITE_DATA_EXPORTED -> {SITE_DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
