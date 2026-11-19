"""C3 adversarial security & correctness regression tests (Opus 5.5 + Astra red-team PoCs)."""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import asn1crypto.cms as cms
import asn1crypto.tsp as tsp
import asn1crypto.x509 as ax509
import numpy as np
import py_ecc.optimized_bls12_381 as bls12
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image
from py_ecc.bls.hash_to_curve import hash_to_G1
from py_ecc.bls.point_compression import compress_G1, compress_G2

from eutropos_referee.a4_harness import (
    _parse_verdict,
    analyze_a4_results,
    exact_mcnemar_pvalue,
    export_blinded_trial_frames,
    run_gemini_vision,
    score_trial_robodojo_astra,
)
from eutropos_referee.beacon import (
    DRAND_QUICKNET_DST,
    BeaconReading,
    u64,
    verify_rfc3161_tst,
)
from eutropos_referee.calibration import (
    HomographyCalibration,
    apply_homography,
    calibrate_overhead_homography,
    detect_fiducial_centroids_px,
    generate_calibration_board,
    pre_trial_bench_check,
)
from eutropos_referee.certificate import generate_or_load_private_key, sign_certificate
from eutropos_referee.disclosure import DISCLOSURE_GENERAL, DISCLOSURE_HAZARD, prepare_disclosure_bundle
from eutropos_referee.families_15 import evaluate_canonical_family
from eutropos_referee.generator import derive_canonical_task
from eutropos_referee.hardware_drivers import (
    ByteStreamTransport,
    MockCBCP01Transport,
    OverheadCameraDriver,
    RadwagCBCP01Driver,
)
from eutropos_referee.instruments import encode_si_frame
from eutropos_referee.manifest import object_hash, read_json, read_jsonl, sha256_file, write_json
from eutropos_referee.protocol_v1 import (
    SlotLedger,
    run_v1_session_bundle,
    summarize_slots,
    verify_v1_bundle,
)
from eutropos_referee.report_html import render_audit_html
from eutropos_referee.runner import run_bundle
from eutropos_referee.verifier import verify_bundle


def _resign_cert(root: Path, priv: Any, updater: Any) -> None:
    env = read_json(root / "certificate.json", canonical=True)
    raw_p = env["payload"]
    pad = "=" * (-len(raw_p) % 4)
    payload = json.loads(base64.urlsafe_b64decode(raw_p + pad).decode("utf-8"))
    updater(payload)
    write_json(root / "certificate.json", sign_certificate(payload, priv))


def _update_close_and_resign(root: Path, priv: Any) -> None:
    close_p = root / "manifests" / "session_close.json"
    close = read_json(close_p, canonical=True)
    close["slot_ledger_sha256"] = sha256_file(root / "manifests" / "slot_ledger.jsonl")
    close_files = [root / e["path"] for e in close["files"] if (root / e["path"]).is_file()]
    from eutropos_referee.manifest import file_entries

    close["files"] = file_entries(root, close_files)
    write_json(close_p, close)
    new_root_hash = sha256_file(close_p)

    def _upd(p: dict[str, Any]) -> None:
        p["evidence"]["chain_root_hash"] = new_root_hash
        p["evidence"]["slot_ledger_sha256"] = close["slot_ledger_sha256"]

    _resign_cert(root, priv, _upd)


