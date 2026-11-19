"""Overhead camera planar homography calibration, drift measurement, and pre-trial bench checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .hardware_drivers import OverheadCameraDriver, RadwagCBCP01Driver
from .instruments import parse_si_frame

DEFAULT_WORLD_FIDUCIALS_MM = (
    (-105.0, -105.0),
    (105.0, -105.0),
    (-105.0, 105.0),
    (105.0, 105.0),
)


@dataclass(frozen=True)
class CalibrationBoardSpec:
    png_path: Path
    width_px: int
    height_px: int
    board_span_mm: float
    world_fiducials_mm: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class HomographyCalibration:
    h_px_to_mm: list[list[float]]
    h_mm_to_px: list[list[float]]
    reference_fiducials_px: list[list[float]]
    reference_fiducials_mm: list[list[float]]
    reprojection_rmse_mm: float
    pixels_per_mm: float


@dataclass(frozen=True)
class BenchPrecheckReport:
    passed: bool
    reasons: tuple[str, ...]
    tare_zero_median_g: float | None
    bezel_drift_mm: float | None
    mean_luma: float
    clock_gap_count: int


def generate_calibration_board(
    out_path: str | Path,
    *,
    width_px: int = 800,
    height_px: int = 800,
    board_span_mm: float = 260.0,
) -> CalibrationBoardSpec:
    """Render printable 4-fiducial + inner 6x6 checkerboard target PNG."""
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width_px, height_px), (236, 236, 232))
    draw = ImageDraw.Draw(img)
    ppm = width_px / board_span_mm
    cx, cy = width_px / 2.0, height_px / 2.0

    def mm_to_px(x_mm: float, y_mm: float) -> tuple[float, float]:
        return cx + x_mm * ppm, cy + y_mm * ppm

    # Scale pan outline 128 x 128 mm + inner 6x6 checkerboard (96 x 96 mm)
    px0, py0 = mm_to_px(-64.0, -64.0)
    px1, py1 = mm_to_px(64.0, 64.0)
    draw.rectangle([px0, py0, px1, py1], outline=(40, 40, 40), width=3)
    cell_mm = 16.0
    for r in range(6):
        for c in range(6):
            if (r + c) % 2 == 0:
                x0, y0 = mm_to_px(-48.0 + c * cell_mm, -48.0 + r * cell_mm)
                x1, y1 = mm_to_px(-48.0 + (c + 1) * cell_mm, -48.0 + (r + 1) * cell_mm)
                draw.rectangle([x0, y0, x1, y1], fill=(22, 24, 28))

    # Draw 4 cyan corner fiducials at +-105 mm (14 x 14 mm squares)
    for fx, fy in DEFAULT_WORLD_FIDUCIALS_MM:
        x0, y0 = mm_to_px(fx - 7.0, fy - 7.0)
        x1, y1 = mm_to_px(fx + 7.0, fy + 7.0)
        draw.rectangle([x0, y0, x1, y1], fill=(0, 235, 242), outline=(0, 80, 90), width=2)

    img.save(dest, format="PNG")
    return CalibrationBoardSpec(
        png_path=dest,
        width_px=width_px,
        height_px=height_px,
        board_span_mm=board_span_mm,
        world_fiducials_mm=DEFAULT_WORLD_FIDUCIALS_MM,
    )


def detect_fiducial_centroids_px(rgb: np.ndarray) -> np.ndarray:
    """Detect 4 cyan corner fiducials ordered (-X,-Y), (+X,-Y), (-X,+Y), (+X,+Y) in image space."""
    arr = np.asarray(rgb, dtype=np.uint8)
    r = arr[..., 0].astype(np.int16)
    g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16)
    mask = ((b > 170) & (g > 170) & (r < 95)).astype(np.uint8) * 255
    num, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps: list[tuple[float, float, int]] = []
    for lbl in range(1, num):
        area = int(stats[lbl, cv2.CC_STAT_AREA])
        if area >= 6:
            cx, cy = float(centroids[lbl, 0]), float(centroids[lbl, 1])
            comps.append((cx, cy, area))
    if len(comps) != 4:
        raise ValueError(f"expected exactly 4 cyan corner fiducials, detected {len(comps)}")
    top4 = sorted(comps, key=lambda c: c[2], reverse=True)
    pts = np.asarray([(c[0], c[1]) for c in top4], dtype=np.float64)
    # Assign to corners cleanly: split top vs bottom by y, then left vs right by x
    by_y = pts[np.argsort(pts[:, 1])]
    top_pair = by_y[:2][np.argsort(by_y[:2, 0])]
    bot_pair = by_y[2:][np.argsort(by_y[2:, 0])]
    return np.vstack([top_pair[0], top_pair[1], bot_pair[0], bot_pair[1]])


def apply_homography(points_xy: np.ndarray, h: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_xy, dtype=np.float64).reshape(-1, 2)
    h_arr = np.asarray(h, dtype=np.float64)
    if h_arr.shape != (3, 3) or not np.all(np.isfinite(h_arr)):
        raise ValueError("homography matrix must be finite 3x3")
    if not np.all(np.isfinite(pts)):
        raise ValueError("input points must be finite")
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    hom = np.hstack([pts, ones])
    proj = (h_arr @ hom.T).T
    w = proj[:, 2:3]
    if not np.all(np.isfinite(w)) or np.any(np.abs(w) < 1e-12):
        raise ValueError("degenerate projective denominator during homography transform")
    out = proj[:, :2] / w
    if not np.all(np.isfinite(out)):
        raise ValueError("non-finite coordinates produced by homography transform")
    return out


def calibrate_overhead_homography(
    rgb: np.ndarray,
    *,
    world_fiducials_mm: tuple[tuple[float, float], ...] = DEFAULT_WORLD_FIDUCIALS_MM,
    extra_px: np.ndarray | None = None,
    extra_mm: np.ndarray | None = None,
) -> HomographyCalibration:
    """Solve planar px -> mm homography via OpenCV and return reprojection RMSE."""
    src_pts = detect_fiducial_centroids_px(rgb)
    dst_pts = np.asarray(world_fiducials_mm, dtype=np.float64)
    if src_pts.shape != (4, 2) or dst_pts.shape != (4, 2):
        raise ValueError("exact 4 fiducial correspondence pairs required")
    all_src = src_pts if extra_px is None else np.vstack([src_pts, extra_px])
    all_dst = dst_pts if extra_mm is None else np.vstack([dst_pts, extra_mm])
    h_fwd, _ = cv2.findHomography(all_src, all_dst, method=0)
    h_inv, _ = cv2.findHomography(all_dst, all_src, method=0)
    if h_fwd is None or h_inv is None or not np.isfinite(h_fwd).all():
        raise ValueError("homography computation failed")
    pred_mm = apply_homography(all_src, h_fwd)
    errs = np.linalg.norm(pred_mm - all_dst, axis=1)
    rmse = float(np.sqrt(np.mean(errs**2)))

    # Average px/mm scale from top and left fiducial spans
    world_span_x = abs(dst_pts[1, 0] - dst_pts[0, 0])
    world_span_y = abs(dst_pts[2, 1] - dst_pts[0, 1])
    px_span_x = float(np.linalg.norm(src_pts[1] - src_pts[0]))
    px_span_y = float(np.linalg.norm(src_pts[2] - src_pts[0]))
    ppm = float(0.5 * (px_span_x / max(world_span_x, 1e-6) + px_span_y / max(world_span_y, 1e-6)))
    return HomographyCalibration(
        h_px_to_mm=h_fwd.tolist(),
        h_mm_to_px=h_inv.tolist(),
        reference_fiducials_px=src_pts.tolist(),
        reference_fiducials_mm=dst_pts.tolist(),
        reprojection_rmse_mm=round(rmse, 6),
        pixels_per_mm=round(ppm, 6),
    )


def measure_fiducial_drift_mm(rgb: np.ndarray, calibration: HomographyCalibration) -> float:
    """Measure max fiducial centroid shift in mm relative to calibrated world coordinates."""
    cur_px = detect_fiducial_centroids_px(rgb)
    h = np.asarray(calibration.h_px_to_mm, dtype=np.float64)
    cur_mm = apply_homography(cur_px, h)
    ref_mm = np.asarray(calibration.reference_fiducials_mm, dtype=np.float64)
    if ref_mm.shape != cur_mm.shape or not np.all(np.isfinite(ref_mm)):
        raise ValueError("invalid or non-finite reference fiducial coordinates")
    dists = np.linalg.norm(cur_mm - ref_mm, axis=1)
    if not np.all(np.isfinite(dists)):
        raise ValueError("non-finite fiducial drift computed")
    return float(np.max(dists))


def pre_trial_bench_check(
    *,
    scale_driver: RadwagCBCP01Driver,
    camera_driver: OverheadCameraDriver,
    calibration: HomographyCalibration,
    empty_pan_threshold_g: float = 0.05,
    max_bezel_drift_mm: float = 0.5,
    min_luma: float = 60.0,
) -> BenchPrecheckReport:
    """Run physical pre-trial balance zero, clock-gap, lighting, and fiducial drift checks."""
    reasons: list[str] = []
    cap = scale_driver.capture_stream(max_frames=5, max_gap_s=0.15)
    if cap.clock_gaps:
        reasons.append(f"detected {len(cap.clock_gaps)} scale clock gaps > 0.15s")
    if cap.nonmonotonic_clocks:
        reasons.append(f"detected {len(cap.nonmonotonic_clocks)} non-monotonic scale clock readings")
    if cap.timeout_count:
        reasons.append(f"detected {cap.timeout_count} scale serial timeouts")
    if cap.malformed_frames:
        reasons.append(f"detected {len(cap.malformed_frames)} malformed CBCP-01 frames")
    masses = [parse_si_frame(s.raw) for s in cap.samples]
    if len(masses) < 5:
        reasons.append(f"expected 5 valid scale frames, received {len(masses)}")
    if not masses:
        tare_med = None
    else:
        tare_med = float(np.median([m.mass_g for m in masses]))
        if not np.isfinite(tare_med):
            reasons.append("non-finite balance median mass")
        elif abs(tare_med) > empty_pan_threshold_g:
            reasons.append(f"scale zero/tare offset {tare_med:.3f} g exceeds {empty_pan_threshold_g:.3f} g")
        if any(m.stability != " " for m in masses):
            reasons.append("unstable balance reading during idle check")

    frame = camera_driver.grab_frame(0)
    mean_luma = float(np.mean(frame.rgb))
    if mean_luma < min_luma:
        reasons.append(f"overhead illumination {mean_luma:.1f} below {min_luma:.1f}")
    drift_mm: float | None = None
    try:
        drift_mm = measure_fiducial_drift_mm(frame.rgb, calibration)
        if not np.isfinite(drift_mm):
            reasons.append("non-finite bezel fiducial drift")
        elif drift_mm > max_bezel_drift_mm:
            reasons.append(f"bezel fiducial drift {drift_mm:.3f} mm exceeds {max_bezel_drift_mm:.3f} mm")
    except ValueError as exc:
        reasons.append(str(exc))

    return BenchPrecheckReport(
        passed=not reasons,
        reasons=tuple(reasons),
        tare_zero_median_g=round(tare_med, 4) if (tare_med is not None and np.isfinite(tare_med)) else None,
        bezel_drift_mm=round(drift_mm, 4) if (drift_mm is not None and np.isfinite(drift_mm)) else None,
        mean_luma=round(mean_luma, 2),
        clock_gap_count=len(cap.clock_gaps),
    )
