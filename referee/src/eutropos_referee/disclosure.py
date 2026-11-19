"""Dual-mode disclosure exporter and verifier (general-open vs hazard-escrowed)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .manifest import (
    bundle_path,
    object_hash,
    read_json,
    relative_path,
    sha256_file,
    validate_relative_path,
    write_json,
)

DISCLOSURE_GENERAL = "general-open"
DISCLOSURE_HAZARD = "hazard-escrowed"
DISCLOSURE_MODES = frozenset({DISCLOSURE_GENERAL, DISCLOSURE_HAZARD})


def prepare_disclosure_bundle(
    root: Path,
    *,
    mode: str,
    private_relpaths: list[str],
    escrow_dir: Path | None = None,
    benign_surrogate_declared: bool = True,
) -> tuple[Path, Path | None, Path | None]:
    """Emit disclosure_receipt.json and, in hazard-escrowed mode, move secrets to escrow_dir."""
    if mode not in DISCLOSURE_MODES:
        raise ValueError(f"unsupported disclosure mode: {mode!r}")
    if mode == DISCLOSURE_HAZARD and not benign_surrogate_declared:
        raise ValueError("hazard-escrowed bundles require benign_surrogate_declared=True")
    clean_rels = sorted({validate_relative_path(rel) for rel in private_relpaths})
    entries: list[dict[str, Any]] = []
    for rel in clean_rels:
        src = bundle_path(root, rel)
        if not src.is_file():
            raise ValueError(f"missing disclosure target file: {rel}")
        entries.append({
            "original_relpath": rel,
            "sha256": sha256_file(src),
            "size_bytes": src.stat().st_size,
        })

    escrow_receipt_path: Path | None = None
    actual_escrow_dir: Path | None = None

    if mode == DISCLOSURE_HAZARD:
        actual_escrow_dir = (
            escrow_dir.absolute()
            if escrow_dir is not None
            else root.parent / f"{root.name}.escrow"
        )
        escrow_root_resolved = actual_escrow_dir.resolve()
        public_root_resolved = root.resolve()
        if escrow_root_resolved == public_root_resolved or public_root_resolved in escrow_root_resolved.parents:
            raise ValueError("escrow_dir must live outside public bundle directory")
        if actual_escrow_dir.is_symlink():
            raise ValueError("escrow_dir must not be a symlink")
        actual_escrow_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            rel = entry["original_relpath"]
            src = bundle_path(root, rel)
            dst = actual_escrow_dir / rel
            rel_parts = Path(rel).parts
            cur = actual_escrow_dir
            for part in rel_parts[:-1]:
                cur = cur / part
                if cur.exists() and cur.is_symlink():
                    raise ValueError(f"symlink/junction inside escrow destination path: {cur}")
                cur.mkdir(exist_ok=True)
            if dst.exists() and dst.is_symlink():
                raise ValueError(f"symlink/junction at escrow destination: {dst}")
            resolved_dst = dst.resolve()
            if escrow_root_resolved not in resolved_dst.parents:
                raise ValueError(f"escrow destination escapes escrow_dir: {rel}")
            if resolved_dst == public_root_resolved or public_root_resolved in resolved_dst.parents:
                raise ValueError(f"escrow destination points inside public bundle: {rel}")
            shutil.move(str(src), str(dst))
            parent = src.parent
            while parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        escrow_root_sha = object_hash(entries)
        escrow_manifest = {
            "schema": "eutropos-escrow-archive-v1.0",
            "mode": mode,
            "benign_surrogate_declared": True,
            "escrow_root_sha256": escrow_root_sha,
            "file_count": len(entries),
            "entries": entries,
        }
        write_json(actual_escrow_dir / "escrow_manifest.json", escrow_manifest)
        escrow_receipt_path = root / "escrow_receipt.json"
        write_json(escrow_receipt_path, {
            "schema": "eutropos-escrow-receipt-v1.0",
            "mode": mode,
            "benign_surrogate_declared": True,
            "escrow_root_sha256": escrow_root_sha,
            "file_count": len(entries),
            "entries": entries,
        })
        public_files = []
        escrowed_paths = [e["original_relpath"] for e in entries]
    else:
        escrow_root_sha = None
        public_files = entries
        escrowed_paths = []

    receipt_path = root / "disclosure_receipt.json"
    write_json(receipt_path, {
        "schema": "eutropos-disclosure-v1.0",
        "mode": mode,
        "benign_surrogate_declared": bool(benign_surrogate_declared),
        "public_targets": public_files,
        "escrowed_paths": escrowed_paths,
        "escrow_root_sha256": escrow_root_sha,
        "escrow_receipt_path": relative_path(root, escrow_receipt_path) if escrow_receipt_path else None,
    })
    return receipt_path, escrow_receipt_path, actual_escrow_dir


def verify_disclosure_bundle(
    root: Path,
    *,
    expected_mode: str,
    escrow_dir: Path | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    receipt_file = bundle_path(root, "disclosure_receipt.json")
    if not receipt_file.is_file():
        return False, ["missing disclosure_receipt.json"]
    receipt = read_json(receipt_file, canonical=True)
    if receipt.get("schema") != "eutropos-disclosure-v1.0":
        errors.append("invalid disclosure_receipt.json schema")
    if receipt.get("mode") != expected_mode:
        errors.append("disclosure mode mismatch")

    if expected_mode == DISCLOSURE_GENERAL:
        if receipt.get("escrowed_paths") or receipt.get("escrow_root_sha256") is not None:
            errors.append("general-open bundle must not hold escrowed paths")
        pub_rels = {entry["original_relpath"] for entry in receipt.get("public_targets", [])}
        if "referee_targets.json" not in pub_rels:
            errors.append("general-open bundle missing referee_targets.json")
        for entry in receipt.get("public_targets", []):
            p = bundle_path(root, entry["original_relpath"])
            if not p.is_file():
                errors.append(f"missing public target in general-open bundle: {entry['original_relpath']}")
            elif sha256_file(p) != entry["sha256"] or p.stat().st_size != entry["size_bytes"]:
                errors.append(f"public target digest mismatch: {entry['original_relpath']}")
        return not errors, errors

    if expected_mode == DISCLOSURE_HAZARD:
        if receipt.get("benign_surrogate_declared") is not True:
            errors.append("hazard-escrowed bundle lacks benign_surrogate_declared=True")
        rec_path = bundle_path(root, "escrow_receipt.json")
        if not rec_path.is_file():
            errors.append("missing escrow_receipt.json")
            return False, errors
        esc_rec = read_json(rec_path, canonical=True)
        entries = esc_rec.get("entries", [])
        if esc_rec.get("escrow_root_sha256") != object_hash(entries) or esc_rec.get("escrow_root_sha256") != receipt.get("escrow_root_sha256"):
            errors.append("escrow_root_sha256 commitment mismatch")
        if esc_rec.get("file_count") != len(entries):
            errors.append("escrow file_count mismatch")
        esc_rels = {entry["original_relpath"] for entry in entries}
        if not {"referee_targets.json", "seed_reveal.json"} <= esc_rels:
            errors.append("hazard-escrowed bundle must escrow both referee_targets.json and seed_reveal.json")
        for entry in entries:
            rel = validate_relative_path(entry["original_relpath"])
            if (root / rel).exists():
                errors.append(f"escrowed secret leaked inside public bundle: {rel}")
            if escrow_dir is not None:
                esc_file = bundle_path(Path(escrow_dir), rel)
                if not esc_file.is_file():
                    errors.append(f"missing file in escrow archive: {rel}")
                elif sha256_file(esc_file) != entry["sha256"] or esc_file.stat().st_size != entry["size_bytes"]:
                    errors.append(f"escrow file digest mismatch: {rel}")
        return not errors, errors

    return False, [f"unsupported disclosure mode: {expected_mode!r}"]
