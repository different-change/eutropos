"""Tests for referee 0.3.0 Pareto profiles, isolation, vision, crypto beacons, and A4 harness."""

from __future__ import annotations

import datetime
import hashlib
import os
from pathlib import Path

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
from inspect_robots.spaces import ActionSemantics, Box, CameraSpec, ObservationSpace, StateField, StateSpec
from py_ecc.bls import G2ProofOfPossession
from py_ecc.bls.hash_to_curve import hash_to_G1
from py_ecc.bls.point_compression import compress_G1, compress_G2

from eutropos_referee.a4_harness import (
    analyze_a4_results,
    cohens_kappa,
    exact_mcnemar_pvalue,
    export_blinded_trial_frames,
    score_trial_datacenterbench_dual,
    score_trial_robodojo_astra,
    wilson_ci,
)
from eutropos_referee.beacon import (
    DRAND_QUICKNET_DST,
    DrandHttpBeacon,
    RFC3161Client,
    u64,
    verify_drand_round,
    verify_rfc3161_tst,
)
from eutropos_referee.certificate import load_public_key, verify_certificate
from eutropos_referee.generator import ALL_FAMILIES, derive_canonical_task
from eutropos_referee.instruments import (
    evaluate_flatness,
    evaluate_opening,
    evaluate_relations,
    evaluate_seating,
    evaluate_slot_passage,
)
from eutropos_referee.manifest import read_json
from eutropos_referee.profiles import (
    get_profile,
    mask_tactile_observation,
    validate_dexterous_semantics,
)
from eutropos_referee.runner import run_instruments_bundle
from eutropos_referee.verifier import verify_bundle
from eutropos_referee.vision import (
    OverheadCalibration,
    extract_overhead_scene,
    render_synthetic_overhead,
)


def test_pareto_profiles_and_semantic_validator() -> None:
    assert get_profile("P0").cost_tier_usd == 0
    assert get_profile("P1").effective_reach_mm == 540.0
    assert get_profile("P2").has_tactile is True

    obs = {"state": {"joint_pos": [0.0], "fingertip_tactile": [1.2]}, "extra": {"touch_raw": [1]}}
    masked = mask_tactile_observation(obs, mask_tactile=True)
    assert list(masked["state"]) == ["joint_pos"] and masked["extra"] == {}

    obs_space = ObservationSpace(
        cameras=(CameraSpec(name="head_left", height=32, width=32, channels=3),),
        state=StateSpec(fields=(StateField(key="joint_pos", shape=(14,), unit="rad", dtype="float64"),)),
    )
    dex_box = Box(
        shape=(14,), low=np.full(14, -1.0), high=np.full(14, 1.0),
        semantics=ActionSemantics(
            control_mode="joint_delta",
            dim_labels=(
                "x", "y", "z", "little_finger", "ring_finger", "middle_finger", "index_finger",
                "thumb_bend", "thumb_rotate", "pad9", "pad10", "pad11", "pad12", "pad13",
            ),
        ),
    )
    jaw_box = Box(
        shape=(14,), low=np.full(14, -1.0), high=np.full(14, 1.0),
        semantics=ActionSemantics(
            control_mode="joint_delta",
            dim_labels=(
                "x", "y", "z", "gripper", "j4", "j5", "j6", "j7",
                "j8", "j9", "j10", "j11", "j12", "j13",
            ),
        ),
    )
    ok_jaw, errs_jaw = validate_dexterous_semantics(jaw_box, obs_space, dex_box, obs_space)
    assert not ok_jaw and any("parallel-gripper" in e for e in errs_jaw)

    ok_same, errs_same = validate_dexterous_semantics(dex_box, obs_space, dex_box, obs_space)
    assert ok_same and errs_same == []


