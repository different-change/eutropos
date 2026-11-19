from __future__ import annotations

import base64
import hashlib
import json
import shutil
import unicodedata

import numpy as np
import pytest

from eutropos_referee.certificate import strict_b64
from eutropos_referee.cli import main
from eutropos_referee.manifest import (
    bundle_path, canonical_json, parse_json, read_json, write_json,
)
from eutropos_referee.runner import run_bundle
from eutropos_referee.seed import derive_instance_seed, u64
from eutropos_referee.verifier import _native_path_matches, verify_bundle


def copy_bundle(source, tmp_path):
    destination = tmp_path / "copy"
    shutil.copytree(source, destination)
    return destination


def test_noncanonical_cert(clean_bundle, trusted_key, tmp_path):
    root = copy_bundle(clean_bundle, tmp_path)
    path = root / "certificate.json"
    path.write_text(json.dumps(read_json(path), indent=2), encoding="utf-8")
    report = verify_bundle(root, public_key=trusted_key)
    assert not report.passed
    assert report.failures[0].startswith("dsse_signature:")


def _padding_mutation(token):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    assert token.endswith("=")
    position = len(token.rstrip("=")) - 1
    index = alphabet.index(token[position])
    return token[:position] + alphabet[index | 1] + token[position + 1:]


def test_b64_padding_malleability(clean_bundle, trusted_key, tmp_path):
    root = copy_bundle(clean_bundle, tmp_path)
    path = root / "certificate.json"
    envelope = read_json(path, canonical=True)
    original = envelope["signatures"][0]["sig"]
    changed = _padding_mutation(original)
    assert base64.b64decode(changed, validate=True) == base64.b64decode(original)
    envelope["signatures"][0]["sig"] = changed
    write_json(path, envelope)
    report = verify_bundle(root, public_key=trusted_key)
    assert not report.passed
    assert "Base64" in report.failures[0]
    for raw in (b"a", b"ab"):
        token = base64.b64encode(raw).decode("ascii")
        with pytest.raises(ValueError, match="noncanonical Base64"):
            strict_b64(_padding_mutation(token))


def test_forged_100pct_over_noop(tmp_path, private_key_file, resign):
    key = tmp_path / "trusted.pem"
    root = run_bundle(
        tmp_path / "noop", policy="noop", private_key=private_key_file,
        write_trusted_public_key=key,
    )
    assert verify_bundle(root, public_key=key).passed
    close = read_json(root / "manifests/session_close.json", canonical=True)
    log_path = root / close["eval_log_path"]
    log = read_json(log_path)
    for index in range(8):
        path = root / f"manifests/trial_{index:04d}.json"
        trial = read_json(path, canonical=True)
        record = read_json(root / trial["record_path"])
        assert record["termination"]["reason"] == "max_steps"
        trial["scores"] = {"success_at_end": 1.0}
        write_json(path, trial)
    for sample in log["samples"]:
        sample["epochs"] = [{"success_at_end": 1.0} for _ in sample["epochs"]]
        sample["reduced"] = {"success_at_end": 1.0}
    log["results"]["metrics"] = {"success_at_end": 1.0}
    write_json(log_path, log)
    resign(root)
    report = verify_bundle(root, public_key=key)
    assert not report.passed
    assert any(failure.startswith("recomputed_scores:") for failure in report.failures)
    assert any(failure.startswith("certificate_results:") for failure in report.failures)
    assert any(failure.startswith("log_results:") for failure in report.failures)


def test_benign_nested_epoch_collision_passes(clean_bundle, trusted_key, tmp_path, resign):
    root = copy_bundle(clean_bundle, tmp_path)
    trial = read_json(root / "manifests/trial_0000.json", canonical=True)
    path = root / trial["record_path"]
    record = read_json(path)
    record["configuration"]["policy"]["config"]["epoch"] = 99
    write_json(path, record)
    resign(root)
    report = verify_bundle(root, public_key=trusted_key)
    assert report.passed, report.failures


def test_top_level_record_seed_tamper_fails(clean_bundle, trusted_key, tmp_path, resign):
    root = copy_bundle(clean_bundle, tmp_path)
    trial = read_json(root / "manifests/trial_0000.json", canonical=True)
    path = root / trial["record_path"]
    record = read_json(path)
    record["seed"] = 123456789
    record["events"][0]["data"]["seed"] = 123456789
    write_json(path, record)
    resign(root)
    report = verify_bundle(root, public_key=trusted_key)
    assert any(failure.startswith("record_seed:") for failure in report.failures)
    assert any(failure.startswith("record_event_seed:") for failure in report.failures)


