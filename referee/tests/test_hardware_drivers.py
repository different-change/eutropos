"""Tests for Day-1 Radwag CBCP-01 serial driver, camera homography calibration, and pre-trial checks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from eutropos_referee.calibration import (
    calibrate_overhead_homography,
    generate_calibration_board,
    measure_fiducial_drift_mm,
    pre_trial_bench_check,
)
from eutropos_referee.cli import main as cli_main
from eutropos_referee.hardware_drivers import (
    MockCBCP01Transport,
    OverheadCameraDriver,
    RadwagCBCP01Driver,
)
from eutropos_referee.instruments import evaluate_scale_stream


def test_radwag_cbcp01_commands_gaps_and_malformed_frames(tmp_path: Path) -> None:
    readings = [(0.0, " ")] * 5 + [(37.20, " ")] * 25
    tr = MockCBCP01Transport(readings, tare_g=10.0, inject_malformed_at={2})
    # Fake monotonic clock: 0.05s normally, 0.30s jump at call 10
    step = {"i": 0, "ns": 1_000_000_000}

    def fake_clock() -> int:
        step["i"] += 1
        step["ns"] += 300_000_000 if step["i"] == 10 else 50_000_000
        return step["ns"]

    drv = RadwagCBCP01Driver(port="mock://", transport=tr, clock_ns=fake_clock)
    assert drv.read_tare() == 10.0
    drv.set_tare(0.0)
    assert drv.read_tare() == 0.0
    drv.enable_continuous()
    assert drv.poll_once().mass_g == 0.0

    cap = drv.capture_stream(max_frames=31, max_gap_s=0.15)
    drv.disable_continuous()
    drv.close()

    assert tr.closed is True
    assert len(cap.malformed_frames) == 1
    assert len(cap.clock_gaps) == 1
    assert cap.clock_gaps[0]["gap_s"] >= 0.25
    assert len(cap.samples) == 30

    scale_file = tmp_path / "cap_scale.txt"
    meta_file = tmp_path / "cap_meta.json"
    cap.write_evidence_files(scale_file, meta_file)
    assert scale_file.read_bytes() == cap.raw_bytes
    assert json.loads(meta_file.read_text(encoding="utf-8"))["frame_count"] == 30

    # Clean settled capture without gaps feeds evaluate_scale_stream directly
    tr_clean = MockCBCP01Transport([(37.20, " ")] * 30)
    tick = {"ns": 0}

    def uniform_clock() -> int:
        tick["ns"] += 50_000_000
        return tick["ns"]

    drv_clean = RadwagCBCP01Driver(transport=tr_clean, clock_ns=uniform_clock)
    drv_clean.enable_continuous()
    cap_clean = drv_clean.capture_stream(max_frames=30, max_gap_s=0.15)
    drv_clean.close()
    res = evaluate_scale_stream(cap_clean.samples, target_net_g=37.20, tolerance_g=0.5, settle_window_s=1.0)
    assert res.passed, res.reasons


def test_calibration_homography_drift_and_precheck(tmp_path: Path) -> None:
    board = generate_calibration_board(tmp_path / "board.png", width_px=800, height_px=800)
    rgb = np.asarray(Image.open(board.png_path).convert("RGB"), dtype=np.uint8)
    hom = calibrate_overhead_homography(rgb)
    assert hom.reprojection_rmse_mm < 0.2
    assert 2.9 <= hom.pixels_per_mm <= 3.3
    assert measure_fiducial_drift_mm(rgb, hom) < 0.05

    # Shift image by 8 px (~2.6 mm) and confirm drift detection exceeds 0.5 mm bezel threshold
    shifted = np.roll(rgb, shift=8, axis=1)
    assert measure_fiducial_drift_mm(shifted, hom) > 2.0

    # Pre-trial bench check passes on settled zero balance + unshifted illuminated board
    clk = {"ns": 0}

    def fast_clk() -> int:
        clk["ns"] += 50_000_000
        return clk["ns"]

    scale_ok = RadwagCBCP01Driver(transport=MockCBCP01Transport([(0.01, " ")] * 6), clock_ns=fast_clk)
    scale_ok.enable_continuous()
    cam_ok = OverheadCameraDriver(backend="mock", frame_provider=lambda _i: rgb)
    pre_ok = pre_trial_bench_check(scale_driver=scale_ok, camera_driver=cam_ok, calibration=hom)
    scale_ok.close()
    cam_ok.close()
    assert pre_ok.passed, pre_ok.reasons

    # Pre-trial check fails cleanly on non-zeroed scale or shifted camera
    scale_bad = RadwagCBCP01Driver(transport=MockCBCP01Transport([(4.5, " ")] * 6), clock_ns=fast_clk)
    scale_bad.enable_continuous()
    cam_bad = OverheadCameraDriver(backend="mock", frame_provider=lambda _i: shifted)
    pre_bad = pre_trial_bench_check(scale_driver=scale_bad, camera_driver=cam_bad, calibration=hom)
    scale_bad.close()
    cam_bad.close()
    assert not pre_bad.passed
    assert len(pre_bad.reasons) >= 2


def test_cli_calibrate_and_bench_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc1 = cli_main([
        "calibrate",
        "--board-png", str(tmp_path / "cli_board.png"),
        "--out-json", str(tmp_path / "cal.json"),
    ])
    assert rc1 == 0
    cal = json.loads((tmp_path / "cal.json").read_text(encoding="utf-8"))
    assert cal["reprojection_rmse_mm"] < 0.2

    capsys.readouterr()
    rc2 = cli_main(["bench-check", "--port", "mock://", "--board-png", str(tmp_path / "cli_board.png")])
    assert rc2 == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["passed"] is True
    assert (tmp_path / "cli_board.png").is_file()
