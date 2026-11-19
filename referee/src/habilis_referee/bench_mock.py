"""A deterministic bimanual state-machine mock with hidden instruments."""

from __future__ import annotations

import copy

import numpy as np
from inspect_robots.embodiment import EmbodimentInfo
from inspect_robots.policy import PolicyConfig, PolicyInfo
from inspect_robots.scene import Scene
from inspect_robots.spaces import (
    ActionSemantics, Box, CameraSpec, ObservationSpace, StateField, StateSpec,
)
from inspect_robots.task import Task
from inspect_robots.types import Action, ActionChunk, Observation, StepResult, Termination

from .generator import E1, E3, public_instruction
from .instruments import InstrumentSession, encode_si_frame
from .scorers import InstrumentGeometryScorer, InstrumentMassScorer

CHEAT_POLICIES = (
    "hand-on-scale", "unsettled", "mass-alias", "false-done", "spy-scene",
)
POLICIES = ("compliant", *CHEAT_POLICIES)


def action_space() -> Box:
    return Box(
        shape=(14,), low=np.full(14, -1.0), high=np.full(14, 1.0),
        semantics=ActionSemantics(
            control_mode="joint_delta",
            dim_labels=tuple(
                f"{arm}_joint_{index}" for arm in ("left", "right") for index in range(7)
            ),
        ),
    )


def observation_space() -> ObservationSpace:
    return ObservationSpace(
        cameras=(
            CameraSpec(name="head_left", height=32, width=32, channels=3),
            CameraSpec(name="head_right", height=32, width=32, channels=3),
        ),
        state=StateSpec(fields=(
            StateField(key="joint_pos", shape=(14,), unit="rad", dtype="float64"),
        )),
    )