def test_subprocess_isolation_and_snooper(tmp_path: Path) -> None:
    key_out = tmp_path / "iso_compliant.pem"
    ev_clean = run_instruments_bundle(
        tmp_path / "iso_compliant", epochs=1, policy="compliant",
        isolated=True, write_trusted_public_key=key_out,
    )
    rep_clean = verify_bundle(ev_clean, public_key=key_out)
    assert rep_clean.passed
    cert_clean = verify_certificate(
        read_json(ev_clean / "certificate.json", canonical=True),
        load_public_key(key_out),
    )
    assert cert_clean["results"]["overall"]["pass_rate"] == 1.0

    key_snoop = tmp_path / "iso_snooper.pem"
    ev_snoop = run_instruments_bundle(
        tmp_path / "iso_snooper", epochs=1, policy="memory-disk-snooper",
        isolated=True, write_trusted_public_key=key_snoop,
    )
    rep_snoop = verify_bundle(ev_snoop, public_key=key_snoop)
    assert rep_snoop.passed
    cert_snoop = verify_certificate(
        read_json(ev_snoop / "certificate.json", canonical=True),
        load_public_key(key_snoop),
    )
    assert cert_snoop["results"]["overall"]["pass_rate"] == 0.0
    close = read_json(ev_snoop / "manifests/session_close.json", canonical=True)
    log = read_json(ev_snoop / close["eval_log_path"])
    transcripts = [tr for s in log["samples"] for tr in s["policy_transcripts"]]
    assert len(transcripts) == 4
    for tr in transcripts:
        assert tr["isolated_worker_pid"] != os.getpid()
        assert tr["snooper"]["isolated_cwd_empty"] is True
        assert tr["snooper"]["loaded_instruments_module"] is False
        assert tr["snooper"]["leaked_tokens"] == []


def test_overhead_vision_extractor_and_five_predicates() -> None:
    cal = OverheadCalibration()
    objs_ok = [
        {"id": "a", "color": "red", "bounds_mm": [-45.0, -10.0, -25.0, 10.0]},
        {"id": "b", "color": "green", "bounds_mm": [-10.0, -10.0, 10.0, 10.0]},
        {"id": "c", "color": "blue", "bounds_mm": [25.0, -10.0, 45.0, 10.0]},
    ]
    base, rgb = render_synthetic_overhead(objs_ok, cal)
    ext = extract_overhead_scene(rgb, base, cal)
    assert ext["bezel_fiducial_drift_mm"] <= 0.1
    assert ext["hands_in_home_zone"] is True
    assert [o["color"] for o in sorted(ext["objects"], key=lambda x: x["bounds_mm"][0])] == ["red", "green", "blue"]
    rel_ok = evaluate_relations(
        sorted(ext["objects"], key=lambda x: x["bounds_mm"][0]),
        rules=[{"kind": "evenly_spaced", "ids": ["obj-0", "obj-1", "obj-2"], "distance_tol_mm": 3.0}],
    )
    assert rel_ok.passed

    _, drifted = render_synthetic_overhead(objs_ok, cal, drift_px=(3.0, 0.0))
    assert extract_overhead_scene(drifted, base, cal)["bezel_fiducial_drift_mm"] >= 2.5
    _, intruded = render_synthetic_overhead(objs_ok, cal, hand_intrusion=True)
    assert extract_overhead_scene(intruded, base, cal)["hands_in_home_zone"] is False
    _, split_cloth = render_synthetic_overhead(
        [{"id": "cloth", "color": "yellow", "bounds_mm": [-30.0, -25.0, 30.0, 25.0], "split_gap": True}], cal
    )
    ext_split = extract_overhead_scene(split_cloth, base, cal)
    assert not evaluate_flatness(
        ext_split["objects"], target_color="yellow",
        zone_bounds_mm=[-55.0, -55.0, 55.0, 55.0], min_area_mm2=2500.0,
    ).passed

    assert evaluate_seating(
        [{"t_s": t / 10, "hands_in_home_zone": True, "fixture_switch_closed": True, "insertion_depth_mm": 19.0} for t in range(12)],
        min_depth_mm=18.0,
    ).passed
    assert not evaluate_seating(
        [{"t_s": t / 10, "hands_in_home_zone": True, "fixture_switch_closed": False, "insertion_depth_mm": 4.0} for t in range(12)],
        min_depth_mm=18.0,
    ).passed
    assert evaluate_opening(
        [{"t_s": t / 10, "hands_in_home_zone": True, "container_intact": True, "closure_open": True, "two_hand_hold_observed": True, "transferred_net_g": 40.0} for t in range(12)],
        min_transfer_net_g=35.0, empty_vessel_g=45.0,
    ).passed
    assert not evaluate_opening(
        [{"t_s": t / 10, "hands_in_home_zone": True, "container_intact": True, "closure_open": False, "two_hand_hold_observed": True, "transferred_net_g": 0.0} for t in range(12)],
        min_transfer_net_g=35.0, empty_vessel_g=45.0,
    ).passed
    assert evaluate_slot_passage(
        [{"t_s": 1.0, "object_id": "c0", "intact": True, "released": True},
         {"t_s": 2.0, "object_id": "c1", "intact": True, "released": True}],
        expected_count=2, catch_box_mass_g=11.34, unit_mass_g=5.67,
    ).passed
    assert not evaluate_slot_passage(
        [{"t_s": 1.0, "object_id": "c0", "intact": True, "released": True},
         {"t_s": 1.02, "object_id": "c1", "intact": True, "released": True}],
        expected_count=2, catch_box_mass_g=11.34, unit_mass_g=5.67,
    ).passed


