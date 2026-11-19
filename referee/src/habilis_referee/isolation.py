"""OS-process and working-directory isolation adapter for athlete policies."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from inspect_robots.embodiment import EmbodimentInfo
from inspect_robots.policy import PolicyBase, PolicyConfig, PolicyInfo
from inspect_robots.scene import Scene
from inspect_robots.spaces import ActionSemantics, Box, ObservationSpace
from inspect_robots.task import TaskEnvelope
from inspect_robots.types import Action, ActionChunk, Observation, Termination

from .proc_sandbox import ProcessTreeGuard, popen_session_kwargs

_SAFE_ENV_KEYS = ("SYSTEMROOT", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "HOME")


def _encode_observation(
    obs: Observation,
    *,
    mask_tactile: bool = False,
    allowed_cameras: frozenset[str] = frozenset({"head_left", "head_right"}),
    allowed_state_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    images_payload = {}
    for cam, arr in obs.images.items():
        if cam not in allowed_cameras:
            continue
        u8 = np.asarray(arr, dtype=np.uint8)
        images_payload[cam] = {
            "shape": list(u8.shape),
            "dtype": "uint8",
            "data_b64": base64.b64encode(u8.tobytes()).decode("ascii"),
        }
    effective_allowed = (
        frozenset({"joint_pos"}) if mask_tactile and allowed_state_keys is None else allowed_state_keys
    )
    state_payload = {
        key: np.asarray(val, dtype=np.float64).tolist()
        for key, val in obs.state.items()
        if (effective_allowed is None or key in effective_allowed)
        and not (
            mask_tactile
            and any(t in key.casefold() for t in ("tactile", "touch", "fingertip", "force", "contact", "effort", "torque", "wrench"))
        )
    }
    return {
        "images": images_payload,
        "state": state_payload,
        "instruction": obs.instruction,
        "image_times": {k: v for k, v in obs.image_times.items() if k in images_payload},
        "state_time": obs.state_time,
    }


def _decode_action_chunk(raw: dict[str, Any]) -> ActionChunk:
    actions = [Action(np.asarray(vec, dtype=np.float64)) for vec in raw["actions"]]
    term = raw.get("terminal")
    termination = (
        Termination(term["kind"], term.get("reason", ""))
        if isinstance(term, dict) else None
    )
    return ActionChunk(
        actions=actions,
        inference_latency_s=float(raw.get("inference_latency_s", 0.001)),
        control_hz=float(raw.get("control_hz", 10.0)),
        terminal=termination,
    )


class SubprocessPolicyAdapter(PolicyBase):
    """Execute athlete policy decisions in a separate OS process with empty cwd/env."""

    def __init__(
        self,
        policy: str = "compliant",
        *,
        python_executable: str | None = None,
        timeout_s: float = 30.0,
        mask_tactile: bool = False,
    ) -> None:
        from .bench_mock import POLICIES, action_space, observation_space

        if policy not in (*POLICIES, "memory-disk-snooper"):
            raise ValueError(f"unsupported isolated worker policy: {policy!r}")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._mode = policy
        self._python = python_executable or sys.executable
        self._timeout_s = float(timeout_s)
        self._mask_tactile = bool(mask_tactile)
        self._proc: subprocess.Popen[str] | None = None
        self._guard: ProcessTreeGuard | None = None
        self._sandbox_dir: tempfile.TemporaryDirectory[str] | None = None
        self._last_transcript: dict[str, Any] = {}
        self.config = PolicyConfig(action_horizon=1)
        self.info = PolicyInfo(
            name=policy,
            action_space=action_space(),
            observation_space=observation_space(),
            control_hz=10.0,
            checkpoint="habilis-isolated-worker-1.0",
            terminal_actions=frozenset({"done", "give_up"}),
        )

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._sandbox_dir = tempfile.TemporaryDirectory(prefix="habilis_athlete_proc_")
        env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
        env["PYTHONNOUSERSITE"] = "1"
        env["HABILIS_ATHLETE_MODE"] = self._mode
        referee_src = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = referee_src
        self._proc = subprocess.Popen(
            [self._python, "-u", "-m", "habilis_referee.isolation"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=self._sandbox_dir.name,
            env=env,
            **popen_session_kwargs(),
        )
        self._guard = ProcessTreeGuard(self._proc)
        return self._proc

    def _rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        proc = self._ensure_worker()
        assert proc.stdin is not None and proc.stdout is not None
        result_box: list[str] = []
        err_box: list[BaseException] = []
        wire = json.dumps(payload, allow_nan=False) + "\n"

        def _exchange() -> None:
            try:
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(wire)
                proc.stdin.flush()
                result_box.append(proc.stdout.readline())
            except BaseException as exc:  # pragma: no cover - defensive
                err_box.append(exc)

        t = threading.Thread(target=_exchange, daemon=True)
        t.start()
        t.join(timeout=self._timeout_s)
        if t.is_alive():
            if self._guard is not None:
                self._guard.terminate()
                self._guard = None
            else:
                proc.kill()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            proc.wait(timeout=3)
            self._proc = None
            raise TimeoutError(f"isolated athlete worker exceeded {self._timeout_s:.2f}s RPC timeout")
        if err_box:
            raise RuntimeError(f"isolated athlete IPC read error: {err_box[0]}")
        line = result_box[0] if result_box else ""
        if not line:
            raise RuntimeError(f"isolated athlete process exited unexpectedly (rc={proc.poll()})")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise RuntimeError(f"isolated athlete worker error: {reply.get('error')}")
        return reply["result"]

    def bind(self, embodiment_info: EmbodimentInfo) -> None:
        return None

    def bind_task(self, envelope: TaskEnvelope) -> None:
        return None

    def reset(self, scene: Scene) -> None:
        if scene.target is not None or dict(scene.metadata):
            raise ValueError("public Scene exposes hidden referee target or metadata")
        scene_payload = {
            "id": scene.id,
            "instruction": scene.instruction,
            "init_seed": scene.init_seed,
            "target": None,
            "metadata": {},
        }
        res = self._rpc({"op": "reset", "scene": scene_payload})
        self._last_transcript = dict(res.get("transcript", {}))

    def act(self, observation: Observation) -> ActionChunk:
        t0 = time.monotonic()
        res = self._rpc({
            "op": "act",
            "observation": _encode_observation(
                observation,
                mask_tactile=self._mask_tactile,
                allowed_state_keys=frozenset({"joint_pos"}),
            ),
        })
        measured_lat = time.monotonic() - t0
        self._last_transcript = dict(res.get("transcript", self._last_transcript))
        chunk = _decode_action_chunk(res["chunk"])
        # Parent measures true IPC latency instead of trusting self-reported child timing.
        return ActionChunk(
            actions=chunk.actions,
            inference_latency_s=measured_lat,
            control_hz=10.0,
            terminal=chunk.terminal,
        )

    def transcript(self) -> dict[str, Any]:
        return dict(self._last_transcript)

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.poll() is None and self._proc.stdin is not None:
                    self._proc.stdin.write(json.dumps({"op": "close"}) + "\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=3)
            except Exception:
                if self._guard is not None:
                    self._guard.terminate()
                else:
                    self._proc.kill()
            finally:
                if self._guard is not None:
                    self._guard.terminate()
                    self._guard = None
                self._proc = None
        if self._sandbox_dir is not None:
            self._sandbox_dir.cleanup()
            self._sandbox_dir = None


def _run_snooper_audit(scene: dict[str, Any], obs: dict[str, Any]) -> dict[str, Any]:
    """Inside child worker: attempt to discover any hidden targets or files."""
    leaked_tokens: list[str] = []
    # Check env vars, cwd, and sys.modules for hidden referee state.
    if os.environ:
        for k, v in os.environ.items():
            low = (k + "=" + v).casefold()
            if any(tok in low for tok in ("target_net_g", "referee_target", "secret", "_scale.txt")):
                leaked_tokens.append(f"env:{k}")
    cwd_entries = list(Path.cwd().iterdir())
    for p in cwd_entries:
        if any(tok in p.name.casefold() for tok in ("scale", "overhead", "referee_targets")):
            leaked_tokens.append(f"cwd:{p.name}")
    loaded_instruments = "habilis_referee.instruments" in sys.modules
    if loaded_instruments:
        from .instruments import InstrumentSession
        if InstrumentSession.current() is not None:
            leaked_tokens.append("memory:active_InstrumentSession")
    if scene.get("target") is not None or scene.get("metadata"):
        leaked_tokens.append("scene:private_fields")
    return {
        "worker_pid": os.getpid(),
        "isolated_cwd_empty": len(cwd_entries) == 0,
        "loaded_instruments_module": loaded_instruments,
        "leaked_tokens": leaked_tokens,
    }


def _worker_main() -> None:
    mode = os.environ.get("HABILIS_ATHLETE_MODE", "compliant")
    step_idx = 0
    blind = False
    snooper_report: dict[str, Any] = {}
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        req = json.loads(raw_line)
        op = req.get("op")
        if op == "close":
            sys.stdout.write(json.dumps({"ok": True, "result": {}}) + "\n")
            sys.stdout.flush()
            break
        if op == "reset":
            scene = req["scene"]
            step_idx = 0
            blind = scene.get("target") is None and scene.get("metadata") == {}
            if mode == "memory-disk-snooper":
                snooper_report = _run_snooper_audit(scene, {})
            sys.stdout.write(json.dumps({
                "ok": True,
                "result": {
                    "transcript": {
                        "scene_target_none": blind,
                        "scene_metadata_empty": blind,
                        "policy": mode,
                        "isolated_worker_pid": os.getpid(),
                        **({"snooper": snooper_report} if mode == "memory-disk-snooper" else {}),
                    }
                },
            }) + "\n")
            sys.stdout.flush()
            continue
        if op == "act":
            obs = req["observation"]
            if set(obs["images"]) != {"head_left", "head_right"}:
                raise ValueError("unexpected camera set in athlete subprocess")
            if set(obs["state"]) != {"joint_pos"}:
                raise ValueError("unexpected state keys in athlete subprocess")
            joints = np.asarray(obs["state"]["joint_pos"], dtype=np.float64)
            vec = -np.clip(joints, -1.0, 1.0)
            if step_idx < 4 and mode not in {"false-done", "spy-scene", "memory-disk-snooper"}:
                vec[2 if mode == "mass-alias" else 0] = 1.0
            if mode == "hand-on-scale":
                vec[7] = 1.0
            if mode == "unsettled":
                vec[8] = 1.0 if step_idx % 2 == 0 else -1.0
            vec[vec == 0] = 0.0
            step_idx += 1
            terminal = (
                {"kind": "done", "reason": "trial complete"}
                if mode in {"false-done", "memory-disk-snooper"} or step_idx == 30
                else None
            )
            if mode == "memory-disk-snooper":
                snooper_report = _run_snooper_audit(
                    {"target": None, "metadata": {}}, obs
                )
            sys.stdout.write(json.dumps({
                "ok": True,
                "result": {
                    "chunk": {
                        "actions": [vec.tolist()],
                        "inference_latency_s": 0.001,
                        "control_hz": 10.0,
                        "terminal": terminal,
                    },
                    "transcript": {
                        "scene_target_none": blind,
                        "scene_metadata_empty": blind,
                        "policy": mode,
                        "isolated_worker_pid": os.getpid(),
                        **({"snooper": snooper_report} if mode == "memory-disk-snooper" else {}),
                    },
                },
            }) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"ok": False, "error": f"unknown op: {op}"}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _worker_main()