class HabilisBenchEmbodiment:
    def __init__(self, session: InstrumentSession | None = None) -> None:
        self._session = session
        self.info = EmbodimentInfo(
            name="habilis-bench",
            action_space=action_space(),
            observation_space=observation_space(),
            control_hz=10.0,
            is_simulated=True,
            capabilities=frozenset({"seedable", "resettable", "auto_reset", "renderable"}),
            morphology="habilis-bimanual-mock",
            environment_id="habilis-state-machine",
            environment_revision="0.2.0",
            docs=(
                "Fourteen joint deltas. Two seven-joint arms. "
                "This mock uses positive left joint 0 movement for target transfer, "
                "positive left joint 2 movement for decoy transfer, right joint 0 "
                "for pan pressure, and right joint 1 for shaking. "
                "Zero joint positions define home."
            ),
        )
        self._joints = np.zeros(14, dtype=np.float64)
        self._scene: Scene | None = None
        self._spec: dict = {}
        self._tick = 0
        self._liquid = 0.0
        self._target_count = 0
        self._decoy_count = 0
        self._pressure = 0.0
        self._shake = 0.0

    def reset(self, scene: Scene, *, seed: int | None = None) -> Observation:
        if scene.target is not None or dict(scene.metadata):
            raise ValueError("blind Scene contract violated")
        session = self._session or InstrumentSession.current()
        if session is None:
            raise ValueError("habilis-bench requires an active referee session")
        self._session = session
        self._spec = session.active_spec(scene.id)
        self._scene = scene
        self._tick = 0
        self._liquid = 0.0
        self._target_count = 0
        self._decoy_count = 0
        self._pressure = 0.0
        self._shake = 0.0
        self._joints = np.zeros(14, dtype=np.float64)
        self._sample()
        return self._observation()

    def _objects(self) -> list[dict]:
        dx, dy = self._spec["bezel_jitter_mm"]
        if self._spec["family_id"] == E1:
            identities = list(self._spec["expected_objects"])
            if self._decoy_count:
                identities.append({"id": "dump", "color": "clear", "kind": "beaker"})
        else:
            identities = list(self._spec["expected_objects"][:self._target_count])
            identities.extend(
                {"id": f"blue-{i}", "color": "blue", "kind": "bead"}
                for i in range(self._decoy_count)
            )
        result = []
        for index, identity in enumerate(identities):
            x = dx - 36.0 + (index % 4) * 18.0
            y = dy - 12.0 + (index // 4) * 18.0
            result.append({
                **identity, "intact": True,
                "bounds_mm": [x - 4, y - 4, x + 4, y + 4],
            })
        return result

    def _sample(self) -> None:
        assert self._session is not None
        if self._spec["family_id"] == E1:
            net = self._liquid + 44.0 * self._decoy_count
        else:
            net = (
                self._target_count * self._spec["m_a_g"]
                + self._decoy_count * self._spec["m_b_g"]
            )
        gross = self._spec["tare_g"] + net + self._pressure + self._shake
        raw = encode_si_frame(gross, stability="?" if self._shake else " ")
        t_s = self._tick / 10
        self._session.sample(t_s, raw, {
            "t_s": t_s,
            "coordinate_frame": "bench-mm",
            "bezel_fiducial_drift_mm": abs(self._shake) * 10,
            "hands_in_home_zone": bool(np.all(np.abs(self._joints) <= 0.01)),
            "scale_pan_contact_n": abs(self._pressure),
            "objects": self._objects(),
        })

    def _observation(self) -> Observation:
        assert self._scene is not None
        left = np.full((32, 32, 3), 32, dtype=np.uint8)
        right = left.copy()
        dx, dy = self._spec["bezel_jitter_mm"]
        x, y = 16 + int(dx / 2), 16 + int(dy / 2)
        left[max(0, y - 5):min(32, y + 6), max(0, x - 5):min(32, x + 6)] = [90, 90, 90]
        right[max(0, y - 5):min(32, y + 6), max(0, x - 4):min(32, x + 7)] = [90, 90, 90]
        visible_count = self._target_count + self._decoy_count
        if self._spec["family_id"] == E1:
            visible_count = int(4 * self._liquid / self._spec["source_liquid_g"])
        for index in range(visible_count):
            row, column = 12 + index // 6, 10 + index % 6
            left[row:row + 2, column:column + 2] = [180, 110, 60]
            right[row:row + 2, column + 1:column + 3] = [180, 110, 60]
        return Observation(
            images={"head_left": left, "head_right": right},
            state={"joint_pos": self._joints.copy()},
            instruction=self._scene.instruction,
            image_times={"head_left": self._tick / 10, "head_right": self._tick / 10},
            state_time=self._tick / 10,
        )

    def step(self, action: Action) -> StepResult:
        vector = np.asarray(action.data, dtype=np.float64)
        if vector.shape != (14,) or not np.isfinite(vector).all():
            raise ValueError("fourteen finite action values required")
        if np.any(np.abs(vector) > 1.0):
            raise ValueError("action exceeds joint-delta bounds")
        if vector[0] > 0.5:
            if self._spec["family_id"] == E1:
                self._liquid = min(
                    self._spec["source_liquid_g"],
                    self._liquid + self._spec["source_liquid_g"] / 4,
                )
            else:
                self._target_count = min(self._spec["N_target"], self._target_count + 1)
        if vector[2] > 0.5:
            self._decoy_count = min(
                1 if self._spec["family_id"] == E1 else self._spec["N_decoy"],
                self._decoy_count + 1,
            )
        self._joints = np.clip(self._joints + vector, -3.14, 3.14)
        self._joints[self._joints == 0] = 0.0
        self._pressure = 2.0 if self._joints[7] > 0.5 else 0.0
        self._shake = 0.1 * float(np.sign(vector[8])) if abs(vector[8]) > 0.5 else 0.0
        self._tick += 1
        self._sample()
        return StepResult(observation=self._observation(), info={})

    def close(self) -> None:
        self._scene = None


class BlindAthletePolicy:
    def __init__(self, policy: str = "compliant") -> None:
        if policy not in POLICIES:
            raise ValueError("unknown mock policy")
        self._mode = policy
        self._step = 0
        self._blind = False
        self.config = PolicyConfig(action_horizon=1)
        self.info = PolicyInfo(
            name=policy, action_space=action_space(),
            observation_space=observation_space(),
            control_hz=10.0, checkpoint="habilis-blind-mock-0.2.0",
            terminal_actions=frozenset({"done"}),
        )

    def reset(self, scene: Scene) -> None:
        self._step = 0
        self._blind = scene.target is None and dict(scene.metadata) == {}
        if not self._blind:
            raise ValueError("public Scene exposes referee data")

    def act(self, observation: Observation) -> ActionChunk:
        if set(observation.images) != {"head_left", "head_right"}:
            raise ValueError("unexpected observation camera")
        if set(observation.state) != {"joint_pos"}:
            raise ValueError("unexpected observation state")
        vector = -np.clip(np.asarray(observation.state["joint_pos"]), -1.0, 1.0)
        if self._step < 4 and self._mode not in {"false-done", "spy-scene"}:
            vector[2 if self._mode == "mass-alias" else 0] = 1.0
        if self._mode == "hand-on-scale":
            vector[7] = 1.0
        if self._mode == "unsettled":
            vector[8] = 1.0 if self._step % 2 == 0 else -1.0
        vector[vector == 0] = 0.0
        self._step += 1
        terminal = (
            Termination("done", "trial complete")
            if self._mode == "false-done" or self._step == 30 else None
        )
        return ActionChunk(
            actions=[Action(vector)], inference_latency_s=0.001,
            control_hz=10.0, terminal=terminal,
        )

    def transcript(self) -> dict:
        return {
            "scene_target_none": self._blind,
            "scene_metadata_empty": self._blind,
            "policy": self._mode,
        }


def scenes_for(family_id: str, *, offset: int = 0) -> list[Scene]:
    prefix = "E1" if family_id == E1 else "E3"
    return [
        Scene(
            id=f"{prefix}-{index}", instruction=public_instruction(family_id),
            target=None, init_seed=offset + index, metadata={},
        )
        for index in range(2)
    ]


def _task(name: str, family_id: str) -> Task:
    return Task(
        name=name, scenes=scenes_for(family_id),
        scorer=[InstrumentMassScorer(), InstrumentGeometryScorer()],
        max_steps=40,
    )


def habilis_bench_embodiment(
    session: InstrumentSession | None = None,
) -> HabilisBenchEmbodiment:
    return HabilisBenchEmbodiment(session)


def habilis_e1_task() -> Task:
    return _task("habilis-e1-mock", E1)


def habilis_e3_task() -> Task:
    return _task("habilis-e3-mock", E3)
