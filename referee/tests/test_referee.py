from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from importlib.metadata import entry_points

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from inspect_robots.registry import registered, resolve

from eutropos_referee.certificate import (
    CERTIFICATE_VERSION, PAYLOAD_TYPE, pae, sign_certificate, verify_certificate,
)
from eutropos_referee.cli import main
from eutropos_referee.manifest import bundle_path, read_json, write_json
from eutropos_referee.seed import (
    StubBeacon, commit, derive_eval_seed, derive_instance_seed, derive_run_seed,
)
from eutropos_referee.sink import RefereeSink
from eutropos_referee.tamper import ATTACK_REASONS, copy_and_tamper
from eutropos_referee.verifier import verify_bundle


def test_entry_point_and_registry_factory(monkeypatch, tmp_path):
    monkeypatch.delenv("INSPECT_ROBOTS_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    assert "referee" in {entry.name for entry in entry_points(group="inspect_robots.sinks")}
    assert "referee" in registered("sink")
    assert isinstance(resolve("sink", "referee"), RefereeSink)
    assert isinstance(resolve("sink", "referee", log_dir=str(tmp_path)), RefereeSink)


def test_seed_encodings_and_domain_separation():
    secret, nonce = bytes(range(32)), bytes(range(16))
    beacon = bytes.fromhex(StubBeacon(7).value_hex)
    seed = derive_run_seed(secret, b"submitter", beacon)
    assert len(commit(secret, nonce)) == 64
    assert commit(secret, nonce) != commit(secret, bytes(reversed(nonce)))
    assert 0 <= derive_eval_seed(seed) < 2**31
    assert derive_instance_seed(seed, "family", 0) != derive_instance_seed(seed, "family", 1)
    assert derive_instance_seed(seed, "family", 0) != derive_instance_seed(seed, "other", 0)


def test_dsse_uses_standard_pae():
    key = Ed25519PrivateKey.generate()
    payload = {
        "certificate_version": CERTIFICATE_VERSION,
        "subject": {}, "hashes": {}, "seed": {}, "evidence": {}, "results": {},
        "deviations_and_incidents": [], "operator_and_witness": {},
        "conflict_of_interest_statement": "test",
    }
    envelope = sign_certificate(payload, key)
    encoded = base64.b64decode(envelope["payload"], validate=True)
    expected = (
        f"DSSEv1 {len(PAYLOAD_TYPE)} {PAYLOAD_TYPE} {len(encoded)} ".encode("ascii")
        + encoded
    )
    assert pae(PAYLOAD_TYPE, encoded) == expected
    key.public_key().verify(base64.b64decode(envelope["signatures"][0]["sig"]), expected)
    assert verify_certificate(envelope, key.public_key()) == payload


def test_full_sealed_run_and_real_frames(clean_bundle, trusted_key):
    report = verify_bundle(clean_bundle, public_key=trusted_key)
    assert report.passed, report.failures
    assert report.trusted_key_mode == "external-key"
    close = read_json(clean_bundle / "manifests/session_close.json", canonical=True)
    assert close["trial_count"] == 8
    for index in range(8):
        trial = read_json(clean_bundle / f"manifests/trial_{index:04d}.json", canonical=True)
        names = [entry["path"] for entry in trial["files"]]
        assert names == sorted(names)
        assert all("\\" not in name for name in names)
        assert trial["scores"] == {"success_at_end": 1.0}
        frame = np.load(bundle_path(clean_bundle, trial["frame_paths"][0]), allow_pickle=False)
        assert frame.shape == (32, 32, 3)
        assert frame.dtype == np.uint8


def test_bundle_is_relocatable(clean_bundle, trusted_key, tmp_path):
    destination = tmp_path / "relocated"
    shutil.copytree(clean_bundle, destination)
    report = verify_bundle(destination, public_key=trusted_key)
    assert report.passed, report.failures


@pytest.mark.parametrize("attack", list(ATTACK_REASONS))
def test_four_attacks_fail_for_exact_reason(clean_bundle, trusted_key, tmp_path, attack):
    destination = tmp_path / attack
    altered = copy_and_tamper(clean_bundle, destination, attack)
    report = verify_bundle(destination, public_key=trusted_key)
    assert not report.passed
    assert any(
        failure.startswith(ATTACK_REASONS[attack] + ":") and altered in failure
        for failure in report.failures
    ), report.failures


def test_drop_trial_and_its_files(clean_bundle, trusted_key, tmp_path):
    destination = tmp_path / "dropped"
    shutil.copytree(clean_bundle, destination)
    path = destination / "manifests/trial_0000.json"
    trial = read_json(path, canonical=True)
    for entry in trial["files"]:
        bundle_path(destination, entry["path"]).unlink()
    path.unlink()
    report = verify_bundle(destination, public_key=trusted_key)
    assert not report.passed
    assert "missing_manifest: manifests/trial_0000.json" in report.failures


@pytest.mark.parametrize(
    ("field", "reason"),
    [("S_hex", "commitment_C"), ("submitter_N_hex", "seed_preregistration"), ("beacon", "beacon")],
)
def test_reveal_substitutions_fail(clean_bundle, trusted_key, tmp_path, field, reason):
    destination = tmp_path / field
    shutil.copytree(clean_bundle, destination)
    path = destination / "seed_reveal.json"
    reveal = read_json(path, canonical=True)
    owner, key = (reveal["beacon"], "value_hex") if field == "beacon" else (reveal, field)
    value = bytearray.fromhex(owner[key])
    value[0] ^= 1
    owner[key] = value.hex()
    write_json(path, reveal)
    report = verify_bundle(destination, public_key=trusted_key)
    assert not report.passed
    assert any(failure.startswith(reason + ":") for failure in report.failures)
    assert "file_sha256: seed_reveal.json" in report.failures


def test_persisted_trial_seed_substitution(clean_bundle, trusted_key, tmp_path):
    destination = tmp_path / "seed"
    shutil.copytree(clean_bundle, destination)
    trial = read_json(destination / "manifests/trial_0000.json", canonical=True)
    path = bundle_path(destination, trial["record_path"])
    record = read_json(path)
    record["configuration"]["trial_seed"] += 1
    write_json(path, record)
    report = verify_bundle(destination, public_key=trusted_key)
    assert any(failure.startswith("record_trial_seed:") for failure in report.failures)


@pytest.mark.parametrize("relative", [
    "frames/orphan.npy", "records/orphan.txt", "actions/orphan.jsonl",
    "manifests/trial_9999.json", "unreferenced.txt",
])
def test_orphan_files_fail(clean_bundle, trusted_key, tmp_path, relative):
    destination = tmp_path / "extra"
    shutil.copytree(clean_bundle, destination)
    path = destination / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unreferenced")
    report = verify_bundle(destination, public_key=trusted_key)
    assert f"orphan_file: {relative}" in report.failures


def test_signature_substitution_fails_first(clean_bundle, trusted_key, tmp_path):
    destination = tmp_path / "signature"
    shutil.copytree(clean_bundle, destination)
    path = destination / "certificate.json"
    envelope = read_json(path, canonical=True)
    signature = bytearray(base64.b64decode(envelope["signatures"][0]["sig"]))
    signature[0] ^= 1
    envelope["signatures"][0]["sig"] = base64.b64encode(signature).decode("ascii")
    write_json(path, envelope)
    report = verify_bundle(destination, public_key=trusted_key)
    assert report.failures[0].startswith("dsse_signature:")


def test_cli_exit_codes(clean_bundle, trusted_key, tmp_path):
    command = [
        sys.executable, "-m", "eutropos_referee", "verify",
        "--evidence-dir", str(clean_bundle), "--public-key", str(trusted_key),
    ]
    valid = subprocess.run(command, capture_output=True, text=True, check=False)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    for attack in ATTACK_REASONS:
        destination = tmp_path / attack
        copy_and_tamper(clean_bundle, destination, attack)
        modified = list(command)
        modified[5] = str(destination)
        invalid = subprocess.run(modified, capture_output=True, text=True, check=False)
        assert invalid.returncode == 1, invalid.stdout + invalid.stderr


def test_single_command_proof(tmp_path, capsys):
    destination = tmp_path / "proof"
    assert main(["prove", "--out-dir", str(destination)]) == 0
    capsys.readouterr()
    report = read_json(destination / "proof_report.json", canonical=True)
    assert report["passed"] and report["clean"]["passed"]
    assert set(report["tamper_tests"]) == set(ATTACK_REASONS)
    assert all(case["detected_for_expected_reason"] for case in report["tamper_tests"].values())
    assert (destination / "trusted-referee-public.pem").is_file()
