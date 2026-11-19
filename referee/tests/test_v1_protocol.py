"""Tests for Protocol v1.0 cryptographic anchoring, slot ledger, dual disclosure, and live snapshot verification."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from habilis_referee.beacon import (
    DRAND_QUICKNET_PUBKEY_HEX,
    verify_drand_round,
    verify_rfc3161_tst,
)
from habilis_referee.certificate import CERTIFICATE_VERSION_V1, load_public_key, verify_certificate
from habilis_referee.disclosure import DISCLOSURE_GENERAL, DISCLOSURE_HAZARD
from habilis_referee.isolation import SubprocessPolicyAdapter, _encode_observation
from habilis_referee.manifest import read_json, read_jsonl
from habilis_referee.protocol_v1 import (
    V1_ATTACK_REASONS,
    V1_FIXED_VECTOR,
    compute_v1_seed_vector,
    prove_v1,
    run_v1_session_bundle,
    tamper_v1_bundle,
    verify_v1_bundle,
)
from habilis_referee.verifier import verify_bundle
from inspect_robots.types import Observation
import numpy as np

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "live_crypto_snapshot.json"


def test_v1_seed_fixed_test_vectors() -> None:
    vec = compute_v1_seed_vector(
        bytes.fromhex(V1_FIXED_VECTOR["secret_hex"]),
        bytes.fromhex(V1_FIXED_VECTOR["nonce_hex"]),
        bytes.fromhex(V1_FIXED_VECTOR["submitter_hex"]),
        bytes.fromhex(V1_FIXED_VECTOR["beacon_hex"]),
        V1_FIXED_VECTOR["family_id"],
        V1_FIXED_VECTOR["trial_index"],
    )
    # Deterministically verify against direct domain-separated SHA-256 reference
    def lp(b: bytes) -> bytes:
        return len(b).to_bytes(8, "big") + b

    s = bytes.fromhex(V1_FIXED_VECTOR["secret_hex"])
    n = bytes.fromhex(V1_FIXED_VECTOR["nonce_hex"])
    sub = bytes.fromhex(V1_FIXED_VECTOR["submitter_hex"])
    bval = bytes.fromhex(V1_FIXED_VECTOR["beacon_hex"])
    c_ref = hashlib.sha256(b"habilis-seed-commit-v1.0" + lp(s) + lp(n)).hexdigest()
    r_ref = hashlib.sha256(b"habilis-run-seed-v1.0" + lp(s) + lp(sub) + lp(bval)).digest()
    e_ref = int.from_bytes(r_ref[:4], "big") & 0x7FFFFFFF
    inst_ref = hashlib.sha256(
        b"habilis-trial-seed-v1.0" + r_ref + lp(b"E1") + (0).to_bytes(8, "big")
    ).hexdigest()
    assert vec == {
        "commitment_C": c_ref,
        "derived_R_hex": r_ref.hex(),
        "eval_seed": e_ref,
        "instance_seed_hex": inst_ref,
    }


def test_live_crypto_snapshot_offline_verification() -> None:
    snap = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    dq = snap["drand_quicknet"]
    d_res = verify_drand_round(
        dq["round_number"],
        dq["value_hex"],
        dq["signature_hex"],
        public_key_hex=snap["drand_public_key_hex"],
        scheme="drand-quicknet",
    )
    assert d_res.valid

    tsr_der = base64.b64decode(snap["freetsa_response_b64"])
    digest = bytes.fromhex(snap["freetsa_digest_hex"])
    t_res = verify_rfc3161_tst(
        tsr_der, digest, trusted_cert_pem=snap["freetsa_cacert_pem"]
    )
    assert t_res.valid and t_res.gen_time_utc == snap["freetsa_gen_time_utc"]

    # Wrong digest must fail offline RFC 3161 verification
    bad_t = verify_rfc3161_tst(
        tsr_der, hashlib.sha256(b"tampered").digest(),
        trusted_cert_pem=snap["freetsa_cacert_pem"],
    )
    assert not bad_t.valid


def test_v1_protocol_prove_and_tampers(tmp_path: Path) -> None:
    passed, report = prove_v1(tmp_path / "v1_proof", live_crypto=False)
    assert passed is True
    assert report["open_verification"]["passed"] is True
    assert report["hazard_public_verification"]["passed"] is True
    assert report["hazard_escrow_verification"]["passed"] is True

    open_dir = Path(report["open_evidence_dir"])
    pub_key = Path(report["trusted_open_public_key"])
    cert = verify_certificate(
        read_json(open_dir / "certificate.json", canonical=True),
        load_public_key(pub_key),
    )
    assert cert["certificate_version"] == CERTIFICATE_VERSION_V1
    assert cert["pareto_profile"] == "P2"
    assert cert["mask_tactile"] is True
    assert cert["disclosure_mode"] == DISCLOSURE_GENERAL
    assert cert["slot_summary"]["start_failure_events"] == 1
    assert cert["slot_summary"]["terminal_start_failures"] == 0
    assert cert["slot_summary"]["retries"] == 1
    assert cert["slot_summary"]["registered_slots"] == 3
    assert cert["slot_summary"]["effective_pass_rate"] == 1.0

    # verify_bundle dispatches cleanly to v1.0
    via_unified = verify_bundle(open_dir, public_key=pub_key)
    assert via_unified.passed

    # hazard-escrowed hides referee_targets.json, seed_reveal.json, and closed_video from public bundle
    haz_dir = Path(report["hazard_evidence_dir"])
    escrow_dir = Path(report["hazard_escrow_dir"])
    assert not (haz_dir / "referee_targets.json").exists()
    assert not (haz_dir / "seed_reveal.json").exists()
    assert not (haz_dir / "closed_video").exists()
    assert (haz_dir / "escrow_receipt.json").is_file()
    assert (escrow_dir / "seed_reveal.json").is_file()
    haz_cert = verify_certificate(
        read_json(haz_dir / "certificate.json", canonical=True),
        load_public_key(haz_dir / "public_key.pem"),
    )
    assert haz_cert["seed"].get("seed_reveal_escrowed") is True
    assert not ({"S_hex", "nonce_hex", "derived_R_hex"} & set(haz_cert["seed"]))

    # Check unrecovered abort updates effective pass rate denominator honestly (1 / 2 = 0.5)
    abort_key = tmp_path / "abort_key.pem"
    abort_dir = run_v1_session_bundle(
        tmp_path / "abort_no_retry",
        families=("E1", "E3"),
        inject_start_failure_and_retry=False,
        abort_slot_indices=(1,),
        disclosure_mode=DISCLOSURE_GENERAL,
        write_trusted_public_key=abort_key,
    )
    assert verify_v1_bundle(abort_dir, public_key=abort_key).passed
    abort_cert = verify_certificate(
        read_json(abort_dir / "certificate.json", canonical=True),
        load_public_key(abort_key),
    )
    assert abort_cert["slot_summary"]["registered_slots"] == 2
    assert abort_cert["slot_summary"]["completed_slots"] == 1
    assert abort_cert["slot_summary"]["aborted_slots"] == 1
    assert abort_cert["slot_summary"]["effective_pass_rate"] == 0.5
    # Check tamper cases all rejected
    for attack, expected in V1_ATTACK_REASONS.items():
        assert report["tamper_tests"][attack]["detected_for_expected_reason"] is True
        assert report["tamper_tests"][attack]["expected_reason"] == expected


def test_isolation_tactile_mask_and_rpc_timeout() -> None:
    obs = Observation(
        images={"head_left": np.zeros((4, 4, 3), dtype=np.uint8)},
        state={
            "joint_pos": np.zeros(26),
            "fingertip_tactile": np.ones(15),
            "touch_pressure": np.ones(5),
        },
        instruction="test",
    )
    masked = _encode_observation(obs, mask_tactile=True)
    assert list(masked["state"]) == ["joint_pos"]

    adapter = SubprocessPolicyAdapter("compliant", timeout_s=0.35)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time, sys; sys.stdin.readline(); time.sleep(3)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        adapter._proc = proc
        with pytest.raises(TimeoutError):
            adapter._rpc({"op": "hang"})
    finally:
        adapter.close()
