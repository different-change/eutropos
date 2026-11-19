"""Canonical JSON and complete portable evidence inventories."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

MAX_JSON_BYTES = 32 * 1024 * 1024
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _numbers(value: Any, *, reject_negative_zero: bool) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        if reject_negative_zero and value == 0.0 and math.copysign(1.0, value) < 0:
            raise ValueError("negative zero not allowed")
    elif isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for child in value.values():
            _numbers(child, reject_negative_zero=reject_negative_zero)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _numbers(child, reject_negative_zero=reject_negative_zero)


def canonical_json(value: Any) -> bytes:
    _numbers(value, reject_negative_zero=True)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def parse_json(data: bytes, *, canonical: bool = False) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON document exceeds the supported size")
    value = json.loads(
        data.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_bad_constant,
    )
    _numbers(value, reject_negative_zero=canonical)
    if canonical and canonical_json(value) != data:
        raise ValueError("JSON bytes are not canonical")
    return value


def read_json(path: Path, *, canonical: bool = False) -> Any:
    return parse_json(path.read_bytes(), canonical=canonical)


def write_json(path: Path, value: Any) -> None:
    data = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if not data or not data.endswith(b"\n"):
        raise ValueError(f"incomplete JSONL: {path.name}")
    lines = data.splitlines()
    result = []
    for index, line in enumerate(lines):
        if not line.strip():
            raise ValueError(f"empty JSONL line {index + 1}")
        value = parse_json(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {index + 1} must be an object")
        result.append(value)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("evidence path must be a nonempty string")
    if "\\" in value or any(c in value for c in '<>:"|?*\x00'):
        raise ValueError(f"unsafe evidence path: {value!r}")
    parts = value.split("/")
    if any(
        not part or part in {".", ".."} or part.endswith((" ", "."))
        or _RESERVED.match(part) or any(ord(c) < 32 for c in part)
        for part in parts
    ):
        raise ValueError(f"unsafe evidence path: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise ValueError(f"absolute evidence path: {value!r}")
    return value


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def bundle_path(root: Path, relative: str) -> Path:
    validate_relative_path(relative)
    if _is_link(root):
        raise ValueError("linked bundle root")
    path = root
    for part in relative.split("/"):
        path = path / part
        if _is_link(path):
            raise ValueError(f"linked evidence path: {relative}")
    path.resolve().relative_to(root.resolve())
    return path


def relative_path(root: Path, path: Path) -> str:
    value = path.absolute().relative_to(root.absolute()).as_posix()
    bundle_path(root, value)
    return value


def file_entry(root: Path, path: Path) -> dict[str, Any]:
    name = relative_path(root, path)
    if not path.is_file():
        raise ValueError(f"missing regular file: {name}")
    return {
        "path": name, "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def file_entries(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    names = [relative_path(root, path) for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("duplicate file in manifest")
    return [file_entry(root, bundle_path(root, name)) for name in sorted(names)]


def empty_directories(root: Path) -> list[str]:
    empty = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        if not directories and not filenames:
            relative = Path(current).relative_to(root).as_posix()
            empty.append(relative)
    return sorted(empty)


def inventory(root: Path) -> set[str]:
    if not root.is_dir() or _is_link(root):
        raise ValueError("evidence directory must be a regular directory")
    result: set[str] = set()
    aliases: dict[str, str] = {}
    empty: list[str] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        if not directories and not filenames:
            empty.append(Path(current).relative_to(root).as_posix())
        for name in directories + filenames:
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            validate_relative_path(relative)
            if _is_link(path):
                raise ValueError(f"linked evidence path: {relative}")
            folded = relative.casefold()
            if folded in aliases and aliases[folded] != relative:
                raise ValueError(f"case-aliased evidence paths: {relative}")
            aliases[folded] = relative
        for name in filenames:
            path = Path(current) / name
            if not path.is_file():
                raise ValueError(f"nonregular evidence file: {path}")
            result.add(path.relative_to(root).as_posix())
    if empty:
        raise ValueError("empty directories: " + ", ".join(sorted(empty)))
    return result


def make_plan(task_spec: dict[str, Any]) -> list[dict[str, Any]]:
    epochs = task_spec["epochs"]
    scenes = task_spec["scenes"]
    if type(epochs) is not int or not 1 <= epochs <= 1000:
        raise ValueError("epochs must be between 1 and 1000")
    ids = [scene["id"] for scene in scenes]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("scene IDs must be nonempty and unique")
    plan = []
    for scene_index, scene in enumerate(scenes):
        if type(scene["init_seed"]) is not int:
            raise ValueError("scene seeds must be integers")
        for epoch in range(epochs):
            plan.append({
                "trial_index": len(plan),
                "family_id": scene.get("family_id", task_spec["name"]),
                "scene_id": scene["id"],
                "scene_index": scene_index,
                "scene_init_seed": scene["init_seed"],
                "epoch": epoch,
            })
    return plan


def source_digest(entries: list[dict[str, Any]], prefix: str) -> str:
    selected = [
        {**entry, "path": entry["path"][len(prefix):]}
        for entry in entries if entry["path"].startswith(prefix)
    ]
    if not selected or any(not entry["path"].endswith(".py") for entry in selected):
        raise ValueError(f"invalid source snapshot: {prefix}")
    return object_hash(sorted(selected, key=lambda entry: entry["path"]))


def provenance_hashes(
    entries: list[dict[str, Any]], scorer_path: str, *,
    harness_version: str, referee_version: str,
) -> dict[str, Any]:
    by_path = {entry["path"]: entry for entry in entries}
    if len(by_path) != len(entries):
        raise ValueError("duplicate preregistration file")
    if not scorer_path.startswith(
        ("provenance/inspect_robots/", "provenance/habilis_referee/")
    ):
        raise ValueError("scoring source must be in a package snapshot")
    return {
        "harness": {
            "name": "inspect-robots", "version": harness_version,
            "sha256": source_digest(entries, "provenance/inspect_robots/"),
            "scope": "installed Python source inventory",
        },
        "referee_package": {
            "name": "habilis-referee", "version": referee_version,
            "sha256": source_digest(entries, "provenance/habilis_referee/"),
            "scope": "installed Python source inventory",
        },
        "scoring_code": {
            "path": scorer_path, "sha256": by_path[scorer_path]["sha256"],
        },
        "body_configuration": by_path["body_configuration.json"]["sha256"],
        "task_spec": by_path["task_spec.json"]["sha256"],
    }