def _make_tsa_resp(
    digest: bytes,
    *,
    eku_timestamp: bool = True,
    now: datetime.datetime | None = None,
    nonce: int | None = None,
) -> tuple[bytes, bytes]:
    now = now or datetime.datetime.now(datetime.UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Eutropos Test TSA")])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
    )
    if eku_timestamp:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True
        )
    else:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=True
        )
    cert = builder.sign(key, hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    tst_payload: dict[str, object] = {
        "version": 1, "policy": "1.2.3.4",
        "message_imprint": {
            "hash_algorithm": {"algorithm": "sha256", "parameters": None},
            "hashed_message": digest,
        },
        "serial_number": 77,
        "gen_time": now.replace(microsecond=0),
    }
    if nonce is not None:
        tst_payload["nonce"] = nonce
    tst_info = tsp.TSTInfo(tst_payload)
    tst_der = tst_info.dump()
    signed_attrs = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["1.2.840.113549.1.9.16.1.4"]}),
        cms.CMSAttribute({
            "type": "signing_certificate",
            "values": [tsp.SigningCertificate({"certs": [{"cert_hash": hashlib.sha1(cert_der).digest()}]})],
        }),
        cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(tst_der).digest()]}),
    ])
    sig = key.sign(cms.CMSAttributes(signed_attrs.native).dump(), padding.PKCS1v15(), hashes.SHA256())
    acert = ax509.Certificate.load(cert_der)
    sd = cms.SignedData({
        "version": "v3",
        "digest_algorithms": [{"algorithm": "sha256", "parameters": None}],
        "encap_content_info": cms.EncapsulatedContentInfo({
            "content_type": "1.2.840.113549.1.9.16.1.4",
            "content": cms.ParsableOctetString(tst_der),
        }),
        "certificates": [cms.CertificateChoices({"certificate": acert})],
        "signer_infos": [{
            "version": "v1",
            "sid": {"issuer_and_serial_number": {"issuer": acert.issuer, "serial_number": acert.serial_number}},
            "digest_algorithm": {"algorithm": "sha256", "parameters": None},
            "signed_attrs": signed_attrs,
            "signature_algorithm": {"algorithm": "sha256_rsa", "parameters": None},
            "signature": sig,
        }],
    })
    resp = tsp.TimeStampResp({
        "status": {"status": "granted"},
        "time_stamp_token": {"content_type": "signed_data", "content": sd},
    })
    return resp.dump(), cert_pem


