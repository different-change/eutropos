"""Semantic parsing of native action/chunk logs and frame sidecars."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .manifest import bundle_path, read_jsonl
from .instruments import finite_number


def _integer(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("nonnegative integer required")
    return value


def _vector(value: Any, dimension: int) -> None:
    if not isinstance(value, list) or len(value) != dimension:
        raise ValueError("action dimension mismatch")
    for item in value:
        finite_number(item)


def validate_native_artifacts(
    root: Path, manifest: dict, record: dict, configuration: dict, stamp: str,
) -> tuple[list[dict], list[dict]]:
    steps = _integer(record["steps"])
    chunk_count = _integer(record["chunks"])
    if steps != manifest["step_count"] or chunk_count < 1:
        raise ValueError("record step/chunk counts differ from manifest")
    action_space = configuration["spaces"]["body"]["action"]
    dimension = math.prod(action_space["shape"])
    semantics = action_space["semantics"]
    labels = semantics["dim_labels"] if semantics is not None else None
    actions = read_jsonl(bundle_path(root, manifest["actions_path"]))
    chunks = read_jsonl(bundle_path(root, manifest["chunks_path"]))
    if actions[0] != {
        "kind": "header", "run_id": stamp, "scene_id": record["scene_id"],
        "epoch": record["epoch"], "action_dim": dimension, "labels": labels,
    }:
        raise ValueError("action header mismatch")
    if chunks[0] != {
        "kind": "header", "record_id": record["record_id"],
        "action_dim": dimension, "labels": labels,
    }:
        raise ValueError("chunk header mismatch")
    if len(actions) != steps + 1 or len(chunks) != chunk_count + 1:
        raise ValueError("JSONL count mismatch")
    executed = actions[1:]
    produced = chunks[1:]
    for index, action in enumerate(executed):
        if set(action) != {"t", "action"} or _integer(action["t"]) != index:
            raise ValueError("action step index mismatch")
        _vector(action["action"], dimension)
    previous = -1
    for index, chunk in enumerate(produced):
        if set(chunk) != {"t", "actions", "terminal", "latency_s", "wall_s"}:
            raise ValueError("unexpected chunk fields")
        t = _integer(chunk["t"])
        if t <= previous or t > steps or (index == 0 and t != 0):
            raise ValueError("chunk step index mismatch")
        previous = t
        if not isinstance(chunk["actions"], list):
            raise ValueError("chunk actions must be a list")
        for vector in chunk["actions"]:
            _vector(vector, dimension)
        terminal = chunk["terminal"]
        if terminal is not None and (
            not isinstance(terminal, dict) or set(terminal) != {"kind", "reason"}
            or not isinstance(terminal["kind"], str) or not terminal["kind"]
            or not isinstance(terminal["reason"], str)
        ):
            raise ValueError("invalid terminal chunk")
        if not chunk["actions"] and terminal is None:
            raise ValueError("empty nonterminal chunk")
        for field in ("latency_s", "wall_s"):
            value = chunk[field]
            if value is None and field == "latency_s":
                continue
            if finite_number(value) < 0:
                raise ValueError("negative chunk latency")
        next_t = produced[index + 1]["t"] if index + 1 < len(produced) else steps
        _integer(next_t)
        used = next_t - t
        if used < 0 or used > len(chunk["actions"]):
            raise ValueError("chunk coverage differs from executed actions")
        if terminal is not None and index + 1 != len(produced):
            raise ValueError("actions follow terminal chunk")
        if [action["action"] for action in executed[t:next_t]] != chunk["actions"][:used]:
            raise ValueError("executed actions differ from produced chunks")
    if record["actions"] != manifest["actions_path"]:
        raise ValueError("record action path mismatch")
    cameras = {
        item["name"]: item
        for item in configuration["spaces"]["body"]["observation"]["cameras"]
    }
    refs = manifest["frame_index"]
    if len(refs) != len(manifest["frame_paths"]):
        raise ValueError("frame index count mismatch")
    expected = {(t, camera) for t in range(steps + 1) for camera in cameras}
    actual = {(item["t"], item["camera"]) for item in refs}
    if actual != expected or len(actual) != len(refs):
        raise ValueError("frame coverage mismatch")
    if sorted(item["path"] for item in refs) != manifest["frame_paths"]:
        raise ValueError("frame index path mismatch")
    for item in refs:
        _integer(item["t"])
        path = bundle_path(root, item["path"])
        with path.open("rb") as stream:
            frame = np.load(stream, allow_pickle=False)
            if stream.read(1):
                raise ValueError("trailing data after NumPy frame")
        if (
            not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0
            or not np.isfinite(frame).all()
            or list(frame.shape) != cameras[item["camera"]]["shape"]
        ):
            raise ValueError(f"invalid RGB frame: {item['path']}")
    events = record["events"]
    if not isinstance(events, list):
        raise ValueError("record events must be a list")
    for event in events:
        if (
            not isinstance(event, dict)
            or set(event) != {"kind", "t", "data"}
            or not isinstance(event["kind"], str)
            or type(event["t"]) is not int
            or not -1 <= event["t"] <= steps
            or not isinstance(event["data"], dict)
        ):
            raise ValueError("invalid native event")
    return actions, chunks
