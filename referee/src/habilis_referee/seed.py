"""Versioned seed commitments and NFC length-prefixed trial domains."""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Any

from .beacon import (
    BeaconReading,
    RandomnessBeacon,
    StubBeacon,
    u64,
    utc_now,
    verify_stub_beacon,
)


def length_prefixed(value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise ValueError("length-prefixed value must be bytes")
    return u64(len(value)) + value


_len_prefixed = length_prefixed


def generate_secret() -> tuple[bytes, bytes]:
    return secrets.token_bytes(32), secrets.token_bytes(16)


def commit(secret: bytes, nonce: bytes) -> str:
    if len(secret) != 32 or len(nonce) != 16:
        raise ValueError("secret and nonce must contain 32 and 16 bytes")
    return hashlib.sha256(
        b"habilis-seed-commit-v0.2" + length_prefixed(secret) + length_prefixed(nonce)
    ).hexdigest()


def commit_v1(secret: bytes, nonce: bytes) -> str:
    if len(secret) != 32 or len(nonce) != 16:
        raise ValueError("secret and nonce must contain 32 and 16 bytes")
    return hashlib.sha256(
        b"habilis-seed-commit-v1.0" + length_prefixed(secret) + length_prefixed(nonce)
    ).hexdigest()


def derive_run_seed(secret: bytes, submitter: bytes, beacon_value: bytes) -> bytes:
    if len(secret) != 32 or len(beacon_value) != 32:
        raise ValueError("secret and beacon must contain 32 bytes")
    return hashlib.sha256(
        b"habilis-run-seed-v0.2" + length_prefixed(secret)
        + length_prefixed(submitter) + length_prefixed(beacon_value)
    ).digest()


def derive_run_seed_v1(secret: bytes, submitter: bytes, beacon_value: bytes) -> bytes:
    if len(secret) != 32 or len(beacon_value) != 32:
        raise ValueError("secret and beacon must contain 32 bytes")
    return hashlib.sha256(
        b"habilis-run-seed-v1.0" + length_prefixed(secret)
        + length_prefixed(submitter) + length_prefixed(beacon_value)
    ).digest()


def derive_eval_seed(run_seed: bytes) -> int:
    if len(run_seed) != 32:
        raise ValueError("run seed must contain 32 bytes")
    return int.from_bytes(run_seed[:4], "big") & 0x7FFFFFFF


derive_eval_seed_v1 = derive_eval_seed


def derive_instance_seed(run_seed: bytes, family_id: str, trial_index: int) -> bytes:
    if len(run_seed) != 32 or not isinstance(family_id, str) or not family_id:
        raise ValueError("invalid instance seed input")
    family = unicodedata.normalize("NFC", family_id).encode("utf-8")
    return hashlib.sha256(
        b"habilis-trial-seed-v0.2" + run_seed + _len_prefixed(family) + u64(trial_index)
    ).digest()


def derive_instance_seed_v1(run_seed: bytes, family_id: str, trial_index: int) -> bytes:
    if len(run_seed) != 32 or not isinstance(family_id, str) or not family_id:
        raise ValueError("invalid instance seed input")
    family = unicodedata.normalize("NFC", family_id).encode("utf-8")
    return hashlib.sha256(
        b"habilis-trial-seed-v1.0" + run_seed + _len_prefixed(family) + u64(trial_index)
    ).digest()


def decode_hex(value: str, *, length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise ValueError("hex value must be a string")
    decoded = bytes.fromhex(value)
    if decoded.hex() != value:
        raise ValueError("hex value must use canonical lowercase notation")
    if length is not None and len(decoded) != length:
        raise ValueError(f"hex value must encode {length} bytes")
    return decoded


@dataclass(frozen=True)
class SealedSeed:
    secret: bytes
    nonce: bytes
    submitter: bytes
    beacon: StubBeacon | BeaconReading

    @property
    def commitment(self) -> str:
        return commit(self.secret, self.nonce)

    @property
    def run_seed(self) -> bytes:
        return derive_run_seed(
            self.secret, self.submitter, decode_hex(self.beacon.value_hex, length=32)
        )

    @property
    def eval_seed(self) -> int:
        return derive_eval_seed(self.run_seed)

    def public_values(self) -> dict[str, Any]:
        return {
            "commitment_C": self.commitment,
            "submitter_N_hex": self.submitter.hex(),
            "beacon": self.beacon.to_dict(),
        }

    def reveal(self) -> dict[str, Any]:
        return {
            **self.public_values(),
            "S_hex": self.secret.hex(), "nonce_hex": self.nonce.hex(),
            "derived_R_hex": self.run_seed.hex(), "eval_seed": self.eval_seed,
        }


@dataclass(frozen=True)
class SealedSeedV1:
    """Protocol v1.0 seed seal using versioned habilis-*-v1.0 domain separators."""

    secret: bytes
    nonce: bytes
    submitter: bytes
    beacon: StubBeacon | BeaconReading

    @property
    def commitment(self) -> str:
        return commit_v1(self.secret, self.nonce)

    @property
    def run_seed(self) -> bytes:
        return derive_run_seed_v1(
            self.secret, self.submitter, decode_hex(self.beacon.value_hex, length=32)
        )

    @property
    def eval_seed(self) -> int:
        return derive_eval_seed_v1(self.run_seed)

    def public_values(self) -> dict[str, Any]:
        return {
            "seed_protocol_version": "v1.0",
            "commitment_C": self.commitment,
            "submitter_N_hex": self.submitter.hex(),
            "beacon": self.beacon.to_dict(),
        }

    def reveal(self) -> dict[str, Any]:
        return {
            **self.public_values(),
            "S_hex": self.secret.hex(),
            "nonce_hex": self.nonce.hex(),
            "derived_R_hex": self.run_seed.hex(),
            "eval_seed": self.eval_seed,
        }
