from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eutropos_referee.certificate import generate_or_load_private_key, sign_certificate
from eutropos_referee.manifest import (
    bundle_path, file_entries, object_hash, parse_json, read_json, sha256_file, write_json,
)
from eutropos_referee.results import summarize
from eutropos_referee.runner import run_bundle, run_instruments_bundle


@pytest.fixture(scope="session")
def private_key_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("referee-key") / "private.pem"
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return path


@pytest.fixture(scope="session")
def clean_bundle(tmp_path_factory, private_key_file) -> Path:
    directory = tmp_path_factory.mktemp("a1-clean")
    return run_bundle(
        directory / "evidence", private_key=private_key_file,
        write_trusted_public_key=directory / "trusted.pem",
    )


@pytest.fixture(scope="session")
def trusted_key(clean_bundle) -> Path:
    return clean_bundle.parent / "trusted.pem"


@pytest.fixture(scope="session")
def instrument_bundle(tmp_path_factory, private_key_file) -> Path:
    directory = tmp_path_factory.mktemp("a2-clean")
    return run_instruments_bundle(
        directory / "evidence", private_key=private_key_file,
        write_trusted_public_key=directory / "trusted.pem",
    )


@pytest.fixture
def resign(private_key_file):
    def operation(root: Path) -> None:
        envelope = read_json(root / "certificate.json", canonical=True)
        payload = parse_json(base64.b64decode(envelope["payload"]), canonical=True)
        prereg = read_json(root / "preregistration.json", canonical=True)
        previous = object_hash(prereg)
        trials = []
        for index in range(payload["evidence"]["trial_count"]):
            path = root / "manifests" / f"trial_{index:04d}.json"
            trial = read_json(path, canonical=True)
            trial["files"] = file_entries(
                root, [bundle_path(root, entry["path"]) for entry in trial["files"]]
            )
            trial["prev_manifest_hash"] = previous
            write_json(path, trial)
            previous = sha256_file(path)
            trials.append(trial)
        close_path = root / "manifests/session_close.json"
        close = read_json(close_path, canonical=True)
        close["genesis_hash"] = object_hash(prereg)
        close["prev_manifest_hash"] = previous
        close["files"] = file_entries(
            root, [bundle_path(root, entry["path"]) for entry in close["files"]]
        )
        write_json(close_path, close)
        payload["evidence"]["genesis_hash"] = object_hash(prereg)
        payload["evidence"]["chain_root_hash"] = sha256_file(close_path)
        payload["results"] = summarize(trials)
        write_json(
            root / "certificate.json",
            sign_certificate(payload, generate_or_load_private_key(private_key_file)),
        )
    return operation