def test_c1_c2_c3_beacon_and_tsa_pinning_regressions(tmp_path: Path) -> None:
    snap = json.loads((Path(__file__).parent / "fixtures" / "live_crypto_snapshot.json").read_text(encoding="utf-8"))

    # C1 / Astra #4: Rogue BLS12-381 keypair registered inside drand-quicknet metadata must be rejected
    sk = 123456789
    c2 = compress_G2(bls12.multiply(bls12.G2, sk))
    rogue_pk = (c2[0].to_bytes(48, "big") + c2[1].to_bytes(48, "big")).hex()
    round_no = 500
    sig_pt = bls12.multiply(hash_to_G1(hashlib.sha256(u64(round_no)).digest(), DRAND_QUICKNET_DST, hashlib.sha256), sk)
    sig_hex = compress_G1(sig_pt).to_bytes(48, "big").hex()
    rogue_reading = BeaconReading(
        provider="https://rogue.example.com",
        round_number=round_no,
        fetched_at="2026-11-19T00:00:00Z",
        value_hex=hashlib.sha256(bytes.fromhex(sig_hex)).hexdigest(),
        signature_hex=sig_hex,
        chain_hash="11" * 32,
        cryptographically_verified=True,
        scheme="drand-quicknet",
    )
    pub_k = tmp_path / "rogue_pub.pem"
    ev_rogue = run_v1_session_bundle(
        tmp_path / "rogue_beacon",
        families=("E1",),
        inject_start_failure_and_retry=False,
        beacon_reading=rogue_reading,
        write_trusted_public_key=pub_k,
    )
    rep_rogue = verify_v1_bundle(ev_rogue, public_key=pub_k, require_live_beacon=True)
    assert not rep_rogue.passed
    assert any("drand" in f for f in rep_rogue.failures)

    # Astra #6: legacy v0.2 bundle must fail when require_live_beacon=True or require_live_tsa=True
    pub_v02 = tmp_path / "v02_pub.pem"
    ev_v02 = run_bundle(tmp_path / "v02", epochs=1, policy="scripted", write_trusted_public_key=pub_v02)
    assert not verify_bundle(ev_v02, public_key=pub_v02, require_live_beacon=True).passed
    assert not verify_bundle(ev_v02, public_key=pub_v02, require_live_tsa=True).passed

    # C3 / Astra #5: self-signed bundled tsa/tsa_chain.pem rejected when trusted_tsa_pem is None
    now = datetime.datetime.now(datetime.UTC)
    priv_tsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rogue TSA")])
    rogue_cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(priv_tsa.public_key())
        .serial_number(99)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(priv_tsa, hashes.SHA256())
    )
    digest = hashlib.sha256(b"rogue-tsa-bundle-test").digest()
    tst_der = tsp.TSTInfo({
        "version": 1, "policy": "1.2.3.4",
        "message_imprint": {"hash_algorithm": {"algorithm": "sha256", "parameters": None}, "hashed_message": digest},
        "serial_number": 5, "gen_time": now.replace(microsecond=0),
    }).dump()
    rogue_der = rogue_cert.public_bytes(serialization.Encoding.DER)
    sa = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["1.2.840.113549.1.9.16.1.4"]}),
        cms.CMSAttribute({"type": "signing_certificate", "values": [tsp.SigningCertificate({"certs": [{"cert_hash": hashlib.sha1(rogue_der).digest()}]})]}),
        cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(tst_der).digest()]}),
    ])
    sig = priv_tsa.sign(cms.CMSAttributes(sa.native).dump(), padding.PKCS1v15(), hashes.SHA256())
    ac = ax509.Certificate.load(rogue_der)
    sd = cms.SignedData({
        "version": "v3", "digest_algorithms": [{"algorithm": "sha256", "parameters": None}],
        "encap_content_info": {"content_type": "1.2.840.113549.1.9.16.1.4", "content": cms.ParsableOctetString(tst_der)},
        "certificates": [cms.CertificateChoices({"certificate": ac})],
        "signer_infos": [{
            "version": "v1",
            "sid": {"issuer_and_serial_number": {"issuer": ac.issuer, "serial_number": ac.serial_number}},
            "digest_algorithm": {"algorithm": "sha256", "parameters": None},
            "signed_attrs": sa,
            "signature_algorithm": {"algorithm": "sha256_rsa", "parameters": None},
            "signature": sig,
        }],
    })
    tsr_der = tsp.TimeStampResp({"status": {"status": "granted"}, "time_stamp_token": {"content_type": "signed_data", "content": sd}}).dump()

    # Valid with explicit caller trust, rejected when pinned FreeTSA root hash is enforced
    assert verify_rfc3161_tst(tsr_der, digest, trusted_cert_pem=rogue_cert.public_bytes(serialization.Encoding.PEM)).valid
    from eutropos_referee.beacon import PINNED_TSA_ROOT_SHA256S

    res_pinned = verify_rfc3161_tst(
        tsr_der, digest,
        trusted_cert_pem=rogue_cert.public_bytes(serialization.Encoding.PEM),
        pinned_root_sha256s=PINNED_TSA_ROOT_SHA256S,
    )
    assert not res_pinned.valid

    # Bundle-level rogue tsa/tsa_chain.pem rejection with require_live_tsa=True & trusted_tsa_pem=None
    key_signer = generate_or_load_private_key()
    pub_t = tmp_path / "pub_t.pem"
    ev_t = run_v1_session_bundle(
        tmp_path / "ev_tsa_bundle",
        families=("E1",),
        inject_start_failure_and_retry=False,
        private_key=key_signer,
        write_trusted_public_key=pub_t,
    )
    (ev_t / "tsa" / "tsa_chain.pem").write_bytes(rogue_cert.public_bytes(serialization.Encoding.PEM))
    (ev_t / "tsa" / "commitment.tsr").write_bytes(tsr_der)

    def _swap_comm_tsa(p: dict[str, Any]) -> None:
        p["evidence"]["tsa_receipts"]["commitment"]["provider"] = "rfc3161"
        p["evidence"]["tsa_receipts"]["commitment"]["digest_sha256"] = digest.hex()
        p["evidence"]["tsa_receipts"]["commitment"]["tsr_sha256"] = sha256_file(ev_t / "tsa" / "commitment.tsr")

    _resign_cert(ev_t, key_signer, _swap_comm_tsa)
    assert not verify_v1_bundle(ev_t, public_key=pub_t, trusted_tsa_pem=None, require_live_tsa=True).passed

    # Live FreeTSA snapshot + incompatible CMS sig_algo rejected (Astra #22)
    live_der = base64.b64decode(snap["freetsa_response_b64"])
    live_digest = bytes.fromhex(snap["freetsa_digest_hex"])
    resp_mod = tsp.TimeStampResp.load(live_der)
    resp_mod["time_stamp_token"]["content"]["signer_infos"][0]["signature_algorithm"] = {"algorithm": "sha512_rsa"}
    bad_sig_algo = verify_rfc3161_tst(resp_mod.dump(), live_digest, trusted_cert_pem=snap["freetsa_cacert_pem"])
    assert not bad_sig_algo.valid

    # Noncritical TSA EKU rejected (Astra #18)
    noncrit_cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(priv_tsa.public_key())
        .serial_number(100)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=False)
        .sign(priv_tsa, hashes.SHA256())
    )
    assert not verify_rfc3161_tst(
        tsr_der, digest, trusted_cert_pem=noncrit_cert.public_bytes(serialization.Encoding.PEM)
    ).valid


