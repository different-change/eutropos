"""Public configuration snapshots for the pinned framework interfaces."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np


def plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, float) and value == 0:
        return 0.0
    if isinstance(value, dict):
        return {str(key): plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(child) for child in value)
    return value


def space_document(action, observation) -> dict:
    semantics = plain(asdict(action.semantics)) if action.semantics is not None else None
    return {
        "action": {
            "shape": list(action.shape),
            "low": plain(action.low), "high": plain(action.high),
            "semantics": semantics,
        },
        "observation": {
            "cameras": [
                {
                    "name": camera.name,
                    "shape": [camera.height, camera.width, camera.channels],
                    "dtype": "uint8",
                }
                for camera in observation.cameras
            ],
            "state_keys": sorted(observation.state_keys),
            "state": (
                [plain(asdict(field)) for field in observation.state.fields]
                if observation.state is not None else None
            ),
        },
    }


def scene_document(scene) -> dict:
    return {
        "id": scene.id, "instruction": scene.instruction,
        "init_seed": scene.init_seed, "setup": scene.setup,
        "metadata": plain(dict(scene.metadata)),
        "target": plain(asdict(scene.target)) if scene.target is not None else None,
    }


def body_identity(body) -> dict:
    return {
        "name": body.info.name,
        "control_hz": body.info.control_hz,
        "is_simulated": body.info.is_simulated,
        "capabilities": sorted(body.info.capabilities),
        "morphology": body.info.morphology,
        "evaluation_interface": [
            name for name in ("health", "prepare_trial", "home", "park")
            if callable(getattr(body, name, None))
        ],
    }


def configuration_document(task, policy, body, seed: int) -> dict:
    return {
        "task": task.name, "inspect_robots_version": "1.0.0",
        "seed": seed, "max_steps": task.max_steps, "max_seconds": task.max_seconds,
        "policy": {
            "name": policy.info.name, "checkpoint": policy.info.checkpoint,
            "config": plain(asdict(policy.config)),
        },
        "embodiment": body_identity(body),
        "spaces": {
            "body": space_document(body.info.action_space, body.info.observation_space),
            "policy": space_document(policy.info.action_space, policy.info.observation_space),
        },
        "scenes": [scene_document(scene) for scene in task.scenes],
    }


def configuration_matches(actual: dict, expected: dict, *, trial: bool = False) -> bool:
    for key, value in expected.items():
        if trial and key == "scenes":
            continue
        if key == "policy":
            candidate = actual.get("policy")
            if not isinstance(candidate, dict):
                return False
            if any(candidate.get(field) != value[field] for field in ("name", "checkpoint")):
                return False
            config = candidate.get("config")
            if not isinstance(config, dict):
                return False
            # Additional policy metadata has no seed or epoch authority.
            if any(config.get(field, object()) != child for field, child in value["config"].items()):
                return False
        elif actual.get(key, object()) != value:
            return False
    return True


def observation_document(observation) -> dict:
    return {
        "images": {
            name: {"shape": list(image.shape), "dtype": str(image.dtype)}
            for name, image in observation.images.items()
        },
        "state": plain(dict(observation.state)),
        "instruction": observation.instruction,
        "extra": plain(dict(observation.extra)),
    }