def test_cryptographic_drand_and_rfc3161_verifiers() -> None:
    sk = 987654321
    pk_pt = bls12.multiply(bls12.G2, sk)
    c2 = compress_G2(pk_pt)
    pk_hex = (c2[0].to_bytes(48, "big") + c2[1].to_bytes(48, "big")).hex()
    round_no = 42
    msg = hashlib.sha256(u64(round_no)).digest()
    sig_pt = bls12.multiply(hash_to_G1(msg, DRAND_QUICKNET_DST, hashlib.sha256), sk)
    sig_hex = compress_G1(sig_pt).to_bytes(48, "big").hex()
    rand_hex = hashlib.sha256(bytes.fromhex(sig_hex)).hexdigest()

    beacon = DrandHttpBeacon(
        "https://api.drand.sh", "ab" * 32,
        public_key_hex=pk_hex, scheme="drand-quicknet",
        transport=lambda _u: {"round": round_no, "randomness": rand_hex, "signature": sig_hex},
    )
    reading = beacon.lookup(round_no)
    assert reading.cryptographically_verified is True

    bad_round = verify_drand_round(round_no + 1, rand_hex, sig_hex, public_key_hex=pk_hex)
    assert not bad_round.valid
    pop_pk = G2ProofOfPossession.SkToPk(sk).hex()
    pop_sig = G2ProofOfPossession.Sign(sk, hashlib.sha256(u64(9)).digest()).hex()
    assert verify_drand_round(
        9, hashlib.sha256(bytes.fromhex(pop_sig)).hexdigest(), pop_sig,
        public_key_hex=pop_pk, scheme="bls12381-g2-pop",
    ).valid

    digest = hashlib.sha256(b"chain-root-payload").digest()
    fixed_now = datetime.datetime.now(datetime.UTC)
    stale_resp_der, pem = _make_tsa_resp(digest, eku_timestamp=True, now=fixed_now, nonce=12345)

    def _mock_tsa(_u: str, req_der: bytes) -> bytes:
        req = tsp.TimeStampReq.load(req_der)
        req_nonce = int(req["nonce"].native)
        signed_attrs = cms.CMSAttributes([
            cms.CMSAttribute({"type": "content_type", "values": ["1.2.840.113549.1.9.16.1.4"]}),
            cms.CMSAttribute({
                "type": "signing_certificate",
                "values": [tsp.SigningCertificate({"certs": [{"cert_hash": hashlib.sha1(x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)).digest()}]})],
            }),
            cms.CMSAttribute({"type": "message_digest", "values": [b""]}),
        ])
        del signed_attrs
        # Use same keypair? Wait: generate fresh self-contained pair inside mock with matching cert_pem
        return _make_tsa_resp(digest, eku_timestamp=True, now=fixed_now, nonce=req_nonce)[0]

    resp_holder: dict[str, bytes] = {}

    def _paired_tsa(_u: str, req_der: bytes) -> bytes:
        req = tsp.TimeStampReq.load(req_der)
        r_der, c_pem = _make_tsa_resp(digest, eku_timestamp=True, now=fixed_now, nonce=int(req["nonce"].native))
        resp_holder["pem"] = c_pem
        return r_der

    # Test with explicit echoed nonce against dynamically signed pair and fixed-key replay rejection
    r_init, pem_init = _make_tsa_resp(digest, eku_timestamp=True, now=fixed_now, nonce=987)
    assert verify_rfc3161_tst(r_init, digest, trusted_cert_pem=pem_init, expected_nonce=987).valid
    assert not verify_rfc3161_tst(r_init, digest, trusted_cert_pem=pem_init, expected_nonce=999).valid
    replay_client = RFC3161Client(
        "https://tsa.example.org", trusted_cert_pem=pem,
        transport=lambda _u, _d: stale_resp_der,
    )
    with pytest.raises(ValueError, match="nonce"):
        replay_client.submit_digest_sha256(digest)

    # Generate reusable test TSA key/cert and echo request nonce cleanly
    tsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tsa_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Echo TSA")])
    tsa_cert = (
        x509.CertificateBuilder()
        .subject_name(tsa_name).issuer_name(tsa_name).public_key(tsa_key.public_key())
        .serial_number(101)
        .not_valid_before(fixed_now - datetime.timedelta(days=1))
        .not_valid_after(fixed_now + datetime.timedelta(days=30))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(tsa_key, hashes.SHA256())
    )
    tsa_pem = tsa_cert.public_bytes(serialization.Encoding.PEM)
    tsa_der = tsa_cert.public_bytes(serialization.Encoding.DER)

    def _echo_transport(_u: str, req_der: bytes) -> bytes:
        req_n = int(tsp.TimeStampReq.load(req_der)["nonce"].native)
        ti = tsp.TSTInfo({
            "version": 1, "policy": "1.2.3.4",
            "message_imprint": {"hash_algorithm": {"algorithm": "sha256", "parameters": None}, "hashed_message": digest},
            "serial_number": 78, "gen_time": fixed_now.replace(microsecond=0), "nonce": req_n,
        })
        ti_der = ti.dump()
        sa = cms.CMSAttributes([
            cms.CMSAttribute({"type": "content_type", "values": ["1.2.840.113549.1.9.16.1.4"]}),
            cms.CMSAttribute({"type": "signing_certificate", "values": [tsp.SigningCertificate({"certs": [{"cert_hash": hashlib.sha1(tsa_der).digest()}]})]}),
            cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(ti_der).digest()]}),
        ])
        sbytes = tsa_key.sign(cms.CMSAttributes(sa.native).dump(), padding.PKCS1v15(), hashes.SHA256())
        ac = ax509.Certificate.load(tsa_der)
        sd_obj = cms.SignedData({
            "version": "v3", "digest_algorithms": [{"algorithm": "sha256", "parameters": None}],
            "encap_content_info": cms.EncapsulatedContentInfo({"content_type": "1.2.840.113549.1.9.16.1.4", "content": cms.ParsableOctetString(ti_der)}),
            "certificates": [cms.CertificateChoices({"certificate": ac})],
            "signer_infos": [{
                "version": "v1",
                "sid": {"issuer_and_serial_number": {"issuer": ac.issuer, "serial_number": ac.serial_number}},
                "digest_algorithm": {"algorithm": "sha256", "parameters": None},
                "signed_attrs": sa,
                "signature_algorithm": {"algorithm": "sha256_rsa", "parameters": None},
                "signature": sbytes,
            }],
        })
        return tsp.TimeStampResp({"status": {"status": "granted"}, "time_stamp_token": {"content_type": "signed_data", "content": sd_obj}}).dump()

    client = RFC3161Client("https://tsa.example.org", trusted_cert_pem=tsa_pem, transport=_echo_transport)
    att = client.submit_digest_sha256(digest)
    assert att.externally_verified is True
    assert not verify_rfc3161_tst(stale_resp_der, hashlib.sha256(b"other").digest(), trusted_cert_pem=pem).valid
    bad_eku_der, bad_pem = _make_tsa_resp(digest, eku_timestamp=False)
    assert not verify_rfc3161_tst(bad_eku_der, digest, trusted_cert_pem=bad_pem).valid


