"""Release 1.0.0 verification tests: ProcessTreeGuard, authentic P0 artifact sealing, and version check."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from eutropos_referee import __version__
from eutropos_referee.manifest import read_json
from eutropos_referee.proc_sandbox import ProcessTreeGuard, popen_session_kwargs
from eutropos_referee.protocol_v1 import run_v1_session_bundle, verify_v1_bundle


def test_version_is_100() -> None:
    assert __version__ == "1.0.0"


def test_process_tree_guard_kills_worker_and_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"open(r'{pid_file}', 'w').write(str(p.pid)); "
        "sys.stdout.write('READY\\n'); sys.stdout.flush(); time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_session_kwargs(),
    )
    guard = ProcessTreeGuard(proc)
    try:
        assert proc.stdout is not None
        ready = proc.stdout.readline().strip()
        assert ready == "READY"
        grand_pid = int(pid_file.read_text(encoding="utf-8").strip())
        guard.terminate()
        proc.wait(timeout=3)
        assert proc.poll() is not None
        if guard.attached:
            # Verify descendant process also terminated cleanly
            time.sleep(0.15)
            if sys.platform == "win32":
                chk = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {grand_pid}", "/NH"],
                    capture_output=True, text=True, check=False,
                )
                assert str(grand_pid) not in chk.stdout
    finally:
        guard.terminate()


def test_extra_slot_artifacts_are_hashed_and_tamper_checked(tmp_path: Path) -> None:
    pub = tmp_path / "pub.pem"
    ev = run_v1_session_bundle(
        tmp_path / "ev",
        families=("E1",),
        inject_start_failure_and_retry=False,
        write_trusted_public_key=pub,
        extra_slot_files={
            "slot-00": {
                "trace.json": b'{"step":0}',
                "frames/cam.bin": b"RAW_FRAME_BYTES_V100",
            }
        },
        extra_deviations=["Sealed test artifact trace included."],
    )
    assert verify_v1_bundle(ev, public_key=pub).passed
    m0 = read_json(ev / "manifests" / "trial_0000.json", canonical=True)
    sealed_paths = {e["path"] for e in m0["files"]}
    assert any(p.endswith("artifacts/20261119_v1_run/slot-00-slot-00-attempt-0/trace.json") for p in sealed_paths)
    assert any(p.endswith("artifacts/20261119_v1_run/slot-00-slot-00-attempt-0/frames/cam.bin") for p in sealed_paths)

    cam_file = next(ev.rglob("cam.bin"))
    cam_file.write_bytes(b"TAMPERED_BYTES_00000")
    rep_bad = verify_v1_bundle(ev, public_key=pub)
    assert not rep_bad.passed
    assert any("file_sha256" in f for f in rep_bad.failures)


def test_p0_closed_loop_seals_authentic_artifacts(tmp_path: Path) -> None:
    pytest.importorskip("mujoco")
    from eutropos_referee.vlm_policy import run_closed_loop_p0_trial

    res = run_closed_loop_p0_trial(tmp_path / "p0_sealed", backend="mock", max_steps=2, live_crypto=False)
    assert res["v1_verification_passed"] is True
    assert res["sealed_artifact_count"] >= 7  # trace + cbcp01 raw/meta + 2*(head_left+overhead)
    bdir = Path(res["bundle_dir"])
    tkey = Path(res["trusted_key"])
    sealed_pngs = list(bdir.rglob("step_00_head_left.png"))
    assert len(sealed_pngs) == 1
    assert list(bdir.rglob("cbcp01_capture.raw"))
    assert list(bdir.rglob("closed_loop_trace.json"))

    # Tampering one byte inside sealed PNG breaks bundle verification
    sealed_pngs[0].write_bytes(b"corrupt-png-bytes")
    rep_bad = verify_v1_bundle(bdir, public_key=tkey)
    assert not rep_bad.passed
    assert any("file_sha256" in f for f in rep_bad.failures)
