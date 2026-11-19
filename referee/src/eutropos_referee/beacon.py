"""Local stubs, drand BLS12-381 verification, and RFC 3161 CMS verification."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import asn1crypto.cms as cms
import asn1crypto.tsp as tsp
import py_ecc.optimized_bls12_381 as bls12
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from py_ecc.bls import G2ProofOfPossession
from py_ecc.bls.g2_primitives import subgroup_check
from py_ecc.bls.hash_to_curve import hash_to_G1
from py_ecc.bls.point_compression import decompress_G1, decompress_G2

DRAND_QUICKNET_DST = b"BLS_SIG_BLS12381G1_XMD:SHA-256_SSWU_RO_NUL_"
DRAND_QUICKNET_CHAIN_HASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
DRAND_QUICKNET_GENESIS_TIME = 1692803367
DRAND_QUICKNET_PERIOD_S = 3
DRAND_QUICKNET_PUBKEY_HEX = (
    "83cf0f2896adee7eb8b5f01fcad3912212c437e0073e911fb90022d3e760183c"
    "8c4b450b6a0a6c3ac6a5776a2d1064510d1fec758c921cc22b0e17e63aaf4bcb"
    "5ed66304de9cf809bd274ca73bab4af5a6e9c76a4bc09e76eae8991ef5ece45a"
)
DRAND_QUICKNET_URLS = ("https://api.drand.sh", "https://drand.cloudflare.com")
FREETSA_URL = "https://freetsa.org/tsr"
FREETSA_CACERT_URL = "https://freetsa.org/files/cacert.pem"
FREETSA_ROOT_SHA256 = "a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc"
PINNED_TSA_ROOT_SHA256S = frozenset({FREETSA_ROOT_SHA256})


def drand_quicknet_round_time_utc(round_number: int) -> datetime:
    """Return exact UTC publication timestamp for a quicknet round (genesis=1692803367, period=3s)."""
    if type(round_number) is not int or round_number < 1:
        raise ValueError("positive integer quicknet round required")
    epoch_s = DRAND_QUICKNET_GENESIS_TIME + (round_number - 1) * DRAND_QUICKNET_PERIOD_S
    return datetime.fromtimestamp(epoch_s, tz=UTC)
_HASH_OIDS = {
    "sha256": (hashes.SHA256, hashlib.sha256),
    "sha384": (hashes.SHA384, hashlib.sha384),
    "sha512": (hashes.SHA512, hashlib.sha512),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def u64(value: int) -> bytes:
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError("value must be an unsigned 64-bit integer")
    return value.to_bytes(8, "big")


class RandomnessBeacon(Protocol):
    provider: str

    def lookup(self, round_number: int) -> BeaconReading | StubBeacon:
        ...


@dataclass(frozen=True)
class BeaconReading:
    provider: str
    round_number: int
    fetched_at: str
    value_hex: str
    signature_hex: str
    chain_hash: str
    cryptographically_verified: bool = False
    scheme: str = "drand-quicknet"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DrandVerificationResult:
    valid: bool
    reason: str
    scheme: str
    round_number: int


@dataclass(frozen=True)
class TimestampVerificationResult:
    valid: bool
    reason: str
    gen_time_utc: str | None
    digest_sha256: str


@dataclass(frozen=True)
class StubBeacon:
    round_number: int = 1
    fetched_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if type(self.round_number) is not int or not 1 <= self.round_number < 2**64:
            raise ValueError("beacon round must be a positive u64")

    @property
    def provider(self) -> str:
        return "stub-sha256-v0"

    @property
    def value_hex(self) -> str:
        return hashlib.sha256(
            b"eutropos-stub-beacon-v0" + u64(self.round_number)
        ).hexdigest()

    @classmethod
    def lookup(cls, round_number: int) -> StubBeacon:
        return cls(round_number=round_number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "round_number": self.round_number,
            "fetched_at": self.fetched_at,
            "value_hex": self.value_hex,
        }


def verify_stub_beacon(reading: dict[str, Any]) -> bool:
    try:
        if set(reading) != {"provider", "round_number", "fetched_at", "value_hex"}:
            return False
        when = datetime.fromisoformat(reading["fetched_at"].replace("Z", "+00:00"))
        return (
            when.utcoffset() is not None
            and when.utcoffset().total_seconds() == 0
            and reading == StubBeacon(
                reading["round_number"], reading["fetched_at"]
            ).to_dict()
        )
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False


def _decode_lower_hex(token: str, expected_len: int | None = None) -> bytes:
    if not isinstance(token, str):
        raise ValueError("hex field must be a string")
    raw = bytes.fromhex(token)
    if raw.hex() != token:
        raise ValueError("hex field must use canonical lowercase notation")
    if expected_len is not None and len(raw) != expected_len:
        raise ValueError(f"hex field must encode {expected_len} bytes")
    return raw


def verify_drand_round(
    round_number: int,
    randomness_hex: str,
    signature_hex: str,
    *,
    public_key_hex: str,
    scheme: str = "drand-quicknet",
    prev_signature_hex: str | None = None,
) -> DrandVerificationResult:
    """Verify a drand BLS12-381 signature and derived randomness offline."""
    if type(round_number) is not int or not 1 <= round_number < 2**64:
        return DrandVerificationResult(False, "invalid round_number", scheme, -1)
    try:
        rand_bytes = _decode_lower_hex(randomness_hex, 32)
        sig_bytes = _decode_lower_hex(signature_hex)
        pk_bytes = _decode_lower_hex(public_key_hex)
        if hashlib.sha256(sig_bytes).digest() != rand_bytes:
            return DrandVerificationResult(
                False, "randomness != sha256(signature)", scheme, round_number
            )
        prev = _decode_lower_hex(prev_signature_hex) if prev_signature_hex else b""
        msg = hashlib.sha256(prev + u64(round_number)).digest()

        if scheme == "drand-quicknet":
            if len(pk_bytes) != 96 or len(sig_bytes) != 48:
                return DrandVerificationResult(
                    False, "quicknet expects 96B G2 key and 48B G1 signature", scheme, round_number
                )
            pk_pt = decompress_G2(
                (int.from_bytes(pk_bytes[:48], "big"), int.from_bytes(pk_bytes[48:], "big"))
            )
            sig_pt = decompress_G1(int.from_bytes(sig_bytes, "big"))
            if bls12.is_inf(pk_pt) or bls12.is_inf(sig_pt):
                return DrandVerificationResult(False, "point at infinity rejected", scheme, round_number)
            if not subgroup_check(pk_pt) or not subgroup_check(sig_pt):
                return DrandVerificationResult(False, "BLS subgroup check failed", scheme, round_number)
            h_pt = hash_to_G1(msg, DRAND_QUICKNET_DST, hashlib.sha256)
            paired = bls12.final_exponentiate(
                bls12.pairing(pk_pt, h_pt, final_exponentiate=False)
                * bls12.pairing(bls12.neg(bls12.G2), sig_pt, final_exponentiate=False)
            )
            if paired != bls12.FQ12.one():
                return DrandVerificationResult(False, "BLS pairing check failed", scheme, round_number)
            return DrandVerificationResult(True, "ok", scheme, round_number)

        if scheme == "bls12381-g2-pop":
            if len(pk_bytes) != 48 or len(sig_bytes) != 96:
                return DrandVerificationResult(
                    False, "g2-pop expects 48B G1 key and 96B G2 signature", scheme, round_number
                )
            if not G2ProofOfPossession.Verify(pk_bytes, msg, sig_bytes):
                return DrandVerificationResult(False, "BLS G2PoP verification failed", scheme, round_number)
            return DrandVerificationResult(True, "ok", scheme, round_number)

        return DrandVerificationResult(False, f"unsupported scheme: {scheme}", scheme, round_number)
    except (ValueError, AssertionError, ArithmeticError, TypeError) as exc:
        return DrandVerificationResult(False, f"BLS parse/verify error: {exc}", scheme, round_number)


def _https(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or not parts.hostname
        or parts.username or parts.password or parts.fragment or parts.query
    ):
        raise ValueError("an HTTPS service URL without credentials is required")
    return url.rstrip("/")


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=20) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("beacon response exceeds one MiB")
    from .manifest import parse_json
    value = parse_json(data)
    if not isinstance(value, dict):
        raise ValueError("beacon response must be an object")
    return value


class DrandHttpBeacon:
    provider = "drand-http-v2"

    def __init__(
        self,
        base_url: str,
        chain_hash: str,
        *,
        public_key_hex: str | None = None,
        scheme: str = "drand-quicknet",
        transport: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.base_url = _https(base_url)
        if len(chain_hash) != 64 or bytes.fromhex(chain_hash).hex() != chain_hash:
            raise ValueError("chain_hash must be 32 lowercase hex bytes")
        self.chain_hash = chain_hash
        self.public_key_hex = public_key_hex
        self.scheme = scheme
        self._transport = transport or _get_json

    def lookup(self, round_number: int) -> BeaconReading:
        if type(round_number) is not int or not 1 <= round_number < 2**64:
            raise ValueError("round must be a positive u64")
        value = self._transport(
            f"{self.base_url}/{self.chain_hash}/public/round/{round_number}"
        )
        if type(value.get("round")) is not int or value["round"] != round_number:
            raise ValueError("beacon round mismatch")
        randomness = value["randomness"]
        signature = value["signature"]
        prev_sig = value.get("previous_signature")
        raw = _decode_lower_hex(randomness, 32)
        sig = _decode_lower_hex(signature)
        if not sig or hashlib.sha256(sig).digest() != raw:
            raise ValueError("drand randomness differs from signature digest")
        verified = False
        if self.public_key_hex is not None:
            check = verify_drand_round(
                round_number,
                randomness,
                signature,
                public_key_hex=self.public_key_hex,
                scheme=self.scheme,
                prev_signature_hex=prev_sig if isinstance(prev_sig, str) else None,
            )
            if not check.valid:
                raise ValueError(check.reason)
            verified = True
        return BeaconReading(
            self.provider,
            round_number,
            utc_now(),
            randomness,
            signature,
            self.chain_hash,
            verified,
            self.scheme,
        )


@dataclass(frozen=True)
class TimestampAttestation:
    provider: str
    digest_sha256: str
    submitted_at: str
    externally_verified: bool = False
    response_b64: str | None = None
    request_b64: str | None = None
    gen_time_utc: str | None = None
    nonce: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TimestampAuthority(Protocol):
    def submit_digest_sha256(self, digest: bytes) -> TimestampAttestation:
        ...


class StubTimestampAuthority:
    def submit_digest_sha256(self, digest: bytes) -> TimestampAttestation:
        if not isinstance(digest, bytes) or len(digest) != 32:
            raise ValueError("SHA-256 digest must contain 32 bytes")
        return TimestampAttestation("local-clock", digest.hex(), utc_now())


def _der(tag: int, value: bytes) -> bytes:
    length = len(value)
    if length < 128:
        encoded_length = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
        encoded_length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + encoded_length + value


def _der_integer(value: int) -> bytes:
    if value < 0:
        raise ValueError("DER integer must be nonnegative")
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return _der(0x02, raw)


def timestamp_request(digest: bytes, nonce: int) -> bytes:
    if not isinstance(digest, bytes) or len(digest) != 32:
        raise ValueError("SHA-256 digest must contain 32 bytes")
    algorithm = _der(0x30, _der(0x06, bytes.fromhex("608648016503040201")) + b"\x05\x00")
    imprint = _der(0x30, algorithm + _der(0x04, digest))
    return _der(
        0x30, _der_integer(1) + imprint + _der_integer(nonce) + b"\x01\x01\xff"
    )


def _load_trusted_certs(trusted_cert_pem: str | Path | bytes) -> list[x509.Certificate]:
    if isinstance(trusted_cert_pem, Path):
        data = trusted_cert_pem.read_bytes()
    elif isinstance(trusted_cert_pem, str):
        data = (
            trusted_cert_pem.encode("utf-8")
            if "BEGIN CERTIFICATE" in trusted_cert_pem
            else Path(trusted_cert_pem).read_bytes()
        )
    else:
        data = trusted_cert_pem
    return x509.load_pem_x509_certificates(data)


def _verify_cert_signature(cert: x509.Certificate, issuer_pub: Any, hash_alg: Any) -> None:
    sig = cert.signature
    tbs = cert.tbs_certificate_bytes
    if isinstance(issuer_pub, rsa.RSAPublicKey):
        sig_pad = getattr(cert, "signature_algorithm_parameters", None)
        if isinstance(sig_pad, padding.AsymmetricPadding):
            issuer_pub.verify(sig, tbs, sig_pad, hash_alg)
        else:
            issuer_pub.verify(sig, tbs, padding.PKCS1v15(), hash_alg)
    elif isinstance(issuer_pub, ec.EllipticCurvePublicKey):
        issuer_pub.verify(sig, tbs, ec.ECDSA(hash_alg))
    elif isinstance(issuer_pub, ed25519.Ed25519PublicKey):
        issuer_pub.verify(sig, tbs)
    else:
        raise ValueError("unsupported issuer public key type")


def _verify_signer_bytes(
    pub: Any, signature: bytes, data: bytes, hash_cls: Any, sig_algo_name: str,
) -> None:
    hash_name = hash_cls().name
    if isinstance(pub, rsa.RSAPublicKey):
        allowed_rsa = {
            "rsassa_pkcs1v15",
            "sha256_rsa",
            "sha384_rsa",
            "sha512_rsa",
        }
        if sig_algo_name in allowed_rsa:
            if sig_algo_name.endswith("_rsa") and not sig_algo_name.startswith(hash_name):
                raise ValueError("CMS signature_algorithm digest mismatch")
            pub.verify(signature, data, padding.PKCS1v15(), hash_cls())
        else:
            raise ValueError(f"incompatible CMS signature_algorithm for RSA key: {sig_algo_name}")
    elif isinstance(pub, ec.EllipticCurvePublicKey):
        allowed_ec = {"ecdsa", "sha256_ecdsa", "sha384_ecdsa", "sha512_ecdsa"}
        if sig_algo_name not in allowed_ec:
            raise ValueError(f"incompatible CMS signature_algorithm for EC key: {sig_algo_name}")
        if sig_algo_name.endswith("_ecdsa") and not sig_algo_name.startswith(hash_name):
            raise ValueError("CMS signature_algorithm digest mismatch")
        pub.verify(signature, data, ec.ECDSA(hash_cls()))
    elif isinstance(pub, ed25519.Ed25519PublicKey):
        if sig_algo_name != "ed25519":
            raise ValueError(f"incompatible CMS signature_algorithm for Ed25519 key: {sig_algo_name}")
        pub.verify(signature, data)
    else:
        raise ValueError("unsupported TSA signer public key type")
        raise ValueError("unsupported TSA public key type")


def verify_rfc3161_tst(
    response_der: bytes,
    expected_digest_sha256: bytes,
    *,
    trusted_cert_pem: str | Path | bytes,
    expected_nonce: int | None = None,
    pinned_root_sha256s: frozenset[str] | None = None,
) -> TimestampVerificationResult:
    """Verify DER TimeStampResp CMS SignedData, EKU, messageDigest, nonce, pinned root, and imprint offline."""
    digest_hex = expected_digest_sha256.hex() if isinstance(expected_digest_sha256, bytes) else ""
    try:
        if not isinstance(response_der, bytes) or not response_der:
            raise ValueError("empty TSA DER response")
        if not isinstance(expected_digest_sha256, bytes) or len(expected_digest_sha256) != 32:
            raise ValueError("expected SHA-256 digest must contain 32 bytes")
        trusted = _load_trusted_certs(trusted_cert_pem)
        if not trusted:
            raise ValueError("trusted certificate list is empty")
        if pinned_root_sha256s is not None:
            loaded_fps = {t.fingerprint(hashes.SHA256()).hex() for t in trusted}
            if not (loaded_fps & pinned_root_sha256s):
                raise ValueError("supplied TSA roots match zero pinned root fingerprints")

        resp = tsp.TimeStampResp.load(response_der)
        status = resp["status"]["status"].native
        if status not in {"granted", "granted_with_mods"}:
            raise ValueError(f"TSA response status rejected: {status}")

        token = resp["time_stamp_token"]
        if token["content_type"].dotted != "1.2.840.113549.1.7.2":
            raise ValueError("TSA token content type is not signed_data")
        sd = token["content"]
        encap = sd["encap_content_info"]
        if encap["content_type"].dotted != "1.2.840.113549.1.9.16.1.4":
            raise ValueError("encapsulated content is not id-ct-TSTInfo")
        raw_tst = bytes(encap["content"].contents)
        tst = tsp.TSTInfo.load(raw_tst)
        if expected_nonce is not None:
            tst_nonce = tst["nonce"].native if tst["nonce"] is not None else None
            if tst_nonce != expected_nonce:
                raise ValueError("TSTInfo nonce mismatch")
        imprint = tst["message_imprint"]
        if imprint["hash_algorithm"]["algorithm"].native != "sha256":
            raise ValueError("TSTInfo hash algorithm must be sha256")
        if imprint["hashed_message"].native != expected_digest_sha256:
            raise ValueError("TSTInfo message_imprint digest mismatch")

        signer_infos = sd["signer_infos"]
        if len(signer_infos) != 1:
            raise ValueError("expected exactly one CMS SignerInfo")
        si = signer_infos[0]
        alg_name = si["digest_algorithm"]["algorithm"].native
        if alg_name not in _HASH_OIDS:
            raise ValueError(f"unsupported CMS digest algorithm: {alg_name}")
        hash_cls, py_hash = _HASH_OIDS[alg_name]

        embedded_certs: list[x509.Certificate] = []
        if sd["certificates"]:
            for choice in sd["certificates"]:
                if choice.name == "certificate":
                    embedded_certs.append(x509.load_der_x509_certificate(choice.chosen.dump()))

        signer_cert: x509.Certificate | None = None
        sid = si["sid"]
        candidates = embedded_certs + trusted
        if sid.name == "issuer_and_serial_number":
            target_serial = sid.chosen["serial_number"].native
            target_issuer_der = sid.chosen["issuer"].dump()
            for cert in candidates:
                if (
                    cert.serial_number == target_serial
                    and cert.issuer.public_bytes() == target_issuer_der
                ):
                    signer_cert = cert
                    break
        elif sid.name == "subject_key_identifier":
            target_ski = bytes(sid.chosen)
            for cert in candidates:
                try:
                    ski = cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
                    if ski.digest == target_ski:
                        signer_cert = cert
                        break
                except x509.ExtensionNotFound:
                    continue
        if signer_cert is None and sid.name not in {"issuer_and_serial_number", "subject_key_identifier"}:
            signer_cert = embedded_certs[0] if embedded_certs else trusted[0]

        if signer_cert is None:
            raise ValueError("matching TSA signer certificate not found")

        supported_critical_leaf_oids = {
            x509.oid.ExtensionOID.BASIC_CONSTRAINTS,
            x509.oid.ExtensionOID.KEY_USAGE,
            x509.oid.ExtensionOID.EXTENDED_KEY_USAGE,
        }
        for ext in signer_cert.extensions:
            if ext.critical and ext.oid not in supported_critical_leaf_oids:
                raise ValueError(f"unsupported critical leaf extension: {ext.oid.dotted_string}")

        eku_ext = signer_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        if not eku_ext.critical or list(eku_ext.value) != [ExtendedKeyUsageOID.TIME_STAMPING]:
            raise ValueError("signer certificate must hold critical ExtendedKeyUsage with only id-kp-timeStamping")

        gen_time = tst["gen_time"].native
        if signer_cert.not_valid_before_utc > gen_time or gen_time > signer_cert.not_valid_after_utc:
            raise ValueError("TSTInfo gen_time outside signer certificate validity window")

        supported_critical_ca_oids = {
            x509.oid.ExtensionOID.BASIC_CONSTRAINTS,
            x509.oid.ExtensionOID.KEY_USAGE,
        }

        def _is_valid_ca(cert: x509.Certificate) -> bool:
            if cert.not_valid_before_utc > gen_time or gen_time > cert.not_valid_after_utc:
                return False
            for ext in cert.extensions:
                if ext.critical and ext.oid not in supported_critical_ca_oids:
                    return False
            try:
                bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
                if not bc.ca:
                    return False
            except x509.ExtensionNotFound:
                return False
            try:
                ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
                if not ku.key_cert_sign:
                    return False
            except x509.ExtensionNotFound:
                pass
            return True

        trusted_fps = {t.fingerprint(hashes.SHA256()) for t in trusted}
        cert_trusted = signer_cert.fingerprint(hashes.SHA256()) in trusted_fps
        if not cert_trusted:
            verified_chain = False
            # Allow direct CA root signature or one intermediate CA signed by trusted CA root
            pool_cas = [c for c in (embedded_certs + trusted) if _is_valid_ca(c)]
            for ca in pool_cas:
                if signer_cert.issuer != ca.subject:
                    continue
                try:
                    _verify_cert_signature(
                        signer_cert, ca.public_key(), signer_cert.signature_hash_algorithm
                    )
                except InvalidSignature:
                    continue
                if ca.fingerprint(hashes.SHA256()) in trusted_fps:
                    verified_chain = True
                    break
                for root_ca in trusted:
                    if _is_valid_ca(root_ca) and ca.issuer == root_ca.subject:
                        try:
                            _verify_cert_signature(
                                ca, root_ca.public_key(), ca.signature_hash_algorithm
                            )
                            verified_chain = True
                            break
                        except InvalidSignature:
                            continue
                if verified_chain:
                    break
            if not verified_chain:
                raise ValueError("TSA signer certificate not trusted by pinned roots")

        signed_attrs = si["signed_attrs"]
        if not signed_attrs:
            raise ValueError("CMS SignerInfo must contain signed_attrs")
        ct_attrs = [a for a in signed_attrs if a["type"].native == "content_type"]
        if len(ct_attrs) != 1 or len(ct_attrs[0]["values"]) != 1 or ct_attrs[0]["values"][0].dotted != "1.2.840.113549.1.9.16.1.4":
            raise ValueError("CMS signed contentType must equal unique id-ct-TSTInfo")
        md_attrs = [a for a in signed_attrs if a["type"].native == "message_digest"]
        if len(md_attrs) != 1 or len(md_attrs[0]["values"]) != 1 or md_attrs[0]["values"][0].native != py_hash(raw_tst).digest():
            raise ValueError("CMS signed messageDigest does not match unique TSTInfo DER bytes")

        signer_der = signer_cert.public_bytes(encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.DER)
        ess_v1 = [a for a in signed_attrs if a["type"].dotted == "1.2.840.113549.1.9.16.2.12"]
        ess_v2 = [a for a in signed_attrs if a["type"].dotted == "1.2.840.113549.1.9.16.2.47"]
        if not ess_v1 and not ess_v2:
            raise ValueError("CMS SignerInfo must contain ESS SigningCertificate or SigningCertificateV2")
        ess_matched = False
        for attr in ess_v1:
            if len(attr["values"]) != 1:
                raise ValueError("ESS SigningCertificate must be single-valued")
            certs_seq = attr["values"][0].native.get("certs") or []
            if certs_seq:
                c0 = certs_seq[0]
                if c0.get("cert_hash") == hashlib.sha1(signer_der).digest():
                    iss = c0.get("issuer_serial")
                    if iss is None or int(iss.get("serial_number", -1)) == signer_cert.serial_number:
                        ess_matched = True
        for attr in ess_v2:
            if len(attr["values"]) != 1:
                raise ValueError("ESS SigningCertificateV2 must be single-valued")
            certs_seq = attr["values"][0].native.get("certs") or []
            if certs_seq:
                c0 = certs_seq[0]
                h_alg = (c0.get("hash_algorithm") or {}).get("algorithm") or "sha256"
                _, ess_hash_fn = _HASH_OIDS.get(h_alg, (None, hashlib.sha1 if h_alg == "sha1" else None))
                if ess_hash_fn is not None and c0.get("cert_hash") == ess_hash_fn(signer_der).digest():
                    iss = c0.get("issuer_serial")
                    if iss is None or int(iss.get("serial_number", -1)) == signer_cert.serial_number:
                        ess_matched = True
        if not ess_matched:
            raise ValueError("ESS SigningCertificate hash does not match TSA signer certificate")

        attrs_der = signed_attrs.dump()
        if attrs_der[:1] == b"\xa0":
            signed_set_der = b"\x31" + attrs_der[1:]
        elif attrs_der[:1] == b"\x31":
            signed_set_der = attrs_der
        else:
            raise ValueError("unexpected CMS signed_attrs ASN.1 tag")
        sig_algo_name = si["signature_algorithm"]["algorithm"].native
        _verify_signer_bytes(signer_cert.public_key(), bytes(si["signature"]), signed_set_der, hash_cls, sig_algo_name)
        return TimestampVerificationResult(
            True, "ok", gen_time.astimezone(UTC).isoformat().replace("+00:00", "Z"), digest_hex
        )
    except Exception as exc:
        return TimestampVerificationResult(False, str(exc), None, digest_hex)


def _post_tsa(url: str, data: bytes) -> bytes:
    request = Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/timestamp-query",
            "Accept": "application/timestamp-reply",
        },
    )
    with urlopen(request, timeout=20) as response:
        result = response.read(4 * 1024 * 1024 + 1)
    if not result or len(result) > 4 * 1024 * 1024:
        raise ValueError("invalid TSA response size")
    return result


class RFC3161Client:
    """Submit DER timestamp requests and verify responses against trusted TSA roots."""

    def __init__(
        self,
        url: str,
        *,
        trusted_cert_pem: str | Path | bytes | None = None,
        transport: Callable[[str, bytes], bytes] | None = None,
    ) -> None:
        self.url = _https(url)
        self.trusted_cert_pem = trusted_cert_pem
        self._transport = transport or _post_tsa

    def submit_digest_sha256(self, digest: bytes) -> TimestampAttestation:
        nonce = secrets.randbits(128)
        request = timestamp_request(digest, nonce)
        response = self._transport(self.url, request)
        if not isinstance(response, bytes) or not response:
            raise ValueError("TSA transport must return response bytes")
        verified = False
        gen_time: str | None = None
        if self.trusted_cert_pem is not None:
            check = verify_rfc3161_tst(
                response,
                digest,
                trusted_cert_pem=self.trusted_cert_pem,
                expected_nonce=nonce,
            )
            if not check.valid:
                raise ValueError(f"TSA verification failed: {check.reason}")
            verified = True
            gen_time = check.gen_time_utc
        return TimestampAttestation(
            "rfc3161",
            digest.hex(),
            utc_now(),
            verified,
            base64.b64encode(response).decode("ascii"),
            base64.b64encode(request).decode("ascii"),
            gen_time,
            nonce,
        )


def fetch_latest_quicknet_round(
    *,
    urls: tuple[str, ...] = DRAND_QUICKNET_URLS,
    chain_hash: str = DRAND_QUICKNET_CHAIN_HASH,
    public_key_hex: str = DRAND_QUICKNET_PUBKEY_HEX,
    transport: Callable[[str], dict[str, Any]] | None = None,
) -> BeaconReading:
    """Fetch and cryptographically verify the latest drand quicknet round (fallback across mirrors)."""
    getter = transport or _get_json
    errors: list[str] = []
    for base in urls:
        clean_base = _https(base)
        try:
            payload = getter(f"{clean_base}/{chain_hash}/public/latest")
            round_no = payload.get("round")
            randomness = payload.get("randomness")
            signature = payload.get("signature")
            prev_sig = payload.get("previous_signature")
            if type(round_no) is not int or not isinstance(randomness, str) or not isinstance(signature, str):
                raise ValueError("malformed drand response payload")
            check = verify_drand_round(
                round_no,
                randomness,
                signature,
                public_key_hex=public_key_hex,
                scheme="drand-quicknet",
                prev_signature_hex=prev_sig if isinstance(prev_sig, str) else None,
            )
            if not check.valid:
                raise ValueError(check.reason)
            return BeaconReading(
                provider=clean_base,
                round_number=round_no,
                fetched_at=utc_now(),
                value_hex=randomness,
                signature_hex=signature,
                chain_hash=chain_hash,
                cryptographically_verified=True,
                scheme="drand-quicknet",
            )
        except Exception as exc:
            errors.append(f"{clean_base}: {exc}")
    raise RuntimeError("all drand endpoints failed: " + "; ".join(errors))


def fetch_future_quicknet_round(
    target_round: int,
    *,
    urls: tuple[str, ...] = DRAND_QUICKNET_URLS,
    chain_hash: str = DRAND_QUICKNET_CHAIN_HASH,
    public_key_hex: str = DRAND_QUICKNET_PUBKEY_HEX,
    timeout_s: float = 25.0,
) -> BeaconReading:
    """Wait for and verify exact future target_round via drand HTTP v2 /{chain}/public/{round}."""
    if type(target_round) is not int or not 1 <= target_round < 2**64:
        raise ValueError("target_round must be a positive u64")
    round_dt = drand_quicknet_round_time_utc(target_round)
    initial_wait = (round_dt - datetime.now(UTC)).total_seconds() + 0.5
    if initial_wait > 0:
        time.sleep(min(initial_wait, timeout_s))
    deadline = time.monotonic() + timeout_s
    last_err: str = "no attempt"
    while True:
        for base in urls:
            clean_base = _https(base)
            try:
                payload = _get_json(f"{clean_base}/{chain_hash}/public/{target_round}")
                round_no = payload.get("round")
                randomness = payload.get("randomness")
                signature = payload.get("signature")
                prev_sig = payload.get("previous_signature")
                if round_no != target_round or not isinstance(randomness, str) or not isinstance(signature, str):
                    raise ValueError("malformed or mismatched drand round response")
                check = verify_drand_round(
                    round_no,
                    randomness,
                    signature,
                    public_key_hex=public_key_hex,
                    scheme="drand-quicknet",
                    prev_signature_hex=prev_sig if isinstance(prev_sig, str) else None,
                )
                if not check.valid:
                    raise ValueError(check.reason)
                return BeaconReading(
                    provider=clean_base,
                    round_number=round_no,
                    fetched_at=utc_now(),
                    value_hex=randomness,
                    signature_hex=signature,
                    chain_hash=chain_hash,
                    cryptographically_verified=True,
                    scheme="drand-quicknet",
                )
            except Exception as exc:
                last_err = f"{clean_base}: {exc}"
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for quicknet round {target_round}: {last_err}")
        time.sleep(1.0)


def fetch_freetsa_cacert(*, url: str = FREETSA_CACERT_URL) -> bytes:
    clean = _https(url)
    with urlopen(Request(clean, headers={"Accept": "application/x-pem-file"}), timeout=15) as resp:
        data = resp.read(256 * 1024 + 1)
    if not data or len(data) > 256 * 1024 or b"BEGIN CERTIFICATE" not in data:
        raise ValueError("invalid FreeTSA CA certificate bundle")
    return data


def fetch_rfc3161_timestamp(
    digest: bytes,
    *,
    url: str = FREETSA_URL,
    trusted_cert_pem: str | Path | bytes | None = None,
    transport: Callable[[str, bytes], bytes] | None = None,
) -> TimestampAttestation:
    """Submit a SHA-256 digest (32 bytes) to an RFC 3161 TSA and verify its signed token."""
    pem = trusted_cert_pem if trusted_cert_pem is not None else fetch_freetsa_cacert()
    client = RFC3161Client(url, trusted_cert_pem=pem, transport=transport)
    return client.submit_digest_sha256(digest)