def test_c4_ledger_hazard_and_target_reconstruction_regressions(tmp_path: Path) -> None:
    priv = generate_or_load_private_key()
    pub = tmp_path / "pub.pem"
    ev = run_v1_session_bundle(
        tmp_path / "base_open",
        families=("E1", "E3"),
        inject_start_failure_and_retry=False,
        private_key=priv,
        write_trusted_public_key=pub,
    )
    assert verify_v1_bundle(ev, public_key=pub).passed

    # Astra #7: Resign forged referee_targets.json + matching post assignment_commitments (seed unchanged)
    t_path = ev / "referee_targets.json"
    tdoc = read_json(t_path, canonical=True)
    tdoc["trials"][0]["spec"]["target_net_g"] = 999.0
    write_json(t_path, tdoc)
    post = read_json(ev / "post_beacon_inputs.json", canonical=True)
    post["assignment_commitments"]["slot-00"] = object_hash(tdoc["trials"][0]["spec"])
    write_json(ev / "post_beacon_inputs.json", post)
    assert not verify_v1_bundle(ev, public_key=pub).passed

    # H2 / Astra #9 & #11: SlotLedger forbids duplicate completed attempt & preserves history across reload
    slots = [
        {"slot_index": 0, "slot_id": "s0", "logical_instance_id": "i0", "family_id": "E1", "scene_id": "sc0", "epoch": 0, "init_seed": 1},
    ]
    led_path = tmp_path / "ledger.jsonl"
    led1 = SlotLedger(led_path, slots)
    led1.record(slot_id="s0", logical_instance_id="i0", execution_attempt_id="a0", status="start_failure")
    led2 = SlotLedger(led_path, slots)
    assert len(led2.entries) == 1
    with pytest.raises(ValueError):
        led2.record(slot_id="s0", logical_instance_id="i0", execution_attempt_id="a1", status="completed", retry_of_attempt_id=None, manifest_path="manifests/trial_0000.json", trial_passed=True, scores={"eutropos-mass": 1.0, "eutropos-geometry": 1.0})
    led2.record(slot_id="s0", logical_instance_id="i0", execution_attempt_id="a1", status="completed", retry_of_attempt_id="a0", manifest_path="manifests/trial_0000.json", trial_passed=True, scores={"eutropos-mass": 1.0, "eutropos-geometry": 1.0})
    with pytest.raises(ValueError):
        led2.record(slot_id="s0", logical_instance_id="i0", execution_attempt_id="a2", status="completed", retry_of_attempt_id=None, manifest_path="manifests/trial_0001.json", trial_passed=True, scores={"eutropos-mass": 1.0, "eutropos-geometry": 1.0})

    # Astra #10: summarize_slots rejects duplicate slot IDs
    with pytest.raises(ValueError):
        summarize_slots([slots[0], slots[0]], read_jsonl(led_path))

    # Astra #14: Cert mask_tactile mismatch vs preregistration caught
    pub_h = tmp_path / "pub_h.pem"
    esc_h = tmp_path / "esc_h"
    ev_h = run_v1_session_bundle(
        tmp_path / "haz",
        families=("E1",),
        disclosure_mode=DISCLOSURE_HAZARD,
        inject_start_failure_and_retry=False,
        private_key=priv,
        write_trusted_public_key=pub_h,
        escrow_dir=esc_h,
    )
    assert not verify_v1_bundle(ev_h, public_key=pub_h, require_full_rescore=True).passed
    assert verify_v1_bundle(ev_h, public_key=pub_h, escrow_dir=esc_h, require_full_rescore=True).passed
    _resign_cert(ev_h, priv, lambda p: p.__setitem__("mask_tactile", True))
    rep_h_bad = verify_v1_bundle(ev_h, public_key=pub_h)
    assert not rep_h_bad.passed

    # Astra #16: prepare_disclosure_bundle rejects escaping escrow symlink
    pub_dir = tmp_path / "disc_pub"
    esc_dir = tmp_path / "disc_esc"
    pub_dir.mkdir()
    (pub_dir / "referee_targets.json").write_text("{}", encoding="utf-8")
    (pub_dir / "seed_reveal.json").write_text("{}", encoding="utf-8")
    escaped_target = pub_dir / "leaked"
    escaped_target.mkdir()
    esc_dir.mkdir()
    try:
        (esc_dir / "sub").symlink_to(escaped_target, target_is_directory=True)
        (pub_dir / "sub").mkdir()
        (pub_dir / "sub" / "secret.bin").write_bytes(b"secret")
        with pytest.raises(ValueError, match="symlink|escape|inside public"):
            prepare_disclosure_bundle(
                pub_dir, mode=DISCLOSURE_HAZARD,
                private_relpaths=["referee_targets.json", "seed_reveal.json", "sub/secret.bin"],
                escrow_dir=esc_dir, benign_surrogate_declared=True,
            )
    except OSError:
        pass  # Windows unprivileged symlink creation may require Developer Mode