def test_empty_dir_injection_fails(clean_bundle, trusted_key, tmp_path):
    root = copy_bundle(clean_bundle, tmp_path)
    (root / "injected_empty_dir").mkdir()
    (root / "nested" / "also_empty").mkdir(parents=True)
    report = verify_bundle(root, public_key=trusted_key)
    assert not report.passed
    failure = next(value for value in report.failures if value.startswith("inventory:"))
    assert "injected_empty_dir" in failure and "nested/also_empty" in failure


def test_cli_default_verify_fails_without_key(clean_bundle, capsys):
    assert main(["verify", "--evidence-dir", str(clean_bundle)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["passed"]
    assert report["failures"][0].startswith("trusted_public_key:")


def test_cli_trust_bundled_key_flag_works(clean_bundle, capsys):
    assert main([
        "verify", "--evidence-dir", str(clean_bundle), "--trust-bundled-key",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"]
    assert report["trusted_key_mode"] == "self-asserted-bundled-key"


@pytest.mark.parametrize("value", [-0.0, {"nested": [-0.0]}])
def test_neg_zero_rejected(value):
    with pytest.raises(ValueError, match="negative zero not allowed"):
        canonical_json(value)
    with pytest.raises(ValueError, match="negative zero not allowed"):
        parse_json(json.dumps(value).encode(), canonical=True)


def test_canonical_decoded_numbers_and_duplicate_keys():
    for raw in (b'{"x":1e999}', b'{"x":NaN}', b'{"x":1,"x":2}'):
        with pytest.raises(ValueError):
            parse_json(raw, canonical=True)


def test_unicode_nfc_length_prefixed_seed():
    run_seed = bytes(range(32))
    composed, decomposed = "\u00e9", "e\u0301"
    family = unicodedata.normalize("NFC", decomposed).encode("utf-8")
    expected = hashlib.sha256(
        b"eutropos-trial-seed-v0.2" + run_seed
        + u64(len(family)) + family + u64(7)
    ).digest()
    assert derive_instance_seed(run_seed, composed, 7) == expected
    assert derive_instance_seed(run_seed, decomposed, 7) == expected


def test_relative_prefix_native_path_rejected():
    expected = "frames/stamp"
    assert _native_path_matches(expected, expected, absolute_allowed=True)
    assert _native_path_matches("C:\\bundle\\frames\\stamp", expected, absolute_allowed=True)
    assert _native_path_matches("/bundle/frames/stamp", expected, absolute_allowed=True)
    for candidate in ("evil/frames/stamp", "C:evil/frames/stamp", "../frames/stamp"):
        assert not _native_path_matches(candidate, expected, absolute_allowed=True)
    assert not _native_path_matches("/bundle/frames/stamp", expected, absolute_allowed=False)


@pytest.mark.parametrize("attack", ["bad_npy", "bad_actions", "bad_chunks", "step_count"])
def test_resigned_invalid_artifacts_fail(clean_bundle, trusted_key, tmp_path, resign, attack):
    root = copy_bundle(clean_bundle, tmp_path)
    trial = read_json(root / "manifests/trial_0000.json", canonical=True)
    if attack == "bad_npy":
        with bundle_path(root, trial["frame_paths"][0]).open("wb") as stream:
            np.save(stream, np.zeros((32, 32), dtype=np.float32), allow_pickle=False)
    elif attack in {"bad_actions", "bad_chunks"}:
        key = "actions_path" if attack == "bad_actions" else "chunks_path"
        path = root / trial[key]
        lines = path.read_bytes().splitlines()
        row = parse_json(lines[1])
        row["t"] = 999999
        lines[1] = canonical_json(row)
        path.write_bytes(b"\n".join(lines) + b"\n")
    else:
        path = root / trial["record_path"]
        record = read_json(path)
        record["steps"] += 1
        write_json(path, record)
    resign(root)
    report = verify_bundle(root, public_key=trusted_key)
    assert not report.passed
    assert any(failure.startswith("artifact_parsing:") for failure in report.failures)
