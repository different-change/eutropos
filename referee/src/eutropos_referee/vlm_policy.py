"""Isolated OS-subprocess closed-loop VLM policy adapter and P0 MuJoCo stress runner."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from inspect_robots.types import Action, ActionChunk, Observation, Termination
from PIL import Image, PngImagePlugin

from .proc_sandbox import ProcessTreeGuard, popen_session_kwargs

_WORKER_SCRIPT = r'''
import json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image

MODE = os.environ.get("EUTROPOS_VLM_BACKEND", "mock")
CLAUDE_BIN = (
    shutil.which("claude.exe")
    or shutil.which("claude")
    or (
        str(Path.home() / ".local" / "bin" / "claude.exe")
        if (Path.home() / ".local" / "bin" / "claude.exe").is_file()
        else "claude"
    )
)

def save_clean_png(u8_list, shape, out_path: Path) -> None:
    arr = np.asarray(u8_list, dtype=np.uint8).reshape(tuple(shape))
    img = Image.fromarray(arr, mode="RGB")
    img.save(out_path, format="PNG")

def parse_delta(text: str, dim: int = 26):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            d = [float(x) for x in obj.get("delta", [])]
            if len(d) == dim and all(np.isfinite(x) for x in d):
                arr = np.clip(np.asarray(d, dtype=np.float64), -0.25, 0.25)
                term = str(obj.get("terminal", "")).strip().lower()
                return arr.tolist(), term, str(obj.get("note", ""))[:180]
        except Exception:
            pass
    return [0.0] * dim, "", f"fallback_zero: {text[:120]}"

def call_codex(prompt: str, images: list[Path], timeout_s: int = 90) -> str:
    codex_bin = shutil.which("codex.cmd") or shutil.which("codex") or "codex.cmd"
    with tempfile.TemporaryDirectory(prefix="p0_c_") as td:
        out_p = Path(td) / "reply.txt"
        cmd = [codex_bin, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
               "-c", 'approval_policy="never"', "-C", td]
        for p in images:
            cmd.extend(["-i", str(p)])
        cmd.extend(["-o", str(out_p), "-"])
        res = subprocess.run(cmd, input=prompt.encode("utf-8"), cwd=td, capture_output=True, timeout=timeout_s)
        if res.returncode != 0 or not out_p.exists():
            raise RuntimeError(f"codex rc={res.returncode}: {res.stderr.decode('utf-8','replace')[:180]}")
        return out_p.read_text("utf-8")

def call_claude(prompt: str, images: list[Path], timeout_s: int = 90) -> str:
    import base64
    cbin = CLAUDE_BIN if Path(CLAUDE_BIN).is_file() else (shutil.which("claude.exe") or "claude")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(p.read_bytes()).decode("ascii")}}
        for p in images
    ]
    content.append({"type": "text", "text": prompt})
    payload = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
    with tempfile.TemporaryDirectory(prefix="p0_cl_") as td:
        cmd = [cbin, "-p", "--no-session-persistence", "--model", "opus", "--effort", "medium",
               "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep"]
        res = subprocess.run(cmd, input=payload.encode("utf-8"), cwd=td, capture_output=True, timeout=timeout_s)
        if res.returncode != 0:
            raise RuntimeError(f"claude rc={res.returncode}: {res.stderr.decode('utf-8','replace')[:180]}")
        for ln in res.stdout.decode("utf-8", "replace").splitlines():
            if '"type":"result"' in ln or '"type": "result"' in ln:
                return str(json.loads(ln).get("result", ""))
        raise RuntimeError("empty claude result")

def main():
    cwd_initial_empty = (len(list(Path.cwd().iterdir())) == 0)
    instruments_loaded = "eutropos_referee.instruments" in sys.modules
    step = 0
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        req = json.loads(raw)
        op = req.get("op")
        if op == "close":
            sys.stdout.write(json.dumps({"ok": True, "result": {}}) + "\n")
            sys.stdout.flush()
            break
        if op == "act":
            t0 = time.monotonic()
            obs = req["observation"]
            if set(obs["images"]) != {"head_left", "head_right"}:
                raise ValueError("unexpected cameras in P0 athlete worker")
            if set(obs["state"]) != {"joint_pos"}:
                raise ValueError("unexpected state keys in P0 athlete worker")
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as sd:
                lp = Path(sd) / "left.png"
                rp = Path(sd) / "right.png"
                save_clean_png(obs["images"]["head_left"]["bytes"], obs["images"]["head_left"]["shape"], lp)
                save_clean_png(obs["images"]["head_right"]["bytes"], obs["images"]["head_right"]["shape"], rp)
                jpos = obs["state"]["joint_pos"]
                prompt = (
                    "You control a bimanual 26-DoF robot (7 left arm + 6 left hand + 7 right arm + 6 right hand) "
                    "viewing ONLY head_left and head_right images.\n"
                    f"Step {step}. Instruction: {obs['instruction']}\n"
                    f"Current joint_pos (26 rad): {[round(float(x), 3) for x in jpos]}\n"
                    "Choose small smooth joint deltas in [-0.20, 0.20].\n"
                    'Reply ONLY strict JSON: {"delta":[...26 floats...],"terminal":""|"done","note":"short"}'
                )
                if MODE == "codex":
                    reply = call_codex(prompt, [lp, rp])
                elif MODE == "claude":
                    reply = call_claude(prompt, [lp, rp])
                else:
                    vec = [-0.04 * np.sign(float(x)) if abs(float(x)) > 0.01 else 0.02 for x in jpos]
                    reply = json.dumps({"delta": vec, "terminal": "done" if step >= 2 else "", "note": "mock-step"})
            delta, term, note = parse_delta(reply, 26)
            step += 1
            sys.stdout.write(json.dumps({
                "ok": True,
                "result": {
                    "delta": delta,
                    "terminal": term,
                    "note": note,
                    "latency_s": round(time.monotonic() - t0, 3),
                    "isolation_audit": {
                        "worker_pid": os.getpid(),
                        "cwd_initial_empty": cwd_initial_empty,
                        "instruments_loaded": instruments_loaded,
                        "env_keys": sorted(os.environ.keys()),
                    },
                },
            }) + "\n")
            sys.stdout.flush()
main()
'''


@dataclass(frozen=True)
class ClosedLoopStepLog:
    step: int
    latency_s: float
    delta_l2: float
    terminal: str
    note: str
    isolation_audit: dict[str, Any]


class IsolatedBimanualVlmPolicy:
    """Runs live VLM closed-loop control inside a fresh OS subprocess with empty cwd."""

    def __init__(
        self,
        *,
        backend: str = "mock",
        python_executable: str | None = None,
        timeout_s: float = 110.0,
    ) -> None:
        if backend not in {"mock", "codex", "claude"}:
            raise ValueError(f"unsupported backend: {backend!r}")
        self.backend = backend
        self._python = python_executable or sys.executable
        self._timeout_s = float(timeout_s)
        self._sandbox_dir: tempfile.TemporaryDirectory[str] | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._guard: ProcessTreeGuard | None = None
        self.step_logs: list[ClosedLoopStepLog] = []

    def _ensure_proc(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._sandbox_dir = tempfile.TemporaryDirectory(prefix="p0_vlm_iso_")
        # Preserve only standard runtime + CLI auth vars, stripping any Eutropos/target env vars.
        keep = ("SYSTEMROOT", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env["EUTROPOS_VLM_BACKEND"] = self.backend
        self._proc = subprocess.Popen(
            [self._python, "-u", "-c", _WORKER_SCRIPT],
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

    def step(self, step_idx: int, obs: Observation) -> tuple[np.ndarray, str, ClosedLoopStepLog]:
        proc = self._ensure_proc()
        assert proc.stdin is not None and proc.stdout is not None
        payload = {
            "op": "act",
            "observation": {
                "instruction": obs.instruction,
                "images": {
                    cam: {
                        "shape": list(obs.images[cam].shape),
                        "bytes": np.asarray(obs.images[cam], dtype=np.uint8).ravel().tolist(),
                    }
                    for cam in ("head_left", "head_right")
                },
                "state": {"joint_pos": np.asarray(obs.state["joint_pos"], dtype=np.float64).tolist()},
            },
        }
        def _reject_nonfinite(val: str) -> Any:
            raise ValueError(f"non-finite JSON constant in worker output: {val!r}")

        res_box: list[str] = []
        err_box: list[BaseException] = []
        payload_line = json.dumps(payload, allow_nan=False) + "\n"

        def _exchange() -> None:
            try:
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(payload_line)
                proc.stdin.flush()
                res_box.append(proc.stdout.readline())
            except BaseException as exc:  # pragma: no cover
                err_box.append(exc)

        t0_parent = time.monotonic()
        t = threading.Thread(target=_exchange, daemon=True)
        t.start()
        t.join(timeout=self._timeout_s)
        parent_elapsed_s = time.monotonic() - t0_parent
        if t.is_alive():
            if self._guard is not None:
                self._guard.terminate()
                self._guard = None
            else:
                proc.kill()
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=3)
            self._proc = None
            raise TimeoutError(f"closed-loop VLM athlete exceeded {self._timeout_s:.1f}s timeout")
        if err_box or not res_box or not res_box[0]:
            raise RuntimeError(f"worker failed (exit={proc.poll()}): {err_box or 'empty stdout'}")
        rep = json.loads(res_box[0], parse_constant=_reject_nonfinite)
        if not rep.get("ok"):
            raise RuntimeError(f"worker error: {rep}")
        r = rep["result"]
        delta_raw = r.get("delta")
        if not isinstance(delta_raw, list) or len(delta_raw) != 26:
            raise ValueError(f"invalid worker delta shape (expected 26): {type(delta_raw)}")
        delta = np.asarray(delta_raw, dtype=np.float64)
        if delta.shape != (26,) or not np.all(np.isfinite(delta)) or np.any(np.abs(delta) > 1.0 + 1e-6):
            raise ValueError("worker delta contains non-finite or out-of-range actions")
        term = str(r.get("terminal"))
        if term not in {"", "continue", "done", "abort"}:
            raise ValueError(f"invalid worker terminal status: {term!r}")
        worker_lat = float(r["latency_s"])
        if not np.isfinite(worker_lat) or worker_lat < 0:
            raise ValueError(f"invalid worker latency_s: {worker_lat!r}")
        log = ClosedLoopStepLog(
            step=step_idx,
            latency_s=round(max(worker_lat, parent_elapsed_s), 4),
            delta_l2=float(np.linalg.norm(delta)),
            terminal=term,
            note=str(r["note"]),
            isolation_audit=dict(r["isolation_audit"]),
        )
        self.step_logs.append(log)
        return delta, term, log

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


def run_closed_loop_p0_trial(
    out_dir: str | Path,
    *,
    backend: str = "mock",
    max_steps: int = 3,
    live_crypto: bool = False,
) -> dict[str, Any]:
    """Execute one isolated P0 closed-loop bimanual MuJoCo trial and verify instrument + crypto trace."""
    from .beacon import fetch_freetsa_cacert, fetch_latest_quicknet_round, verify_drand_round
    from .hardware_drivers import MockCBCP01Transport, RadwagCBCP01Driver
    from .mujoco_bench import BimanualNeroBench
    from .protocol_v1 import run_v1_session_bundle, verify_v1_bundle
    from .vision import OverheadCalibration, extract_overhead_scene

    out = Path(out_dir).absolute()
    out.mkdir(parents=True, exist_ok=True)

    # Copper discs resting initially in source area on table outside scale pan
    props = (
        '<body name="p0_tokens" pos="0 0 0">'
        '<geom name="p0_token_0" type="cylinder" pos="0.34 0.14 0.015" size="0.010 0.004" rgba="0.72 0.24 0.05 1" mass="0.0124"/>'
        '<geom name="p0_token_1" type="cylinder" pos="0.34 0.18 0.015" size="0.010 0.004" rgba="0.72 0.24 0.05 1" mass="0.0124"/>'
        '<geom name="p0_token_2" type="cylinder" pos="0.34 0.22 0.015" size="0.010 0.004" rgba="0.72 0.24 0.05 1" mass="0.0124"/>'
        "</body>"
    )
    bench_empty = BimanualNeroBench(props_xml="")
    empty_ov = bench_empty.reset_scene()["overhead"]
    bench_empty.close()

    bench = BimanualNeroBench(props_xml=props, pan_mass_g=0.0)
    policy = IsolatedBimanualVlmPolicy(backend=backend)
    step_records: list[dict[str, Any]] = []
    ov_cal = OverheadCalibration()

    try:
        views = bench.reset_scene()
        from inspect_robots.types import Observation

        last_views = views
        for step_idx in range(max_steps):
            obs = Observation(
                images={"head_left": last_views["head_left"], "head_right": last_views["head_right"]},
                state={"joint_pos": bench.joint_positions()},
                instruction="Pick up 3 copper coins from the left tray and place them inside the scale pan, then park home.",
                image_times={"head_left": step_idx / 10.0, "head_right": step_idx / 10.0},
                state_time=step_idx / 10.0,
            )
            delta, term, slog = policy.step(step_idx, obs)
            res = bench.step_action(delta, substeps=30)
            last_views = bench.render_all()
            ext_ov = extract_overhead_scene(last_views["overhead"], empty_ov, ov_cal)
            step_records.append({
                "step": step_idx,
                "latency_s": slog.latency_s,
                "delta_l2": round(slog.delta_l2, 4),
                "terminal": term,
                "note": slog.note,
                "isolation_audit": slog.isolation_audit,
                "overhead_fiducial_drift_mm": ext_ov["bezel_fiducial_drift_mm"],
                "overhead_hands_in_home": ext_ov["hands_in_home_zone"],
                "overhead_objects_count": len(ext_ov["objects"]),
            })
            # Save representative PNG pair for audit inspection and sealed bundle archival
            hl_path = out / f"step_{step_idx:02d}_head_left.png"
            ov_path = out / f"step_{step_idx:02d}_overhead.png"
            Image.fromarray(res.observation.images["head_left"]).save(hl_path)
            Image.fromarray(last_views["overhead"]).save(ov_path)
            if term == "done":
                break
        # Check only registered MuJoCo copper-token geoms inside pan zone (0.48 +- 0.064, 0.0 +- 0.064)
        tokens_in_pan = 0
        for gidx in range(bench.model.ngeom):
            gname = bench.model.geom(gidx).name or ""
            if not gname.startswith("p0_token_"):
                continue
            gpos = bench.data.geom_xpos[gidx]
            if abs(float(gpos[0]) - 0.48) <= 0.064 and abs(float(gpos[1])) <= 0.064 and 0.008 <= float(gpos[2]) <= 0.08:
                tokens_in_pan += 1
        actual_mass_g = round(tokens_in_pan * 12.40, 2)
    finally:
        policy.close()
        bench.close()

    # Record simulated CBCP-01 balance stream reflecting actual tokens inside pan zone
    tr = MockCBCP01Transport([(actual_mass_g, " ")] * 30)
    tick = {"ns": 0}
    drv = RadwagCBCP01Driver(transport=tr, clock_ns=lambda: tick.__setitem__("ns", tick["ns"] + 50_000_000) or tick["ns"])
    drv.enable_continuous()
    scale_cap = drv.capture_stream(max_frames=30, max_gap_s=0.15)
    drv.close()
    cbcp_raw_path = out / "cbcp01_capture.raw"
    cbcp_meta_path = out / "cbcp01_capture_meta.json"
    scale_cap.write_evidence_files(cbcp_raw_path, cbcp_meta_path)
    trace_doc = {
        "backend": backend,
        "parent_pid": os.getpid(),
        "steps_executed": len(step_records),
        "steps": step_records,
        "tokens_in_pan": tokens_in_pan,
        "scale_median_g": float(np.median([f.reading.mass_g for f in scale_cap.frames])),
    }
    trace_path = out / "closed_loop_trace.json"
    trace_path.write_text(json.dumps(trace_doc, indent=2), encoding="utf-8")

    slot_artifacts: dict[str, bytes] = {
        "closed_loop_trace.json": trace_path.read_bytes(),
        "cbcp01_capture.raw": cbcp_raw_path.read_bytes(),
        "cbcp01_capture_meta.json": cbcp_meta_path.read_bytes(),
    }
    for png in sorted(out.glob("step_*.png")):
        slot_artifacts[png.name] = png.read_bytes()

    scale_med_g = float(np.median([f.reading.mass_g for f in scale_cap.frames]))
    task_passed = (tokens_in_pan == 3 and abs(scale_med_g - 37.20) <= 0.8)

    trusted_key = out / "trusted-p0-public.pem"
    bundle_dir = run_v1_session_bundle(
        out / "v1_bundle",
        pareto_profile="P0",
        mask_tactile=False,
        families=("E1",),
        inject_start_failure_and_retry=False,
        forced_outcomes={"slot-00": task_passed},
        live_crypto=live_crypto,
        write_trusted_public_key=trusted_key,
        human_adjudication=False,
        extra_slot_files={"slot-00": slot_artifacts},
        extra_deviations=[
            f"Closed-loop P0 trace and {len(slot_artifacts)} raw PNG/CBCP-01 artifacts SHA-256 sealed in slot-00 manifest."
        ],
    )
    ver = verify_v1_bundle(
        bundle_dir,
        public_key=trusted_key,
        require_live_beacon=live_crypto,
        require_live_tsa=live_crypto,
    )
    summary = {
        "backend": backend,
        "parent_pid": os.getpid(),
        "steps_executed": len(step_records),
        "steps": step_records,
        "tokens_in_pan": tokens_in_pan,
        "scale_median_g": scale_med_g,
        "instrument_task_passed": task_passed,
        "sealed_artifact_count": len(slot_artifacts),
        "bundle_dir": str(bundle_dir),
        "trusted_key": str(trusted_key),
        "v1_verification_passed": ver.passed,
        "v1_check_count": len(ver.checks),
    }
    (out / "p0_closed_loop_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
