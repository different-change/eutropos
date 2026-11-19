"""Ed25519 DSSE envelopes with strict canonical Base64."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .manifest import canonical_json, parse_json

PAYLOAD_TYPE = "application/vnd.habilis.referee-certificate+json"
CERTIFICATE_VERSION = "habilis-referee-certificate-v0.2"
CERTIFICATE_VERSION_V1 = "habilis-referee-certificate-v1.0"


def pae(payload_type: str, payload: bytes) -> bytes:
    kind = payload_type.encode("ascii")
    return (
        b"DSSEv1 " + str(len(kind)).encode("ascii") + b" " + kind
        + b" " + str(len(payload)).encode("ascii") + b" " + payload
    )


def public_key_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def key_id(key: Ed25519PublicKey) -> str:
    return hashlib.sha256(public_key_bytes(key)).hexdigest()[:16]


def generate_or_load_private_key(
    path: str | Path | Ed25519PrivateKey | None = None,
) -> Ed25519PrivateKey:
    if isinstance(path, Ed25519PrivateKey):
        return path
    if path is None:
        return Ed25519PrivateKey.generate()
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key must be Ed25519")
    return key


def load_public_key(
    value: str | Path | bytes | Ed25519PublicKey,
) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str) and value.startswith("-----BEGIN PUBLIC KEY-----"):
        data = value.encode("ascii")
    else:
        data = Path(value).read_bytes()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key must be Ed25519")
    return key


def write_public_key(path: Path, key: Ed25519PublicKey) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))


def strict_b64(token: str) -> bytes:
    if not isinstance(token, str):
        raise ValueError("Base64 token must be a string")
    decoded = base64.b64decode(token, validate=True)
    if base64.b64encode(decoded).decode("ascii") != token:
        raise ValueError("noncanonical Base64 padding bits or spelling")
    return decoded


def sign_certificate(
    payload: dict[str, Any], private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    encoded = canonical_json(payload)
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(encoded).decode("ascii"),
        "signatures": [{
            "keyid": key_id(private_key.public_key()),
            "sig": base64.b64encode(
                private_key.sign(pae(PAYLOAD_TYPE, encoded))
            ).decode("ascii"),
        }],
    }


def verify_certificate(
    envelope: dict[str, Any], public_key: Ed25519PublicKey,
) -> dict[str, Any]:
    if not isinstance(envelope, dict) or set(envelope) != {
        "payloadType", "payload", "signatures"
    }:
        raise ValueError("invalid DSSE envelope fields")
    if envelope["payloadType"] != PAYLOAD_TYPE:
        raise ValueError("unexpected DSSE payload type")
    payload_bytes = strict_b64(envelope["payload"])
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not signatures:
        raise ValueError("DSSE signatures must be a nonempty list")
    decoded_signatures = []
    for signature in signatures:
        if not isinstance(signature, dict) or set(signature) != {"keyid", "sig"}:
            raise ValueError("invalid DSSE signature fields")
        decoded_signatures.append(strict_b64(signature["sig"]))
    if len(signatures) != 1:
        raise ValueError("v0.2 requires exactly one signature")
    if signatures[0]["keyid"] != key_id(public_key):
        raise ValueError("DSSE key ID differs from the supplied public key")
    public_key.verify(decoded_signatures[0], pae(PAYLOAD_TYPE, payload_bytes))
    payload = parse_json(payload_bytes, canonical=True)
    if not isinstance(payload, dict):
        raise ValueError("certificate payload must be a JSON object")
    version = payload.get("certificate_version")
    if version == CERTIFICATE_VERSION:
        required = {
            "certificate_version", "subject", "hashes", "seed", "evidence",
            "results", "deviations_and_incidents", "operator_and_witness",
            "conflict_of_interest_statement",
        }
        if set(payload) != required:
            raise ValueError("invalid certificate payload fields")
        return payload
    if version == CERTIFICATE_VERSION_V1:
        required_v1 = {
            "certificate_version", "subject", "pareto_profile", "mask_tactile",
            "disclosure_mode", "hashes", "pre_beacon_registration_sha256",
            "seed", "evidence", "slot_summary", "results", "adjudications",
            "reference_baselines", "deviations_and_incidents",
            "operator_and_witness", "conflict_of_interest_statement",
        }
        if set(payload) != required_v1:
            raise ValueError("invalid v1.0 certificate payload fields")
        adjudications = payload["adjudications"]
        if not isinstance(adjudications, list):
            raise ValueError("adjudications must be a list")
        for adj in adjudications:
            if not isinstance(adj, dict) or not {
                "slot_id", "execution_attempt_id", "original_scores",
                "adjudicated_scores", "reason", "adjudicator_id",
            } <= set(adj):
                raise ValueError("adjudication entry missing required raw-score preservation fields")
        return payload
    raise ValueError("unsupported certificate version")
