"""Protocol v1.0 cryptographic registration, slot ledger, TSA anchoring, and verification."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .a4_harness import wilson_ci
from .beacon import (
    DRAND_QUICKNET_CHAIN_HASH,
    DRAND_QUICKNET_GENESIS_TIME,
    DRAND_QUICKNET_PERIOD_S,
    DRAND_QUICKNET_PUBKEY_HEX,
    PINNED_TSA_ROOT_SHA256S,
    BeaconReading,
    RFC3161Client,
    StubBeacon,
    StubTimestampAuthority,
    TimestampAuthority,
    drand_quicknet_round_time_utc,
    fetch_freetsa_cacert,
    fetch_future_quicknet_round,
    fetch_latest_quicknet_round,
    verify_drand_round,
    verify_rfc3161_tst,
    verify_stub_beacon,
)
from .certificate import (
    CERTIFICATE_VERSION_V1,
    generate_or_load_private_key,
    key_id,
    load_public_key,
    public_key_bytes,
    sign_certificate,
    verify_certificate,
    write_public_key,
)
from .disclosure import (
    DISCLOSURE_GENERAL,
    DISCLOSURE_HAZARD,
    DISCLOSURE_MODES,
    prepare_disclosure_bundle,
    verify_disclosure_bundle,
)
from .generator import ALL_FAMILIES, derive_canonical_task
from .instruments import (
    encode_si_frame,
    evaluate_overhead_stream,
    evaluate_scale_stream,
    parse_si_frame,
    read_instrument_files,
)
from .manifest import (
    bundle_path,
    canonical_json,
    file_entries,
    inventory,
    object_hash,
    read_json,
    read_jsonl,
    relative_path,
    sha256_bytes,
    sha256_file,
    validate_relative_path,
    write_json,
)
from .profiles import get_profile
from .runner import prepare_empty_directory
from .seed import (
    SealedSeedV1,
    commit_v1,
    decode_hex,
    derive_eval_seed_v1,
    derive_instance_seed_v1,
    derive_run_seed_v1,
    generate_secret,
    utc_now,
)

SLOT_STATUSES = frozenset({"completed", "start_failure", "aborted", "hardware_fault", "retry"})
TERMINAL_SLOT_STATUSES = frozenset({"completed", "start_failure", "aborted", "hardware_fault"})
NON_RETRYABLE_STATUSES = frozenset({"completed", "aborted"})
MAX_RETRIES_PER_SLOT = 2


def enrich_canonical_target(hid: dict[str, Any]) -> dict[str, Any]:
    return {
        **hid,
        "target_net_g": float(hid.get("target_net_g", hid.get("catch_mass_target_g", 37.2))),
        "tolerance_g": float(hid.get("tolerance_g", 0.8)),
        "tare_g": 0.0,
        "coordinate_frame": "bench-mm",
        "pan_bounds_mm": [-64.0, -64.0, 64.0, 64.0],
        "expected_objects": [{"id": "token-0", "color": "copper", "kind": "bead"}],
        "settle_window_s": 2.0,
        "max_step_delta_g": 0.03,
        "max_bezel_drift_mm": 0.5,
    }


def _validate_planned_slots(
    planned_slots: list[dict[str, Any]],
    *,
    task_spec: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(planned_slots, list) or not planned_slots:
        raise ValueError("planned_slots must be a non-empty list")
    by_slot: dict[str, dict[str, Any]] = {}
    seen_logical: set[str] = set()
    seen_indices: set[int] = set()
    families_seq: list[str] = []
    for idx, s in enumerate(planned_slots):
        if not isinstance(s, dict):
            raise ValueError("each planned slot must be an object")
        sid = s.get("slot_id")
        lid = s.get("logical_instance_id")
        sidx = s.get("slot_index")
        fam = s.get("family_id")
        if not isinstance(sid, str) or not sid or sid in by_slot:
            raise ValueError(f"invalid or duplicate planned slot_id: {sid!r}")
        if not isinstance(lid, str) or not lid or lid in seen_logical:
            raise ValueError(f"invalid or duplicate logical_instance_id: {lid!r}")
        if type(sidx) is not int or sidx != idx or sidx in seen_indices:
            raise ValueError(f"invalid or non-contiguous slot_index: {sidx!r}")
        if fam not in ALL_FAMILIES:
            raise ValueError(f"unregistered family_id in planned_slots: {fam!r}")
        by_slot[sid] = s
        seen_logical.add(lid)
        seen_indices.add(sidx)
        families_seq.append(fam)
    if task_spec is not None:
        if task_spec.get("planned_slot_count") != len(planned_slots):
            raise ValueError("planned_slots count disagrees with task_spec.json")
        if list(task_spec.get("families") or []) != families_seq:
            raise ValueError("planned_slots families sequence disagrees with task_spec.json")
    return by_slot

V1_FIXED_VECTOR = {
    "secret_hex": "00" * 32,
    "nonce_hex": "11" * 16,
    "submitter_hex": "7375626d69747465722d7631",
    "beacon_hex": "22" * 32,
    "family_id": "E1",
    "trial_index": 0,
}


def compute_v1_seed_vector(
    secret: bytes, nonce: bytes, submitter: bytes, beacon: bytes, family_id: str, trial_index: int,
) -> dict[str, Any]:
    c = commit_v1(secret, nonce)
    r = derive_run_seed_v1(secret, submitter, beacon)
    e = derive_eval_seed_v1(r)
    inst = derive_instance_seed_v1(r, family_id, trial_index)
    return {
        "commitment_C": c,
        "derived_R_hex": r.hex(),
        "eval_seed": e,
        "instance_seed_hex": inst.hex(),
    }


def _decode_tsa_b64(token: str) -> bytes:
    return base64.b64decode(token, validate=True)


def _save_tsa_artifact(
    root: Path,
    relpath: str,
    digest: bytes,
    authority: TimestampAuthority,
) -> dict[str, Any]:
    att = authority.submit_digest_sha256(digest)
    out = bundle_path(root, relpath)
    out.parent.mkdir(parents=True, exist_ok=True)
    if att.response_b64:
        raw = _decode_tsa_b64(att.response_b64)
        out.write_bytes(raw)
        rec: dict[str, Any] = {
            "path": relpath,
            "provider": att.provider,
            "digest_sha256": digest.hex(),
            "tsr_sha256": sha256_file(out),
            "externally_verified": bool(att.externally_verified),
            "gen_time_utc": att.gen_time_utc,
        }
        if att.nonce is not None:
            rec["nonce"] = int(att.nonce)
        return rec
    write_json(out, att.to_dict())
    return {
        "path": relpath,
        "provider": att.provider,
        "digest_sha256": digest.hex(),
        "tsr_sha256": sha256_file(out),
        "externally_verified": False,
        "gen_time_utc": att.submitted_at,
    }


def _validate_ledger_entries(
    planned_slots: list[dict[str, Any]],
    ledger_entries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_slot_spec = _validate_planned_slots(planned_slots)
    by_slot: dict[str, list[dict[str, Any]]] = {sid: [] for sid in by_slot_spec}
    seen_attempts: dict[str, dict[str, Any]] = {}
    for idx, ev in enumerate(ledger_entries):
        if ev.get("seq") != idx:
            raise ValueError(f"slot ledger seq gap at index {idx}")
        sid = ev.get("slot_id")
        if sid not in by_slot_spec:
            raise ValueError(f"unregistered slot_id in ledger: {sid}")
        if ev.get("logical_instance_id") != by_slot_spec[sid]["logical_instance_id"]:
            raise ValueError(f"logical_instance_id mismatch in ledger for slot {sid}")
        status = ev.get("status")
        if status not in SLOT_STATUSES:
            raise ValueError(f"unsupported slot ledger status: {status!r}")
        aid = ev.get("execution_attempt_id")
        if not isinstance(aid, str) or not aid or aid in seen_attempts:
            raise ValueError(f"invalid or duplicate execution_attempt_id: {aid!r}")
        slot_evs = by_slot[sid]
        retry_id = ev.get("retry_of_attempt_id")
        if not slot_evs:
            if retry_id is not None:
                raise ValueError(f"initial attempt {aid} for slot {sid} cannot set retry_of_attempt_id")
        else:
            prev = slot_evs[-1]
            if prev["status"] in NON_RETRYABLE_STATUSES:
                raise ValueError(f"post-terminal attempt {aid} forbidden after {prev['status']} on slot {sid}")
            if retry_id != prev["execution_attempt_id"]:
                raise ValueError(
                    f"attempt {aid} for slot {sid} must chain retry_of_attempt_id={prev['execution_attempt_id']!r}"
                )
            if len(slot_evs) > MAX_RETRIES_PER_SLOT:
                raise ValueError(f"slot {sid} exceeds MAX_RETRIES_PER_SLOT={MAX_RETRIES_PER_SLOT}")
        if status == "completed":
            mp = ev.get("manifest_path")
            if not isinstance(mp, str) or not mp:
                raise ValueError(f"completed attempt {aid} requires manifest_path")
            validate_relative_path(mp)
            if type(ev.get("trial_passed")) is not bool:
                raise ValueError(f"completed attempt {aid} requires boolean trial_passed")
            if not isinstance(ev.get("scores"), dict):
                raise ValueError(f"completed attempt {aid} requires scores dict")
        elif ev.get("manifest_path") is not None:
            raise ValueError(f"non-completed attempt {aid} cannot reference manifest_path")
        seen_attempts[aid] = ev
        slot_evs.append(ev)
    return by_slot


class SlotLedger:
    """Append-only JSONL ledger capturing every registered slot execution and retry."""

    def __init__(self, path: Path, planned_slots: list[dict[str, Any]]) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.planned_slots = planned_slots
        self.by_slot = _validate_planned_slots(planned_slots)
        self.entries: list[dict[str, Any]] = []
        self._attempts: dict[str, dict[str, Any]] = {}
        self._by_slot_history: dict[str, list[dict[str, Any]]] = {sid: [] for sid in self.by_slot}
        if self.path.exists() and self.path.stat().st_size > 0:
            existing = read_jsonl(self.path)
            self._by_slot_history = _validate_ledger_entries(planned_slots, existing)
            self.entries = list(existing)
            self._attempts = {e["execution_attempt_id"]: e for e in existing}

    def record(
        self,
        *,
        slot_id: str,
        logical_instance_id: str,
        execution_attempt_id: str,
        status: str,
        retry_of_attempt_id: str | None = None,
        manifest_path: str | None = None,
        trial_passed: bool | None = None,
        scores: dict[str, float] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        entry = {
            "seq": len(self.entries),
            "slot_id": slot_id,
            "logical_instance_id": logical_instance_id,
            "execution_attempt_id": execution_attempt_id,
            "status": status,
            "retry_of_attempt_id": retry_of_attempt_id,
            "manifest_path": manifest_path,
            "trial_passed": trial_passed,
            "scores": dict(scores or {}),
            "reason": reason,
            "timestamp_utc": utc_now(),
        }
        candidate = [*self.entries, entry]
        updated_history = _validate_ledger_entries(self.planned_slots, candidate)
        self.entries.append(entry)
        self._attempts[execution_attempt_id] = entry
        self._by_slot_history = updated_history
        line = canonical_json(entry) + b"\n"
        with open(self.path, "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return entry


def summarize_slots(
    planned_slots: list[dict[str, Any]], ledger_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize outcomes using all pre-registered slots in denominator (no abort hiding)."""
    by_slot = _validate_ledger_entries(planned_slots, ledger_entries)
    registered = len(planned_slots)

    completed = 0
    terminal_start_failures = 0
    start_failure_events = 0
    aborted = 0
    hardware_faults = 0
    retries = 0
    passed = 0
    failed = 0
    all_accounted = True

    for s in planned_slots:
        evs = by_slot[s["slot_id"]]
        if not evs:
            all_accounted = False
            failed += 1
            continue
        retries += sum(1 for e in evs if e.get("retry_of_attempt_id") is not None)
        start_failure_events += sum(1 for e in evs if e.get("status") == "start_failure")
        last = evs[-1]
        st = last["status"]
        if st == "completed":
            completed += 1
            if last.get("trial_passed") is True:
                passed += 1
            else:
                failed += 1
        elif st == "start_failure":
            terminal_start_failures += 1
            failed += 1
        elif st == "aborted":
            aborted += 1
            failed += 1
        elif st == "hardware_fault":
            hardware_faults += 1
            failed += 1
        else:
            all_accounted = False
            failed += 1

    ci = wilson_ci(passed, registered) if registered else None
    return {
        "registered_slots": registered,
        "completed_slots": completed,
        "passed_slots": passed,
        "failed_slots": failed,
        "start_failure_events": start_failure_events,
        "terminal_start_failures": terminal_start_failures,
        "aborted_slots": aborted,
        "hardware_faults": hardware_faults,
        "retries": retries,
        "all_slots_accounted": all_accounted,
        "effective_pass_rate": round(passed / registered, 6) if registered else 0.0,
        "effective_pass_ci95": list(ci) if ci is not None else None,
    }