def test_hardware_calibration_families_a4_and_html_c3_regressions(tmp_path: Path) -> None:
    # Astra #25: Radwag OT grammar rejects OT_ERROR and kg units
    class _RawOT(ByteStreamTransport):
        def __init__(self, reply: bytes) -> None:
            self.reply = reply

        def write(self, data: bytes) -> int:
            return len(data)

        def read(self, size: int = 1) -> bytes:
            return self.reply[:size]

        def readline(self) -> bytes:
            return self.reply

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    for bad_ot in (b"OT_ERROR 17\r\n", b"OT 12 kg\r\n", b"CORRUPT 5\r\n"):
        drv = RadwagCBCP01Driver(transport=_RawOT(bad_ot))
        with pytest.raises(ValueError):
            drv.read_tare()

    # Astra #26 & #27: backward clock recorded in nonmonotonic_clocks and <5 frames / timeout fails precheck
    ticks = [0, 100_000_000, 90_000_000, 80_000_000, 70_000_000, 60_000_000]
    t_idx = {"i": 0}

    def _backward_clk() -> int:
        val = ticks[min(t_idx["i"], len(ticks) - 1)]
        t_idx["i"] += 1
        return val

    drv_bw = RadwagCBCP01Driver(transport=MockCBCP01Transport([(0.0, " ")] * 5), clock_ns=_backward_clk)
    drv_bw.enable_continuous()
    cap_bw = drv_bw.capture_stream(max_frames=5)
    assert len(cap_bw.nonmonotonic_clocks) == 4

    board = generate_calibration_board(tmp_path / "b.png")
    rgb = np.asarray(Image.open(board.png_path).convert("RGB"), dtype=np.uint8)
    hom = calibrate_overhead_homography(rgb)
    cam = OverheadCameraDriver(backend="mock", frame_provider=lambda _i: rgb)

    # Precheck must fail with <5 scale readings (timeouts)
    class _ShortTimeoutTransport(_RawOT):
        def __init__(self) -> None:
            self.calls = 0

        def write(self, data: bytes) -> int:
            return len(data)

        def readline(self) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"C1_A\r\n"
            if self.calls == 2:
                return encode_si_frame(0.0, stability=" ")
            return b""

    drv_short = RadwagCBCP01Driver(transport=_ShortTimeoutTransport())
    drv_short.enable_continuous()
    rep_short = pre_trial_bench_check(scale_driver=drv_short, camera_driver=cam, calibration=hom)
    assert not rep_short.passed and any("timeout" in r or "expected 5" in r for r in rep_short.reasons)

    # Astra #28 & #29: NaN homography and >4 cyan components rejected
    bad_hom = HomographyCalibration(
        h_px_to_mm=[[float("nan"), 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        h_mm_to_px=hom.h_mm_to_px,
        reference_fiducials_px=hom.reference_fiducials_px,
        reference_fiducials_mm=hom.reference_fiducials_mm,
        reprojection_rmse_mm=0.0, pixels_per_mm=3.0,
    )
    with pytest.raises(ValueError):
        apply_homography(np.array([[10.0, 10.0]]), np.asarray(bad_hom.h_px_to_mm))
    decoy_rgb = rgb.copy()
    decoy_rgb[390:415, 390:415] = [0, 230, 230]  # 5th extra cyan patch
    with pytest.raises(ValueError, match="exactly 4"):
        detect_fiducial_centroids_px(decoy_rgb)

    # Astra #30–#35: families_15 fail-closed checks
    assert not evaluate_canonical_family("E4", {"expected_blocks": {"b1": [0.0, 0.0, 10.0]}, "pose_tol_mm": 2.0}, {"hands_in_home_zone": True, "observed_blocks": [{"id": "b1", "intact": True, "supported": True, "pos_mm": []}], "reference_card_in_zone": False}).passed
    assert not evaluate_canonical_family("L2", {"expected_card_text": "BIN-A"}, {"hands_in_home_zone": True, "card_visible_from_stereo": True}).passed
    assert not evaluate_canonical_family("L3", {"feasible": True}, {"hands_in_home_zone": True, "physical_completed": "false", "declared_impossible": False, "damaging_probe": False}).passed
    assert not evaluate_canonical_family("T1", {"required_tool": "spoon", "ratio_tol": 0.1}, {"hands_in_home_zone": True, "tool_used": "spoon", "tool_working_surface_contact": True, "direct_finger_manipulation_of_target": False, "outcome_ok": True}).passed
    assert not evaluate_canonical_family("I1", {"expected_bins": ["A", "B"], "item_count": 2}, {"hands_in_home_zone": True, "observed_bins": []}).passed

    # Astra #33–#36: a4_harness fixes
    assert _parse_verdict("I cannot determine whether this is a PASS.")[0] == "UNSURE"
    assert exact_mcnemar_pvalue(515, 515) == 1.0
    assert exact_mcnemar_pvalue(29, 0) > 0.0

    # Gemini API key sent in header, NOT URL
    seen_urls: list[str] = []
    frames = [np.zeros((8, 8, 3), dtype=np.uint8)]
    pkg = export_blinded_trial_frames(tmp_path / "gem", "tr_99_000001", "Task", frames, frames)
    run_gemini_vision("Judge", list(pkg.head_left_paths), api_key="secret-xyz", transport=lambda u, b: (seen_urls.append(u) or {"candidates": [{"content": {"parts": [{"text": "PASS"}]}}]}))
    assert "secret-xyz" not in seen_urls[0] and "?key=" not in seen_urls[0]

    # Missing strata in analyze_a4_results must trigger incomplete_strata stop-use gate
    partial_recs = [
        {"opaque_id": "t0", "family_id": "E1", "stratum": "S1", "ground_truth": 1, "robodojo_astra": score_trial_robodojo_astra(pkg, runner=lambda _p, _i: ("PASS", 0.1))}
    ]
    partial_res = analyze_a4_results(partial_recs, judge_keys=("robodojo_astra",), bootstrap_n=20)
    assert partial_res["judges"]["robodojo_astra"]["stop_use_triggered"] is True

    # report_html.py handles noncanonical/corrupt certificate cleanly + distinguishes LOCAL STUB DEMO
    pub_rep = tmp_path / "pub_rep.pem"
    ev_stub = run_v1_session_bundle(tmp_path / "ev_stub", families=("E1",), inject_start_failure_and_retry=False, write_trusted_public_key=pub_rep)
    assert "VERIFIED PASS (LOCAL STUB DEMO)" in render_audit_html(ev_stub, public_key=pub_rep)
    (ev_stub / "certificate.json").write_text('{"payload": "not_valid_json", "b": 1}', encoding="utf-8")
    assert "VERIFICATION FAILED" in render_audit_html(ev_stub, public_key=pub_rep)

    # vlm_policy.py rejects NaN or malformed-shape delta from malicious child
    import subprocess
    import sys
    from eutropos_referee.vlm_policy import IsolatedBimanualVlmPolicy
    from inspect_robots.types import Observation

    pol = IsolatedBimanualVlmPolicy(backend="mock", timeout_s=2.0)
    try:
        script = (
            "import json, sys; "
            "sys.stdin.readline(); "
            "sys.stdout.write('{\"ok\":true,\"result\":{\"delta\":[NaN],\"terminal\":\"done\",\"note\":\"x\",\"latency_s\":0.1,\"isolation_audit\":{}}}\\n'); "
            "sys.stdout.flush()"
        )
        pol._proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        obs = Observation(
            images={"head_left": np.zeros((4, 4, 3), dtype=np.uint8), "head_right": np.zeros((4, 4, 3), dtype=np.uint8)},
            state={"joint_pos": np.zeros(26)},
            instruction="test",
        )
        with pytest.raises(ValueError, match="non-finite|shape"):
            pol.step(0, obs)
    finally:
        pol.close()
