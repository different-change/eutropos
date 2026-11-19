"""Pixel-to-object overhead vision extraction for calibrated bench imagery."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


@dataclass(frozen=True)
class OverheadCalibration:
    width_px: int = 240
    height_px: int = 240
    mm_per_px: float = 1.0
    origin_px: tuple[float, float] = (120.0, 120.0)
    pan_bounds_mm: tuple[float, float, float, float] = (-64.0, -64.0, 64.0, 64.0)
    home_margin_px: int = 18
    fiducial_patches: tuple[tuple[int, int, int, int], ...] = (
        (2, 2, 22, 22),
        (218, 2, 238, 22),
        (2, 218, 22, 238),
        (218, 218, 238, 238),
    )


def _validate_rgb(img: np.ndarray) -> np.ndarray:
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise ValueError("overhead frame must be uint8 (H, W, 3) RGB")
    return arr


def _classify_color(rgb_mean: np.ndarray) -> str:
    r, g, b = float(rgb_mean[0]), float(rgb_mean[1]), float(rgb_mean[2])
    if r > 125 and g > 125 and b < 110 and abs(r - g) < 40 and (min(r, g) - b) > 55:
        return "yellow"
    if r > 110 and (r - b) > 55 and 0.35 * r <= g <= 0.78 * r:
        return "copper"
    if (r - max(g, b)) > 55 and r > 115:
        return "red"
    if (b - r) > 45 and b > 105:
        return "blue"
    if (g - max(r, b)) > 40 and g > 105:
        return "green"
    if r > 175 and g > 175 and b > 175 and max(r, g, b) - min(r, g, b) < 35:
        return "white"
    return "neutral"


def _measure_fiducial_drift_mm(
    rgb: np.ndarray, baseline: np.ndarray, cal: OverheadCalibration
) -> float:
    drifts: list[float] = []
    for x0, y0, x1, y1 in cal.fiducial_patches:
        p_cur = rgb[y0:y1, x0:x1].astype(np.float64)
        p_base = baseline[y0:y1, x0:x1].astype(np.float64)
        # Fiducials are bright cyan/white corner squares against dark apron.
        w_cur = np.clip(p_cur[:, :, 1] + p_cur[:, :, 2] - 0.5 * p_cur[:, :, 0] - 120.0, 0.0, None)
        w_base = np.clip(p_base[:, :, 1] + p_base[:, :, 2] - 0.5 * p_base[:, :, 0] - 120.0, 0.0, None)
        if w_cur.sum() < 1e-6 or w_base.sum() < 1e-6:
            return 99.0
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cx_c, cy_c = float((xx * w_cur).sum() / w_cur.sum()), float((yy * w_cur).sum() / w_cur.sum())
        cx_b, cy_b = float((xx * w_base).sum() / w_base.sum()), float((yy * w_base).sum() / w_base.sum())
        drifts.append(float(np.hypot(cx_c - cx_b, cy_c - cy_b) * cal.mm_per_px))
    return round(float(max(drifts)) if drifts else 0.0, 4)


def _connected_components(mask: np.ndarray, *, min_pixels: int = 9) -> list[np.ndarray]:
    h, w = mask.shape
    visited = np.zeros((h, w), dtype=bool)
    components: list[np.ndarray] = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if visited[sy, sx]:
            continue
        queue: deque[tuple[int, int]] = deque([(sy, sx)])
        visited[sy, sx] = True
        pixels: list[tuple[int, int]] = []
        while queue:
            cy, cx = queue.popleft()
            pixels.append((cy, cx))
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
        if len(pixels) >= min_pixels:
            components.append(np.asarray(pixels, dtype=np.int64))
    return components


def extract_overhead_scene(
    rgb_uint8: np.ndarray,
    baseline_rgb: np.ndarray,
    calibration: OverheadCalibration = OverheadCalibration(),
    *,
    diff_threshold: float = 24.0,
    min_pixels: int = 12,
) -> dict[str, Any]:
    """Extract bezel drift, home-zone clearance, and object geometry from raw overhead RGB."""
    rgb = _validate_rgb(rgb_uint8)
    base = _validate_rgb(baseline_rgb)
    if rgb.shape != base.shape:
        raise ValueError("overhead and baseline image shapes differ")
    h, w, _ = rgb.shape

    drift_mm = _measure_fiducial_drift_mm(rgb, base, calibration)

    # Mask outside fiducial patches cleanly when diffing against baseline scene.
    diff = np.linalg.norm(rgb.astype(np.float64) - base.astype(np.float64), axis=2)
    fg = diff >= diff_threshold
    for x0, y0, x1, y1 in calibration.fiducial_patches:
        fg[max(0, y0 - 2):min(h, y1 + 2), max(0, x0 - 2):min(w, x1 + 2)] = False

    # Home-zone violation if arm/hand grey-orange intrusion crosses inner border margin.
    m = calibration.home_margin_px
    border_intrusion = bool(
        fg[:m, :].any() or fg[h - m:, :].any() or fg[:, :m].any() or fg[:, w - m:].any()
    )
    interior = fg.copy()
    interior[:m, :] = False
    interior[h - m:, :] = False
    interior[:, :m] = False
    interior[:, w - m:] = False

    ox, oy = calibration.origin_px
    scale = calibration.mm_per_px
    comps = _connected_components(interior, min_pixels=min_pixels)

    extracted: list[dict[str, Any]] = []
    hand_detected_inside = False
    for idx, pix in enumerate(comps):
        comp_rgb = rgb[pix[:, 0], pix[:, 1]]
        bright = comp_rgb[comp_rgb.max(axis=1) > 75]
        rep_rgb = np.median(bright if len(bright) > 0 else comp_rgb, axis=0)
        color = _classify_color(rep_rgb)
        py0, px0 = int(pix[:, 0].min()), int(pix[:, 1].min())
        py1, px1 = int(pix[:, 0].max()) + 1, int(pix[:, 1].max()) + 1
        bbox_area_px = max(1, (py1 - py0) * (px1 - px0))
        fill_ratio = round(float(len(pix) / bbox_area_px), 4)
        # Detect thin/slanted hand intrusion (very large elongated dark/grey arm segment or magenta hand tag).
        if float(rep_rgb[0]) > 145 and float(rep_rgb[2]) > 145 and float(rep_rgb[1]) < 95:
            hand_detected_inside = True
            continue
        x0_mm = round((px0 - ox) * scale, 2)
        y0_mm = round((py0 - oy) * scale, 2)
        x1_mm = round((px1 - ox) * scale, 2)
        y1_mm = round((py1 - oy) * scale, 2)
        cx_mm = round((float(pix[:, 1].mean()) - ox) * scale, 2)
        cy_mm = round((float(pix[:, 0].mean()) - oy) * scale, 2)
        # Principal orientation via covariance of pixel coordinates.
        centered = pix.astype(np.float64) - pix.mean(axis=0)
        cov = np.cov(centered.T) if len(pix) > 2 else np.eye(2)
        eigvals, eigvecs = np.linalg.eigh(cov)
        major = eigvecs[:, int(np.argmax(eigvals))]
        angle_deg = round(float(np.degrees(np.arctan2(major[0], major[1]))), 2)
        intact = fill_ratio >= 0.45 and len(pix) >= min_pixels
        extracted.append({
            "id": f"obj-{idx}",
            "kind": "extracted",
            "color": color,
            "centroid_xy_mm": [cx_mm, cy_mm],
            "bounds_mm": [x0_mm, y0_mm, x1_mm, y1_mm],
            "area_mm2": round(float(len(pix) * scale * scale), 2),
            "flatness_ratio": fill_ratio,
            "orientation_deg": angle_deg,
            "intact": intact,
        })

    return {
        "coordinate_frame": "bench-mm",
        "bezel_fiducial_drift_mm": drift_mm,
        "hands_in_home_zone": not (border_intrusion or hand_detected_inside),
        "objects": extracted,
    }


def render_synthetic_overhead(
    objects: list[dict[str, Any]],
    calibration: OverheadCalibration = OverheadCalibration(),
    *,
    drift_px: tuple[float, float] = (0.0, 0.0),
    hand_intrusion: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Render matching baseline and scene overhead RGB images for deterministic tests."""
    h, w = calibration.height_px, calibration.width_px
    ox, oy = calibration.origin_px
    inv = 1.0 / calibration.mm_per_px

    def _base(dx: float, dy: float) -> Image.Image:
        img = Image.new("RGB", (w, h), (26, 28, 32))
        draw = ImageDraw.Draw(img)
        # Draw pan bezel rectangle
        px0 = ox + calibration.pan_bounds_mm[0] * inv
        py0 = oy + calibration.pan_bounds_mm[1] * inv
        px1 = ox + calibration.pan_bounds_mm[2] * inv
        py1 = oy + calibration.pan_bounds_mm[3] * inv
        draw.rectangle([px0, py0, px1, py1], fill=(40, 44, 50), outline=(85, 90, 96))
        for fx0, fy0, fx1, fy1 in calibration.fiducial_patches:
            cx, cy = (fx0 + fx1) / 2.0, (fy0 + fy1) / 2.0
            draw.rectangle(
                [cx - 4 + dx, cy - 4 + dy, cx + 4 + dx, cy + 4 + dy],
                fill=(0, 235, 240),
            )
        return img

    baseline = np.asarray(_base(0.0, 0.0), dtype=np.uint8)
    scene_img = _base(drift_px[0], drift_px[1])
    draw = ImageDraw.Draw(scene_img)
    palette = {
        "red": (220, 50, 50),
        "copper": (205, 115, 50),
        "blue": (55, 110, 220),
        "green": (50, 195, 85),
        "yellow": (225, 210, 45),
        "white": (235, 235, 235),
    }
    for obj in objects:
        bx0, by0, bx1, by1 = obj["bounds_mm"]
        rgb_col = palette.get(obj.get("color", "white"), (200, 200, 200))
        rx0, ry0 = ox + bx0 * inv, oy + by0 * inv
        rx1, ry1 = ox + bx1 * inv, oy + by1 * inv
        if obj.get("split_gap"):
            # Render two separated fragments (fails intact flatness/area or produces 2 components).
            mid = (rx0 + rx1) / 2.0
            draw.rectangle([rx0, ry0, mid - 2.0, ry1], fill=rgb_col)
            draw.rectangle([mid + 2.0, ry0, rx1, ry1], fill=rgb_col)
        else:
            draw.rectangle([rx0, ry0, rx1, ry1], fill=rgb_col)
    if hand_intrusion:
        draw.rectangle([2, 100, 35, 128], fill=(210, 55, 210))
    return baseline, np.asarray(scene_img, dtype=np.uint8)
