"""Isolated evidence attacks for both proof commands."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

from .certificate import generate_or_load_private_key, sign_certificate, write_public_key
from .manifest import bundle_path, parse_json, read_json, write_json

ATTACK_REASONS = {
    "frame_byte_flip": "file_sha256",
    "drop_trial": "missing_manifest",
    "reorder_trials": "prev_manifest_hash",
    "swap_seed": "eval_seed",
}

INSTRUMENT_ATTACK_REASONS = {
    **ATTACK_REASONS,
    "scale_frame_byte_flip": "file_sha256",
    "overhead_drift_tamper": "file_sha256",
    "inject_empty_dir": "inventory",
    "rogue_key_cli_verify": "dsse_signature",
}


def alter_bundle(root: Path, attack: str) -> str:
    if attack not in INSTRUMENT_ATTACK_REASONS:
        raise ValueError(f"unknown tamper test: {attack}")
    if attack == "inject_empty_dir":
        (root / "injected_empty_dir").mkdir()
        return "injected_empty_dir"
    if attack == "rogue_key_cli_verify":
        path = root / "certificate.json"
        envelope = read_json(path, canonical=True)
        payload = parse_json(base64.b64decode(envelope["payload"]), canonical=True)
        key = generate_or_load_private_key()
        write_public_key(root / "public_key.pem", key.public_key())
        write_json(path, sign_certificate(payload, key))
        return "certificate.json"
    if attack == "drop_trial":
        relative = "manifests/trial_0000.json"
        bundle_path(root, relative).unlink()
        return relative
    if attack == "reorder_trials":
        first = root / "manifests/trial_0000.json"
        second = root / "manifests/trial_0001.json"
        first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
        first.write_bytes(second_bytes)
        second.write_bytes(first_bytes)
        return "manifests/trial_0000.json"
    if attack in {"frame_byte_flip", "scale_frame_byte_flip", "overhead_drift_tamper"}:
        trial = read_json(root / "manifests/trial_0000.json", canonical=True)
        if attack == "overhead_drift_tamper":
            relative = trial["overhead_path"]
            path = bundle_path(root, relative)
            overhead = read_json(path, canonical=True)
            overhead["frames"][-1]["bezel_fiducial_drift_mm"] = 10.0
            write_json(path, overhead)
        else:
            relative = trial["frame_paths"][0] if attack == "frame_byte_flip" else trial["scale_path"]
            path = bundle_path(root, relative)
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
        return relative
    close = read_json(root / "manifests/session_close.json", canonical=True)
    relative = close["eval_log_path"]
    path = bundle_path(root, relative)
    log = read_json(path)
    log["eval"]["seed"] = (log["eval"]["seed"] + 1) & 0x7FFFFFFF
    write_json(path, log)
    return relative


def copy_and_tamper(source: Path, destination: Path, attack: str) -> str:
    shutil.copytree(source, destination)
    return alter_bundle(destination, attack)