def test_15_family_generator_and_a4_stats_harness(tmp_path: Path) -> None:
    seed = hashlib.sha256(b"season-seed").digest()
    for idx, fam in enumerate(ALL_FAMILIES):
        pub, hid = derive_canonical_task(seed, fam, idx)
        assert pub["family_id"] == fam and hid["family_id"] == fam
        assert "instruction" in pub
    pub_f, hid_f = derive_canonical_task(seed, "L3", 0, l3_feasible=True)
    pub_i, hid_i = derive_canonical_task(seed, "L3", 1, l3_feasible=False)
    assert pub_f["pair_id"] == pub_i["pair_id"]
    assert hid_f["feasible"] is True and hid_i["feasible"] is False

    # Statistical sanity & blinded A4 package checks
    assert wilson_ci(6, 60) == (0.046643, 0.201495)
    assert wilson_ci(0, 180) == (0.0, 0.020895)
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert exact_mcnemar_pvalue(6, 0) == pytest.approx(2 * (0.5 ** 6), abs=1e-7)

    left = np.full((32, 32, 3), 100, dtype=np.uint8)
    right = np.full((32, 32, 3), 105, dtype=np.uint8)
    pkg = export_blinded_trial_frames(tmp_path, "opaque-trial-01", "Place 3 tokens.", [left, left], [right, right])
    assert (tmp_path / "opaque-trial-01" / "cam_left_00.png").is_file()

    def _mock_fail_s4(prompt, imgs):
        return '{"verdict":"PASS","reason":"looks ok"}', 0.01

    def _dual_pass(records_list):
        return analyze_a4_results(records_list, bootstrap_n=200)

    records_agreed_clean = []
    for i in range(40):
        stratum = ("S1", "S2", "S3", "S4")[i // 10]
        gt = 1 if stratum == "S1" else 0
        # 2/10 S4 false passes by single model (20% -> stop-use); 0/10 false passes & 9/10 agreement in dual!
        astra_fails_this = stratum == "S4" and (i % 10 == 0)
        astra_fn = _mock_fail_s4 if (stratum == "S4" and (i % 10 in {0, 1})) else (lambda p, im, gt=gt: ('{"verdict":"PASS"}' if gt else '{"verdict":"FAIL"}', 0.01))
        r_astra = score_trial_robodojo_astra(pkg, runner=astra_fn)
        r_dual = score_trial_datacenterbench_dual(
            pkg,
            astra_runner=_mock_fail_s4 if astra_fails_this else (lambda p, im, gt=gt: ('{"verdict":"PASS"}' if gt else '{"verdict":"FAIL"}', 0.01)),
            claude_runner=lambda p, im, gt=gt: ('{"verdict":"PASS"}' if gt else '{"verdict":"FAIL"}', 0.01),
        )
        records_agreed_clean.append({
            "stratum": stratum,
            "family_id": ("E1", "E2", "E3", "H1")[i % 4],
            "ground_truth": gt,
            "robodojo_astra": r_astra,
            "datacenterbench_dual": r_dual,
        })
    summary = _dual_pass(records_agreed_clean)
    assert summary["judges"]["robodojo_astra"]["stop_use_triggered"] is True
    assert summary["judges"]["datacenterbench_dual"]["overall_fpr"] == 0.0
    assert summary["judges"]["datacenterbench_dual"]["stop_use_triggered"] is False