def _aggregate_family_results(
    planned_slots: list[dict[str, Any]], ledger_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    by_slot = _validate_ledger_entries(planned_slots, ledger_entries)
    per_family: dict[str, dict[str, Any]] = {}
    for slot in planned_slots:
        fam = slot["family_id"]
        rec = per_family.setdefault(fam, {"registered": 0, "passed": 0, "completed": 0})
        rec["registered"] += 1
        evs = by_slot[slot["slot_id"]]
        ev = evs[-1] if evs else None
        if ev and ev["status"] == "completed":
            rec["completed"] += 1
            if ev.get("trial_passed") is True:
                rec["passed"] += 1
    out_fam: dict[str, Any] = {}
    total_reg = sum(v["registered"] for v in per_family.values())
    total_pass = sum(v["passed"] for v in per_family.values())
    for fam, counts in sorted(per_family.items()):
        ci = wilson_ci(counts["passed"], counts["registered"])
        out_fam[fam] = {
            **counts,
            "pass_rate": round(counts["passed"] / counts["registered"], 6),
            "ci95": list(ci) if ci is not None else None,
        }
    overall_ci = wilson_ci(total_pass, total_reg) if total_reg else None
    return {
        "overall": {
            "registered": total_reg,
            "passed": total_pass,
            "pass_rate": round(total_pass / total_reg, 6) if total_reg else 0.0,
            "ci95": list(overall_ci) if overall_ci is not None else None,
        },
        "per_family": out_fam,
        "per_scene": {},
        "diagnostics": {"ledger_events": len(ledger_entries)},
    }


def _write_clean_scale_and_overhead(
    root: Path,
    stamp: str,
    base: str,
    target_g: float,
    pan_bounds: list[float],
    drift_mm: float = 0.08,
    passed: bool = True,
) -> tuple[Path, Path]:
    inst_dir = root / "instruments" / stamp
    inst_dir.mkdir(parents=True, exist_ok=True)
    scale_path = inst_dir / f"{base}_scale.txt"
    cam_path = inst_dir / f"{base}_overhead.json"
    raw_frames: list[bytes] = []
    scale_samples: list[dict[str, Any]] = []
    cam_frames: list[dict[str, Any]] = []
    actual_g = target_g if passed else round(target_g + 15.0, 2)
    cx = (pan_bounds[0] + pan_bounds[2]) / 2.0
    cy = (pan_bounds[1] + pan_bounds[3]) / 2.0
    for k in range(30):
        t_s = k / 10.0
        val = actual_g if k >= 8 else round(actual_g * 0.25, 2)
        raw_frames.append(encode_si_frame(val, stability=" "))
        scale_samples.append({"index": k, "t_s": t_s})
        obj_x = cx if passed else pan_bounds[2] + 15.0
        cam_frames.append({
            "t_s": t_s,
            "coordinate_frame": "bench-mm",
            "bezel_fiducial_drift_mm": drift_mm,
            "hands_in_home_zone": k >= 8,
            "scale_pan_contact_n": 0.0,
            "objects": [{
                "id": "token-0",
                "color": "copper",
                "kind": "bead",
                "intact": True,
                "bounds_mm": [obj_x - 6.0, cy - 6.0, obj_x + 6.0, cy + 6.0],
            }],
        })
    raw_bytes = b"".join(raw_frames)
    scale_path.write_bytes(raw_bytes)
    write_json(cam_path, {
        "schema": "eutropos-instruments-v0",
        "clock": "episode-simulated-seconds",
        "capture_start_s": 0.0,
        "capture_end_s": 2.9,
        "scale_sha256": sha256_bytes(raw_bytes),
        "scale_samples": scale_samples,
        "frames": cam_frames,
    })
    return scale_path, cam_path


def run_v1_session_bundle(
    out_dir: str | Path,
    *,
    pareto_profile: str = "P0",
    mask_tactile: bool = False,
    disclosure_mode: str = DISCLOSURE_GENERAL,
    families: tuple[str, ...] = ("E1", "E3", "H4"),
    inject_start_failure_and_retry: bool = True,
    abort_slot_indices: tuple[int, ...] = (),
    forced_outcomes: dict[str, bool] | None = None,
    live_crypto: bool = False,
    beacon_reading: BeaconReading | StubBeacon | None = None,
    tsa_authority: TimestampAuthority | None = None,
    trusted_tsa_pem: str | Path | bytes | None = None,
    private_key: Any = None,
    write_trusted_public_key: Path | None = None,
    submitter: str = "v1-submitter",
    escrow_dir: Path | None = None,
    human_adjudication: bool = True,
    extra_slot_files: dict[str, dict[str, bytes]] | None = None,
    extra_deviations: list[str] | None = None,
) -> Path:
    """Create and execute a complete v1.0 evidence bundle with live or stub external crypto."""
    profile = get_profile(pareto_profile)
    if disclosure_mode not in DISCLOSURE_MODES:
        raise ValueError(f"unsupported disclosure mode: {disclosure_mode!r}")
    root = prepare_empty_directory(Path(out_dir))
    key = generate_or_load_private_key(private_key)
    if write_trusted_public_key is not None:
        trusted = Path(write_trusted_public_key).absolute()
        if trusted.resolve() == root.resolve() or root.resolve() in trusted.resolve().parents:
            raise ValueError("trusted public key output must live outside evidence")
        write_public_key(trusted, key.public_key())

    cacert_bytes: bytes | None = None
    if trusted_tsa_pem is not None:
        cacert_bytes = (
            trusted_tsa_pem.read_bytes()
            if isinstance(trusted_tsa_pem, Path)
            else (
                trusted_tsa_pem.encode("utf-8")
                if isinstance(trusted_tsa_pem, str) and "BEGIN CERTIFICATE" in trusted_tsa_pem
                else (Path(trusted_tsa_pem).read_bytes() if isinstance(trusted_tsa_pem, str) else trusted_tsa_pem)
            )
        )
    if live_crypto and cacert_bytes is None:
        cacert_bytes = fetch_freetsa_cacert()

    if tsa_authority is not None:
        tsa = tsa_authority
    elif live_crypto:
        tsa = RFC3161Client("https://freetsa.org/tsr", trusted_cert_pem=cacert_bytes)
    else:
        tsa = StubTimestampAuthority()

    if cacert_bytes is not None:
        chain_out = root / "tsa" / "tsa_chain.pem"
        chain_out.parent.mkdir(parents=True, exist_ok=True)
        chain_out.write_bytes(cacert_bytes)

    secret, nonce = generate_secret()
    commitment_c = commit_v1(secret, nonce)
    submitter_bytes = submitter.encode("utf-8")
    submitter_n_hex = submitter_bytes.hex()

    planned_slots = [
        {
            "slot_index": idx,
            "slot_id": f"slot-{idx:02d}",
            "logical_instance_id": f"inst-{fam}-{idx:02d}",
            "family_id": fam,
            "scene_id": f"{fam}-scene-{idx}",
            "epoch": 0,
            "init_seed": 1000 + idx,
        }
        for idx, fam in enumerate(families)
    ]

    task_spec = {
        "schema": "eutropos-task-spec-v1.0",
        "pareto_profile": pareto_profile,
        "mask_tactile": bool(mask_tactile),
        "families": list(families),
        "planned_slot_count": len(planned_slots),
    }
    body_cfg = {
        "pareto_profile": pareto_profile,
        "title": profile.title,
        "total_dof": profile.total_dof,
        "has_tactile_hardware": profile.has_tactile,
        "mask_tactile": bool(mask_tactile),
        "effective_reach_mm": profile.effective_reach_mm,
    }
    write_json(root / "task_spec.json", task_spec)
    write_json(root / "body_configuration.json", body_cfg)

    prereg_files = file_entries(root, [root / "task_spec.json", root / "body_configuration.json"])
    if beacon_reading is not None:
        reading: BeaconReading | StubBeacon | None = beacon_reading
        target_round = beacon_reading.round_number
        use_quicknet_meta = isinstance(beacon_reading, BeaconReading)
    elif live_crypto:
        latest = fetch_latest_quicknet_round()
        # Reserve a future quicknet round (+3 periods ~= 9s) BEFORE writing and timestamping preregistration.
        target_round = latest.round_number + 3
        reading = None
        use_quicknet_meta = True
    else:
        reading = StubBeacon.lookup(42)
        target_round = reading.round_number
        use_quicknet_meta = False

    beacon_meta = (
        {
            "network": "drand-quicknet",
            "chain_hash": DRAND_QUICKNET_CHAIN_HASH,
            "public_key_hex": DRAND_QUICKNET_PUBKEY_HEX,
            "scheme": "drand-quicknet",
            "target_round": target_round,
        }
        if use_quicknet_meta
        else {
            "network": "stub-sha256-v0",
            "chain_hash": "00" * 32,
            "public_key_hex": "",
            "scheme": "stub-sha256-v0",
            "target_round": target_round,
        }
    )

    pre_beacon_reg = {
        "protocol_version": "eutropos-referee-v1.0",
        "bundle_profile": "instruments-v1",
        "pareto_profile": pareto_profile,
        "mask_tactile": bool(mask_tactile),
        "disclosure_mode": disclosure_mode,
        "created_utc": utc_now(),
        "subject": {
            "name": "v1-compliant-bench",
            "snapshot": f"eutropos-referee=={__version__}",
            "division": "blind-stereo-nontactile" if (mask_tactile or not profile.has_tactile) else "blind-stereo-tactile",
            "sampling_settings": "deterministic v1 proof run",
        },
        "hashes": {
            "task_spec": sha256_file(root / "task_spec.json"),
            "body_configuration": sha256_file(root / "body_configuration.json"),
            "referee_package_version": __version__,
        },
        "commitment_C": commitment_c,
        "submitter_N_hex": submitter_n_hex,
        "beacon_config": beacon_meta,
        "registration_deadline_utc": utc_now(),
        "planned_slots": planned_slots,
        "deviations_and_incidents": [
            "Live quicknet/FreeTSA crypto anchored." if live_crypto else "Local stub beacon/clock used for offline unit check.",
            "Simulated bench instruments exercise v1 protocol ledger and disclosure.",
            *(extra_deviations or ()),
        ],
        "operator_and_witness": {"operator_id": "v1-operator", "witness_id": "v1-witness", "witness_signed": False},
        "conflict_of_interest_statement": "Automated v1 verification suite bundle.",
        "files": prereg_files,
    }
    pre_path = root / "pre_beacon_registration.json"
    write_json(pre_path, pre_beacon_reg)
    pre_sha = sha256_file(pre_path)

    commitment_tsa = _save_tsa_artifact(root, "tsa/commitment.tsr", bytes.fromhex(pre_sha), tsa)
    if reading is None:
        reading = fetch_future_quicknet_round(target_round)

    # Phase B: Post-beacon reveal & private instance commitments
    sealed = SealedSeedV1(secret, nonce, submitter_bytes, reading)
    assignments: dict[str, str] = {}
    targets_list: list[dict[str, Any]] = []
    slot_specs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for slot in planned_slots:
        inst_seed = derive_instance_seed_v1(sealed.run_seed, slot["family_id"], slot["slot_index"])
        pub, hid = derive_canonical_task(inst_seed, slot["family_id"], slot["slot_index"])
        hid_enriched = enrich_canonical_target(hid)
        assignments[slot["slot_id"]] = object_hash(hid_enriched)
        targets_list.append({
            "slot_id": slot["slot_id"],
            "logical_instance_id": slot["logical_instance_id"],
            "spec": hid_enriched,
        })
        slot_specs[slot["slot_id"]] = (pub, hid_enriched)

    post_beacon = {
        "protocol_version": "eutropos-referee-v1.0",
        "pre_beacon_registration_sha256": pre_sha,
        "submitter_N_hex": sealed.submitter.hex(),
        "beacon": reading.to_dict(),
        "assignment_commitments": assignments,
    }
    post_path = root / "post_beacon_inputs.json"
    write_json(post_path, post_beacon)
    post_sha = sha256_file(post_path)
    post_beacon_tsa = _save_tsa_artifact(root, "tsa/post_beacon.tsr", bytes.fromhex(post_sha), tsa)

    # Phase C: Slot execution + selective-abort/retry ledger + trial manifest chain
    stamp = "20261119_v1_run"
    ledger = SlotLedger(root / "manifests" / "slot_ledger.jsonl", planned_slots)
    trials: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    checkpoint_tsa: list[dict[str, Any]] = []
    previous_hash = pre_sha
    manifest_idx = 0

    for idx, slot in enumerate(planned_slots):
        sid = slot["slot_id"]
        lid = slot["logical_instance_id"]
        pub, hid = slot_specs[sid]
        if idx in abort_slot_indices:
            ledger.record(
                slot_id=sid,
                logical_instance_id=lid,
                execution_attempt_id=f"{sid}-attempt-0",
                status="aborted",
                manifest_path=None,
                trial_passed=False,
                reason="operator aborted trial without retry",
            )
            continue
        if inject_start_failure_and_retry and idx == 0:
            fail_id = f"{sid}-attempt-0"
            ledger.record(
                slot_id=sid,
                logical_instance_id=lid,
                execution_attempt_id=fail_id,
                status="start_failure",
                manifest_path=None,
                trial_passed=False,
                reason="simulated gripper home check fault prior to trial start",
            )
            att_id = f"{sid}-attempt-1"
            retry_of = fail_id
        else:
            att_id = f"{sid}-attempt-0"
            retry_of = None

        base = f"{sid}-{att_id}"
        outcome = True if not forced_outcomes else bool(forced_outcomes.get(sid, True))
        scale_p, cam_p = _write_clean_scale_and_overhead(
            root, stamp, base, hid["target_net_g"], hid["pan_bounds_mm"], passed=outcome,
        )
        rec_path = root / "records" / stamp / base / "record.json"
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(rec_path, {
            "record_id": base,
            "slot_id": sid,
            "logical_instance_id": lid,
            "execution_attempt_id": att_id,
            "instruction": pub["instruction"],
            "steps": 29,
            "mask_tactile": bool(mask_tactile),
            "status": "success",
        })
        scale_r, cam_r = read_instrument_files(scale_p, cam_p, expected_end_s=2.9)
        m_res = evaluate_scale_stream(
            scale_r, target_net_g=hid["target_net_g"], tolerance_g=hid["tolerance_g"],
            tare_g=hid["tare_g"], settle_window_s=hid["settle_window_s"],
            max_step_delta_g=hid["max_step_delta_g"],
        )
        g_res = evaluate_overhead_stream(
            cam_r, target_spec=hid, settle_window_s=hid["settle_window_s"],
            max_bezel_drift_mm=hid["max_bezel_drift_mm"],
        )
        scores = {"eutropos-mass": float(m_res.passed), "eutropos-geometry": float(g_res.passed)}
        trial_passed = m_res.passed and g_res.passed
        t_paths = [scale_p, cam_p, rec_path]
        slot_artifacts = (extra_slot_files or {}).get(sid, {})
        for art_name, art_bytes in sorted(slot_artifacts.items()):
            clean_name = validate_relative_path(art_name)
            art_dest = bundle_path(root, f"artifacts/{stamp}/{base}/{clean_name}")
            art_dest.parent.mkdir(parents=True, exist_ok=True)
            art_dest.write_bytes(art_bytes)
            t_paths.append(art_dest)
        m_rel = f"manifests/trial_{manifest_idx:04d}.json"
        manifest = {
            "manifest_version": "eutropos-trial-manifest-v1.0",
            "trial_index": manifest_idx,
            **slot,
            "execution_attempt_id": att_id,
            "prev_manifest_hash": previous_hash,
            "scale_path": relative_path(root, scale_p),
            "overhead_path": relative_path(root, cam_p),
            "record_path": relative_path(root, rec_path),
            "scores": scores,
            "trial_passed": trial_passed,
            "files": file_entries(root, t_paths),
        }
        m_path = root / m_rel
        write_json(m_path, manifest)
        previous_hash = sha256_file(m_path)
        trials.append(manifest)
        ledger.record(
            slot_id=sid,
            logical_instance_id=lid,
            execution_attempt_id=att_id,
            status="completed",
            retry_of_attempt_id=retry_of,
            manifest_path=m_rel,
            trial_passed=trial_passed,
            scores=scores,
            reason="instrument pass",
        )
        if idx == 0 and human_adjudication:
            # Adjudication example preserves original raw instrument scores unmodified
            adjudications.append({
                "slot_id": sid,
                "execution_attempt_id": att_id,
                "original_scores": dict(scores),
                "adjudicated_scores": dict(scores),
                "reason": "routine post-eval review confirmed instrument pass",
                "adjudicator_id": "witness-panel-v1",
            })
        if idx == 1:
            chk_rec = _save_tsa_artifact(
                root,
                f"tsa/checkpoint_{manifest_idx:04d}.tsr",
                bytes.fromhex(previous_hash),
                tsa,
            )
            chk_rec["manifest_index"] = manifest_idx
            chk_rec["manifest_path"] = m_rel
            checkpoint_tsa.append(chk_rec)
        manifest_idx += 1

    # Phase D: targets, disclosure split (general-open vs hazard-escrowed), seed reveal, close
    targets_path = root / "referee_targets.json"
    write_json(targets_path, {
        "schema": "eutropos-targets-v1.0",
        "trials": targets_list,
    })
    reveal_path = root / "seed_reveal.json"
    write_json(reveal_path, sealed.reveal())
    seed_reveal_sha256 = sha256_file(reveal_path)

    private_rels = ["referee_targets.json"]
    if disclosure_mode == DISCLOSURE_HAZARD:
        raw_vid = root / "closed_video" / "sample_trace.bin"
        raw_vid.parent.mkdir(parents=True, exist_ok=True)
        raw_vid.write_bytes(b"BENIGN_SURROGATE_VIDEO_PLACEHOLDER_V1")
        private_rels.extend(["seed_reveal.json", "closed_video/sample_trace.bin"])

    disc_path, esc_rec_path, _ = prepare_disclosure_bundle(
        root,
        mode=disclosure_mode,
        private_relpaths=private_rels,
        escrow_dir=escrow_dir,
        benign_surrogate_declared=True,
    )

    close_files = [
        root / "manifests" / "slot_ledger.jsonl",
        disc_path,
    ]
    if esc_rec_path is not None:
        close_files.append(esc_rec_path)
        public_seed_block: dict[str, Any] = {
            "seed_reveal_escrowed": True,
            "commitment_C": sealed.commitment,
            "submitter_N_hex": sealed.submitter.hex(),
            "beacon": reading.to_dict(),
            "seed_reveal_sha256": seed_reveal_sha256,
        }
    else:
        close_files.extend([reveal_path, targets_path])
        public_seed_block = sealed.reveal()

    close_doc = {
        "manifest_version": "eutropos-session-close-v1.0",
        "bundle_profile": "instruments-v1",
        "pre_beacon_registration_sha256": pre_sha,
        "post_beacon_inputs_sha256": post_sha,
        "prev_manifest_hash": previous_hash,
        "slot_ledger_sha256": sha256_file(root / "manifests" / "slot_ledger.jsonl"),
        "disclosure_receipt_sha256": sha256_file(disc_path),
        "escrow_receipt_sha256": sha256_file(esc_rec_path) if esc_rec_path else None,
        "trial_manifest_count": len(trials),
        "created_utc": utc_now(),
        "files": file_entries(root, close_files),
    }
    close_path = root / "manifests" / "session_close.json"
    write_json(close_path, close_doc)
    chain_root_hash = sha256_file(close_path)

    # Phase E: Non-circular session_close RFC 3161 TSA over chain_root_hash -> sign DSSE cert
    close_tsa = _save_tsa_artifact(
        root, "tsa/session_close.tsr", bytes.fromhex(chain_root_hash), tsa
    )
    ledger_entries = read_jsonl(root / "manifests" / "slot_ledger.jsonl")
    slot_summary = summarize_slots(planned_slots, ledger_entries)
    results = _aggregate_family_results(planned_slots, ledger_entries)

    cert_payload = {
        "certificate_version": CERTIFICATE_VERSION_V1,
        "subject": pre_beacon_reg["subject"],
        "pareto_profile": pareto_profile,
        "mask_tactile": bool(mask_tactile),
        "disclosure_mode": disclosure_mode,
        "hashes": pre_beacon_reg["hashes"],
        "pre_beacon_registration_sha256": pre_sha,
        "seed": public_seed_block,
        "evidence": {
            "bundle_profile": "instruments-v1",
            "genesis_hash": pre_sha,
            "chain_root_hash": chain_root_hash,
            "slot_ledger_sha256": close_doc["slot_ledger_sha256"],
            "escrow_receipt_sha256": close_doc["escrow_receipt_sha256"],
            "tsa_receipts": {
                "commitment": commitment_tsa,
                "post_beacon": post_beacon_tsa,
                "checkpoints": checkpoint_tsa,
                "session_close": close_tsa,
            },
            "trial_count": len(trials),
            "created_utc": close_doc["created_utc"],
        },
        "slot_summary": slot_summary,
        "results": results,
        "adjudications": adjudications,
        "reference_baselines": {
            "human_reference": {"status": "pending-physical-rig", "pass_rate": None},
            "scripted_floor": {"status": "stub-demo", "pass_rate": 1.0},
        },
        "deviations_and_incidents": pre_beacon_reg["deviations_and_incidents"],
        "operator_and_witness": pre_beacon_reg["operator_and_witness"],
        "conflict_of_interest_statement": pre_beacon_reg["conflict_of_interest_statement"],
    }
    write_public_key(root / "public_key.pem", key.public_key())
    write_json(root / "certificate.json", sign_certificate(cert_payload, key))
    return root


def _parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def verify_v1_bundle(
    evidence_dir: str | Path,
    *,
    certificate: str | Path | None = None,
    public_key: Any = None,
    allow_bundled_key: bool = False,
    trusted_tsa_pem: str | Path | bytes | None = None,
    escrow_dir: str | Path | None = None,
    require_live_beacon: bool = False,
    require_live_tsa: bool = False,
    require_full_rescore: bool = False,
) -> Any:
    """Verify every cryptographic, chronology, slot-ledger, TSA, and disclosure claim of a v1.0 bundle."""
    from .verifier import VerificationReport

    report = VerificationReport()
    root = Path(evidence_dir).absolute()
    cert_path = Path(certificate) if certificate is not None else root / "certificate.json"
    if public_key is None and not allow_bundled_key:
        report.check("trusted_public_key", False, "supply public_key or explicitly allow_bundled_key")
        return report.finish()
    mode = "external-key" if public_key is not None else "self-asserted-bundled-key"
    report.trusted_key_mode = mode
    report.check("trusted_key_mode", True, mode)

    key = report.capture(
        "dsse_signature",
        lambda: load_public_key(public_key if public_key is not None else root / "public_key.pem"),
    )
    if key is None:
        return report.finish()

    def auth() -> dict[str, Any]:
        raw = cert_path.read_bytes()
        env = read_json(cert_path, canonical=True)
        if canonical_json(env) != raw:
            raise ValueError("noncanonical certificate bytes")
        p = verify_certificate(env, key)
        report.check("dsse_signature", True, f"Ed25519 DSSEv1 PAE; keyid={key_id(key)}")
        return p

    payload = report.capture("dsse_signature", auth)
    if payload is None:
        return report.finish()

    if payload.get("disclosure_mode") not in DISCLOSURE_MODES:
        report.check("disclosure_mode", False, f"unsupported disclosure mode: {payload.get('disclosure_mode')!r}")
        return report.finish()
    d_mode = payload["disclosure_mode"]
    esc_path = Path(escrow_dir).absolute() if escrow_dir is not None else None

    def load_core():
        task_spec = read_json(bundle_path(root, "task_spec.json"), canonical=True)
        body_cfg = read_json(bundle_path(root, "body_configuration.json"), canonical=True)
        pre = read_json(bundle_path(root, "pre_beacon_registration.json"), canonical=True)
        post = read_json(bundle_path(root, "post_beacon_inputs.json"), canonical=True)
        close = read_json(bundle_path(root, "manifests/session_close.json"), canonical=True)
        ledger = read_jsonl(bundle_path(root, "manifests/slot_ledger.jsonl"))
        reveal: dict[str, Any] | None = None
        if d_mode == DISCLOSURE_GENERAL:
            reveal = read_json(bundle_path(root, "seed_reveal.json"), canonical=True)
        elif esc_path is not None:
            esc_rev_p = bundle_path(esc_path, "seed_reveal.json")
            if not esc_rev_p.is_file():
                raise ValueError("escrow_dir missing seed_reveal.json")
            reveal = read_json(esc_rev_p, canonical=True)
        return task_spec, body_cfg, pre, post, reveal, close, ledger

    core = report.capture("v1_structure", load_core)
    if core is None:
        return report.finish()
    task_spec, body_cfg, pre, post, reveal, close, ledger = core

    report.check(
        "cert_prereg_consistency",
        payload.get("subject") == pre.get("subject")
        and payload.get("pareto_profile") == pre.get("pareto_profile") == task_spec.get("pareto_profile") == body_cfg.get("pareto_profile")
        and payload.get("mask_tactile") == pre.get("mask_tactile") == task_spec.get("mask_tactile") == body_cfg.get("mask_tactile")
        and payload.get("disclosure_mode") == pre.get("disclosure_mode")
        and payload.get("hashes") == pre.get("hashes")
        and pre.get("hashes", {}).get("task_spec") == sha256_file(root / "task_spec.json")
        and pre.get("hashes", {}).get("body_configuration") == sha256_file(root / "body_configuration.json"),
        "certificate matches preregistration, task_spec, and body_configuration",
    )

    pre_sha = sha256_file(root / "pre_beacon_registration.json")
    post_sha = sha256_file(root / "post_beacon_inputs.json")
    report.check(
        "pre_post_binding",
        pre_sha == payload["pre_beacon_registration_sha256"]
        == post["pre_beacon_registration_sha256"]
        == close["pre_beacon_registration_sha256"]
        and post_sha == close["post_beacon_inputs_sha256"],
        "pre_beacon_registration and post_beacon_inputs bindings",
    )

    # Seed & Beacon check (handles hazard-escrowed redaction cleanly)
    def check_seed_beacon() -> tuple[bytes | None, list[dict[str, Any]]]:
        _validate_planned_slots(pre["planned_slots"], task_spec=task_spec)
        bcfg = pre["beacon_config"]
        bdict = post["beacon"]
        seed_pub = payload["seed"]
        report.check(
            "submitter_commitment",
            bool(pre.get("submitter_N_hex"))
            and pre["submitter_N_hex"] == post["submitter_N_hex"] == seed_pub["submitter_N_hex"],
            "submitter_N_hex pre-committed",
        )
        scheme_ok = (
            bdict.get("scheme") == "drand-quicknet"
            if bcfg["scheme"] == "drand-quicknet"
            else bdict.get("scheme") in {None, "stub-sha256-v0"}
        )
        report.check(
            "post_beacon_match",
            bdict == seed_pub["beacon"] and scheme_ok,
            "post_beacon_inputs match certificate and preregistered scheme",
        )
        if bcfg["scheme"] == "drand-quicknet":
            pinned_ok = (
                bcfg.get("network") == "drand-quicknet"
                and bcfg.get("chain_hash") == DRAND_QUICKNET_CHAIN_HASH
                and bcfg.get("public_key_hex") == DRAND_QUICKNET_PUBKEY_HEX
                and bdict.get("chain_hash") == DRAND_QUICKNET_CHAIN_HASH
            )
            report.check("drand_pinned_network", pinned_ok, "pinned drand-quicknet chain_hash and public_key")
            dres = verify_drand_round(
                bdict["round_number"],
                bdict["value_hex"],
                bdict["signature_hex"],
                public_key_hex=DRAND_QUICKNET_PUBKEY_HEX,
                scheme="drand-quicknet",
            )
            report.check(
                "drand_beacon",
                pinned_ok and dres.valid and bdict["round_number"] == bcfg["target_round"],
                f"drand-quicknet exact round={bdict['round_number']} (target={bcfg['target_round']}): {dres.reason}",
            )
        else:
            report.check(
                "drand_beacon",
                (not require_live_beacon)
                and bdict["round_number"] == bcfg["target_round"]
                and verify_stub_beacon(bdict),
                "stub beacon",
            )

        if d_mode == DISCLOSURE_HAZARD:
            leaked_secret_fields = {"S_hex", "nonce_hex", "derived_R_hex"} & set(seed_pub.keys())
            report.check(
                "hazard_public_seed_redacted",
                not leaked_secret_fields
                and seed_pub.get("seed_reveal_escrowed") is True
                and seed_pub.get("commitment_C") == pre["commitment_C"],
                "hazard certificate omits S_hex/nonce_hex/derived_R_hex",
            )
            if reveal is None:
                if require_full_rescore:
                    report.check("full_rescore_required", False, "escrow_dir required for hazard full rescore")
                return None, pre["planned_slots"]
            esc_sha = sha256_file(bundle_path(esc_path, "seed_reveal.json"))  # type: ignore[arg-type]
            report.check("escrowed_seed_reveal_sha256", esc_sha == seed_pub.get("seed_reveal_sha256"), "seed_reveal.json hash")
        else:
            if reveal is None:
                raise ValueError("general-open bundle missing seed_reveal.json")
            report.check("certificate_seed", reveal == seed_pub, "certificate seed payload")

        sec = decode_hex(reveal["S_hex"], length=32)
        non = decode_hex(reveal["nonce_hex"], length=16)
        sub = decode_hex(reveal["submitter_N_hex"])
        bval = decode_hex(reveal["beacon"]["value_hex"], length=32)
        report.check(
            "commitment_C",
            commit_v1(sec, non) == reveal["commitment_C"] == pre["commitment_C"] == seed_pub["commitment_C"],
            "v1.0 seed commitment",
        )
        report.check(
            "reveal_beacon_match",
            reveal["beacon"] == bdict and reveal["submitter_N_hex"] == pre["submitter_N_hex"],
            "seed_reveal matches post_beacon_inputs",
        )
        rseed = derive_run_seed_v1(sec, sub, bval)
        eseed = derive_eval_seed_v1(rseed)
        report.check("derived_R_v1", rseed.hex() == reveal["derived_R_hex"] and eseed == reveal["eval_seed"], "v1.0 seed derivation")
        return rseed, pre["planned_slots"]

    seed_res = report.capture("seed_beacon", check_seed_beacon)
    if seed_res is None:
        return report.finish()
    run_seed, planned_slots = seed_res

    # Slot ledger + denominator checks
    def check_slots_and_chain() -> list[dict[str, Any]]:
        _validate_ledger_entries(planned_slots, ledger)
        completed_events = [ev for ev in ledger if ev["status"] == "completed"]

        computed_summary = summarize_slots(planned_slots, ledger)
        report.check("slot_ledger_accounted", computed_summary["all_slots_accounted"], "every registered slot terminated")
        report.check("slot_summary", computed_summary == payload["slot_summary"], "exact slot denominator summary")
        report.check("family_results", _aggregate_family_results(planned_slots, ledger) == payload["results"], "recomputed per-family results")

        # Chained trial manifests + exact identity/score binding to completed ledger events
        trials: list[dict[str, Any]] = []
        prev = pre_sha
        for t_idx in range(close["trial_manifest_count"]):
            rel = f"manifests/trial_{t_idx:04d}.json"
            m = read_json(bundle_path(root, rel), canonical=True)
            report.check("prev_manifest_hash", m["prev_manifest_hash"] == prev, rel)
            prev = sha256_file(root / rel)
            trials.append(m)

        sync_ok = len(trials) == len(completed_events)
        if sync_ok:
            for i, (m, ev) in enumerate(zip(trials, completed_events)):
                exp_pass = m["scores"].get("eutropos-mass") == 1.0 and m["scores"].get("eutropos-geometry") == 1.0
                if not (
                    m.get("manifest_version") == "eutropos-trial-manifest-v1.0"
                    and m.get("trial_index") == i
                    and m["slot_id"] == ev["slot_id"]
                    and m["logical_instance_id"] == ev["logical_instance_id"]
                    and m["execution_attempt_id"] == ev["execution_attempt_id"]
                    and ev["manifest_path"] == f"manifests/trial_{i:04d}.json"
                    and m["scores"] == ev["scores"]
                    and type(m.get("trial_passed")) is bool
                    and m["trial_passed"] == ev["trial_passed"] == exp_pass
                ):
                    sync_ok = False
                    break
        report.check(
            "ledger_manifest_sync",
            sync_ok,
            "completed ledger entries and scores match chained trial manifests",
        )
        expected_close_paths = {
            "manifests/slot_ledger.jsonl",
            "disclosure_receipt.json",
            "escrow_receipt.json" if d_mode == DISCLOSURE_HAZARD else "seed_reveal.json",
        }
        if d_mode == DISCLOSURE_GENERAL:
            expected_close_paths.add("referee_targets.json")
        close_file_paths = {validate_relative_path(e["path"]) for e in close.get("files", [])}
        report.check(
            "session_close_chain",
            close["manifest_version"] == "eutropos-session-close-v1.0"
            and close["prev_manifest_hash"] == prev
            and close["slot_ledger_sha256"] == sha256_file(root / "manifests/slot_ledger.jsonl")
            and close_file_paths == expected_close_paths
            and sha256_file(root / "manifests/session_close.json") == payload["evidence"]["chain_root_hash"],
            "v1.0 manifest chain root",
        )
        # Verify adjudications preserve raw manifest scores untouched
        m_by_att = {m["execution_attempt_id"]: m for m in trials}
        for adj in payload["adjudications"]:
            tm = m_by_att.get(adj["execution_attempt_id"])
            report.check(
                "adjudication_original_scores",
                tm is not None and adj["original_scores"] == tm["scores"],
                adj["execution_attempt_id"],
            )
        return trials

    trials = report.capture("slot_chain", check_slots_and_chain) or []

    # File descriptors and complete inventory
    referenced: set[str] = set()
    verified_digests: dict[str, str] = {}
    tsa_paths: set[str] = set()
    tsa_chain = root / "tsa" / "tsa_chain.pem"
    if tsa_chain.is_file():
        tsa_paths.add("tsa/tsa_chain.pem")
    tsa_rec = payload["evidence"]["tsa_receipts"]
    for block in [tsa_rec["commitment"], tsa_rec["post_beacon"], tsa_rec["session_close"], *tsa_rec.get("checkpoints", [])]:
        p = validate_relative_path(block["path"])
        tsa_paths.add(p)

    for owner in [pre, *trials, close]:
        for entry in owner.get("files", []):
            name = validate_relative_path(entry["path"])
            report.check("duplicate_file_reference", name not in referenced, name)
            referenced.add(name)
            fpath = bundle_path(root, name)
            if report.check("file_missing", fpath.is_file(), name):
                size_ok = report.check("file_size", fpath.stat().st_size == entry["size_bytes"], name)
                actual_sha = sha256_file(fpath)
                sha_ok = report.check("file_sha256", actual_sha == entry["sha256"], name)
                if size_ok and sha_ok:
                    verified_digests[name] = actual_sha

    def check_inventory() -> None:
        actual = inventory(root)
        expected = referenced | tsa_paths | {
            "pre_beacon_registration.json",
            "post_beacon_inputs.json",
            "certificate.json",
            "public_key.pem",
            "manifests/session_close.json",
            *(f"manifests/trial_{i:04d}.json" for i in range(close["trial_manifest_count"])),
        }
        for n in sorted(actual - expected):
            report.check("orphan_file", False, n)
        for n in sorted(expected - actual):
            report.check("missing_bundle_file", False, n)
        report.check("complete_inventory", actual == expected, "exact v1 inventory")
        report.check(
            "public_key_copy",
            public_key_bytes(load_public_key(root / "public_key.pem")) == public_key_bytes(key),
            "bundled public key matches trusted key",
        )

    report.capture("inventory", check_inventory)

    # RFC 3161 TSA verification + pinned trust anchor + chronology + pre-beacon quicknet bound
    def check_tsa() -> None:
        pinned_roots: frozenset[str] | None = None
        if trusted_tsa_pem is not None:
            tsa_pem: Any = trusted_tsa_pem
        elif tsa_chain.is_file():
            tsa_pem = tsa_chain
            pinned_roots = PINNED_TSA_ROOT_SHA256S
        else:
            tsa_pem = None
        comm = tsa_rec["commitment"]
        post_blk = tsa_rec["post_beacon"]
        sclose = tsa_rec["session_close"]
        report.check(
            "tsa_commitment_digest",
            comm["digest_sha256"] == pre_sha
            and sha256_file(bundle_path(root, comm["path"])) == comm["tsr_sha256"],
            comm["path"],
        )
        report.check(
            "tsa_post_beacon_digest",
            post_blk["digest_sha256"] == post_sha
            and sha256_file(bundle_path(root, post_blk["path"])) == post_blk["tsr_sha256"],
            post_blk["path"],
        )
        report.check(
            "tsa_session_close_digest",
            sclose["digest_sha256"] == payload["evidence"]["chain_root_hash"]
            and sha256_file(bundle_path(root, sclose["path"])) == sclose["tsr_sha256"],
            sclose["path"],
        )
        checkpoint_labels: list[str] = []
        for i, chk in enumerate(tsa_rec.get("checkpoints", [])):
            midx = chk.get("manifest_index")
            lbl = f"checkpoint_{i}"
            checkpoint_labels.append(lbl)
            valid_chk = (
                type(midx) is int
                and 0 <= midx < len(trials)
                and chk.get("digest_sha256") == sha256_file(bundle_path(root, f"manifests/trial_{midx:04d}.json"))
                and sha256_file(bundle_path(root, chk["path"])) == chk.get("tsr_sha256")
            )
            report.check(f"tsa_{lbl}_digest", valid_chk, chk.get("path", lbl))

        all_blocks = [("commitment", comm), ("post_beacon", post_blk), ("session_close", sclose)] + [
            (f"checkpoint_{i}", c) for i, c in enumerate(tsa_rec.get("checkpoints", []))
        ]
        gen_times: dict[str, datetime] = {}
        providers: dict[str, str] = {}
        for label, blk in all_blocks:
            tfile = bundle_path(root, blk["path"])
            providers[label] = blk["provider"]
            if blk["provider"] == "rfc3161":
                if tsa_pem is None:
                    report.check(f"tsa_{label}", False, "trusted or pinned TSA certificate required for rfc3161 token")
                else:
                    res = verify_rfc3161_tst(
                        tfile.read_bytes(),
                        bytes.fromhex(blk["digest_sha256"]),
                        trusted_cert_pem=tsa_pem,
                        expected_nonce=blk.get("nonce"),
                        pinned_root_sha256s=pinned_roots,
                    )
                    report.check(f"tsa_{label}", res.valid, res.reason)
                    if res.valid and res.gen_time_utc:
                        gen_times[label] = _parse_utc(res.gen_time_utc)
            elif require_live_tsa:
                report.check(f"tsa_{label}", False, "live rfc3161 TSA required")
            else:
                gen_times[label] = _parse_utc(blk["gen_time_utc"])

        if "commitment" in gen_times and "post_beacon" in gen_times and "session_close" in gen_times:
            chrono_ok = (
                gen_times["commitment"] <= gen_times["post_beacon"] <= gen_times["session_close"]
                and all(
                    lbl in gen_times
                    and gen_times["post_beacon"] <= gen_times[lbl] <= gen_times["session_close"]
                    for lbl in checkpoint_labels
                )
            )
            report.check(
                "tsa_chronology",
                chrono_ok,
                "commitment <= post_beacon <= checkpoints <= session_close TSA gen_time ordering",
            )
        if pre["beacon_config"]["scheme"] == "drand-quicknet" and providers.get("commitment") == "rfc3161" and "commitment" in gen_times:
            round_time = drand_quicknet_round_time_utc(post["beacon"]["round_number"])
            report.check(
                "commitment_precedes_beacon_round",
                round_time >= gen_times["commitment"],
                f"quicknet_round_utc={round_time.isoformat()} commitment_tsa_utc={gen_times['commitment'].isoformat()}",
            )

    report.capture("tsa_checks", check_tsa)

    # Dual disclosure + full deterministic assignment reconstruction & instrument re-scoring
    def check_disclosure_and_scores() -> None:
        ok_disc, disc_errs = verify_disclosure_bundle(
            root,
            expected_mode=d_mode,
            escrow_dir=esc_path,
        )
        report.check("disclosure_mode", ok_disc, "; ".join(disc_errs) or d_mode)

        t_path: Path | None = None
        if d_mode == DISCLOSURE_GENERAL:
            t_path = bundle_path(root, "referee_targets.json")
        elif esc_path is not None:
            t_path = bundle_path(esc_path, "referee_targets.json")

        if t_path is None:
            return
        if not t_path.is_file():
            report.check("referee_targets_present", False, str(t_path))
            return

        tdoc = read_json(t_path, canonical=True)
        by_slot_t = {item["slot_id"]: item["spec"] for item in tdoc["trials"]}
        expected_pub_by_slot: dict[str, dict[str, Any]] = {}
        if run_seed is not None:
            for slot in planned_slots:
                sid = slot["slot_id"]
                inst_seed = derive_instance_seed_v1(run_seed, slot["family_id"], slot["slot_index"])
                exp_pub, exp_hid_raw = derive_canonical_task(inst_seed, slot["family_id"], slot["slot_index"])
                exp_hid = enrich_canonical_target(exp_hid_raw)
                expected_pub_by_slot[sid] = exp_pub
                report.check(
                    "seed_derived_target",
                    sid in by_slot_t and by_slot_t[sid] == exp_hid,
                    sid,
                )

        if len(by_slot_t) != len(planned_slots):
            report.check("target_slot_completeness", False, "referee_targets count disagrees with planned_slots")

        for tm in trials:
            sid = tm["slot_id"]
            if sid not in by_slot_t:
                report.check("target_slot_missing", False, sid)
                continue
            spec = by_slot_t[sid]
            report.check(
                "assignment_commitment",
                post["assignment_commitments"].get(sid) == object_hash(spec),
                sid,
            )
            rec = read_json(bundle_path(root, tm["record_path"]))
            exp_pub = expected_pub_by_slot.get(sid)
            record_meta_ok = (
                rec.get("slot_id") == tm["slot_id"]
                and rec.get("execution_attempt_id") == tm["execution_attempt_id"]
                and rec.get("mask_tactile") == pre["mask_tactile"]
                and (exp_pub is None or rec.get("instruction") == exp_pub["instruction"])
            )
            report.check("record_slot_binding", record_meta_ok, tm["execution_attempt_id"])
            scale_r, cam_r = read_instrument_files(
                bundle_path(root, tm["scale_path"]),
                bundle_path(root, tm["overhead_path"]),
                expected_end_s=rec["steps"] / 10,
            )
            m_res = evaluate_scale_stream(
                scale_r, target_net_g=spec["target_net_g"], tolerance_g=spec["tolerance_g"],
                tare_g=spec["tare_g"], settle_window_s=spec["settle_window_s"],
                max_step_delta_g=spec["max_step_delta_g"],
            )
            g_res = evaluate_overhead_stream(
                cam_r, target_spec=spec, settle_window_s=spec["settle_window_s"],
                max_bezel_drift_mm=spec["max_bezel_drift_mm"],
            )
            recomputed = {"eutropos-mass": float(m_res.passed), "eutropos-geometry": float(g_res.passed)}
            report.check("recomputed_scores", recomputed == tm["scores"], tm["execution_attempt_id"])

    report.capture("disclosure_and_scores", check_disclosure_and_scores)
    setattr(report, "_verified_file_digests", verified_digests)
    return report.finish()


V1_ATTACK_REASONS = {
    "abort_hidden_from_ledger": "slot_chain",
    "tsa_digest_swap": "tsa_session_close_digest",
    "drand_signature_bitflip": "drand_beacon",
    "adjudication_erased_raw_score": "adjudication_original_scores",
}


def tamper_v1_bundle(src: Path, dst: Path, attack: str) -> Path:
    import shutil

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if attack == "abort_hidden_from_ledger":
        ledger_p = dst / "manifests" / "slot_ledger.jsonl"
        rows = read_jsonl(ledger_p)
        kept = [r for r in rows if r["status"] != "start_failure"]
        for i, r in enumerate(kept):
            r["seq"] = i
        ledger_p.write_bytes(b"".join(canonical_json(r) + b"\n" for r in kept))
        return dst
    if attack == "tsa_digest_swap":
        (dst / "tsa" / "session_close.tsr").write_bytes((dst / "tsa" / "commitment.tsr").read_bytes())
        return dst
    if attack == "drand_signature_bitflip":
        rev_p = dst / "seed_reveal.json"
        post_p = dst / "post_beacon_inputs.json"
        rev = read_json(rev_p, canonical=True)
        post_d = read_json(post_p, canonical=True)
        for doc_beacon in (rev["beacon"], post_d["beacon"]):
            if "signature_hex" in doc_beacon and doc_beacon["signature_hex"]:
                sig = doc_beacon["signature_hex"]
                doc_beacon["signature_hex"] = ("0" if sig[0] != "0" else "1") + sig[1:]
            else:
                vh = doc_beacon["value_hex"]
                doc_beacon["value_hex"] = ("0" if vh[0] != "0" else "1") + vh[1:]
        write_json(rev_p, rev)
        write_json(post_p, post_d)
        return dst
    if attack == "adjudication_erased_raw_score":
        # Alter first trial manifest's recorded raw score to diverge from adjudication.original_scores
        m_p = dst / "manifests" / "trial_0000.json"
        m = read_json(m_p, canonical=True)
        m["scores"]["eutropos-mass"] = 0.0 if m["scores"]["eutropos-mass"] == 1.0 else 1.0
        write_json(m_p, m)
        return dst
    raise ValueError(f"unknown v1 attack: {attack!r}")


def prove_v1(out_dir: str | Path, *, live_crypto: bool = False) -> tuple[bool, dict[str, Any]]:
    root = prepare_empty_directory(Path(out_dir))
    trusted_open = root / "trusted-v1-open.pem"
    open_dir = run_v1_session_bundle(
        root / "evidence_open",
        pareto_profile="P2",
        mask_tactile=True,
        disclosure_mode=DISCLOSURE_GENERAL,
        live_crypto=live_crypto,
        write_trusted_public_key=trusted_open,
    )
    rep_open = verify_v1_bundle(
        open_dir,
        public_key=trusted_open,
        require_live_beacon=live_crypto,
        require_live_tsa=live_crypto,
    )

    trusted_haz = root / "trusted-v1-hazard.pem"
    escrow_dir = root / "hazard_escrow_archive"
    haz_dir = run_v1_session_bundle(
        root / "evidence_hazard",
        pareto_profile="P1",
        mask_tactile=False,
        disclosure_mode=DISCLOSURE_HAZARD,
        live_crypto=live_crypto,
        write_trusted_public_key=trusted_haz,
        escrow_dir=escrow_dir,
    )
    rep_haz_pub = verify_v1_bundle(
        haz_dir, public_key=trusted_haz,
        require_live_beacon=live_crypto, require_live_tsa=live_crypto,
    )
    rep_haz_escrow = verify_v1_bundle(
        haz_dir, public_key=trusted_haz, escrow_dir=escrow_dir,
        require_live_beacon=live_crypto, require_live_tsa=live_crypto,
        require_full_rescore=True,
    )

    tampers: dict[str, Any] = {}
    for attack, expected_reason in V1_ATTACK_REASONS.items():
        dst = root / "tamper_tests" / attack
        tamper_v1_bundle(open_dir, dst, attack)
        trep = verify_v1_bundle(dst, public_key=trusted_open)
        detected = (not trep.passed) and any(
            f.startswith(expected_reason + ":") or expected_reason in f
            for f in trep.failures
        )
        tampers[attack] = {
            "expected_reason": expected_reason,
            "detected_for_expected_reason": detected,
            "verification": asdict(trep),
        }

    hazard_no_seed_leak = not (haz_dir / "seed_reveal.json").exists()
    passed = (
        rep_open.passed
        and rep_haz_pub.passed
        and rep_haz_escrow.passed
        and hazard_no_seed_leak
        and all(t["detected_for_expected_reason"] for t in tampers.values())
    )
    result = {
        "passed": passed,
        "live_crypto": live_crypto,
        "open_evidence_dir": str(open_dir),
        "trusted_open_public_key": str(trusted_open),
        "open_verification": asdict(rep_open),
        "hazard_evidence_dir": str(haz_dir),
        "hazard_escrow_dir": str(escrow_dir),
        "hazard_public_verification": asdict(rep_haz_pub),
        "hazard_escrow_verification": asdict(rep_haz_escrow),
        "tamper_tests": tampers,
    }
    write_json(root / "proof_v1_report.json", result)
    return passed, result
