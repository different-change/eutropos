"""Strict instrument decoding, scoring predicates, and hidden session storage."""

from __future__ import annotations

import copy
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterator

from inspect_robots.frames import _safe

from .manifest import canonical_json, read_json, sha256_bytes, write_json

MAX_SAMPLE_GAP_S = 0.100001
_ACTIVE: ContextVar[InstrumentSession | None] = ContextVar(
    "habilis_instrument_session", default=None
)


def finite_number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("finite numeric value required")
    return float(value)


@dataclass(frozen=True)
class ScaleReading:
    mass_g: float
    stability: str
    unit: str


@dataclass(frozen=True)
class ScaleSample:
    t_s: float
    raw: bytes


@dataclass(frozen=True)
class MassEvalResult:
    passed: bool
    reasons: tuple[str, ...]
    median_net_g: float | None
    sample_count: int


@dataclass(frozen=True)
class GeometryEvalResult:
    passed: bool
    reasons: tuple[str, ...]
    sample_count: int


def _unit(unit: str) -> bytes:
    if (
        not isinstance(unit, str) or len(unit) != 3
        or re.fullmatch(r"[A-Za-z]{1,3} *", unit) is None
        or unit != unit.rstrip().ljust(3)
    ):
        raise ValueError("unit must be a left-justified three-byte ASCII unit")
    return unit.encode("ascii")


def encode_si_frame(
    mass_g: float, *, stability: str = " ", unit: str = "g  ",
) -> bytes:
    value = finite_number(mass_g)
    if value == 0.0 and math.copysign(1.0, value) < 0:
        raise ValueError("negative zero not allowed")
    if stability not in (" ", "?", "^", "v"):
        raise ValueError("invalid SI stability marker")
    magnitude = f"{abs(value):.2f}"
    if len(magnitude) > 9:
        raise ValueError("SI mass exceeds the nine-byte field")
    if value < 0 and float(magnitude) == 0:
        raise ValueError("rounded negative zero not allowed")
    result = (
        b"SI " + stability.encode("ascii") + b" "
        + (b"-" if value < 0 else b" ")
        + magnitude.rjust(9).encode("ascii") + b" " + _unit(unit) + b"\r\n"
    )
    if len(result) != 21:
        raise ValueError("invalid encoded SI length")
    return result


def parse_si_frame(line: bytes) -> ScaleReading:
    if not isinstance(line, bytes) or len(line) != 21:
        raise ValueError("SI frame must contain exactly 21 bytes")
    if line[:3] != b"SI " or line[4:5] != b" " or line[15:16] != b" ":
        raise ValueError("invalid SI fixed bytes")
    if line[3:4] not in (b" ", b"?", b"^", b"v"):
        raise ValueError("invalid SI stability marker")
    if line[5:6] not in (b" ", b"-") or line[19:] != b"\r\n":
        raise ValueError("invalid SI sign or terminator")
    field = line[6:15].decode("ascii")
    token = field.lstrip(" ")
    if (
        re.fullmatch(r"\d+(?:\.\d+)?", token) is None
        or field != token.rjust(9)
    ):
        raise ValueError("invalid right-justified SI mass")
    unit = line[16:19].decode("ascii")
    _unit(unit)
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite SI mass")
    if line[5:6] == b"-":
        if value == 0:
            raise ValueError("negative zero not allowed")
        value = -value
    return ScaleReading(value, line[3:4].decode("ascii"), unit)


def _window(times: list[float], duration: float) -> list[int]:
    duration = finite_number(duration)
    if duration <= 0 or not times:
        raise ValueError("positive settle duration and samples required")
    checked = [finite_number(t) for t in times]
    if checked[0] < 0:
        raise ValueError("negative sample time")
    if any(b <= a for a, b in zip(checked, checked[1:])):
        raise ValueError("sample times must increase strictly")
    start = checked[-1] - duration
    if start < checked[0] - 1e-9:
        raise ValueError("insufficient settling coverage")
    # Include the sample at or immediately before the window boundary.
    first = max(i for i, t in enumerate(checked) if t <= start + 1e-9)
    selected = list(range(first, len(checked)))
    if any(
        checked[b] - checked[a] > MAX_SAMPLE_GAP_S
        for a, b in zip(selected, selected[1:])
    ):
        raise ValueError("settling sample gap")
    if checked[-1] - checked[first] < duration - 1e-9:
        raise ValueError("incomplete settling window")
    return selected


def evaluate_scale_stream(
    frames: list[ScaleSample], *, target_net_g: float,
    tolerance_g: float, tare_g: float = 0.0,
    settle_window_s: float = 2.0, max_step_delta_g: float = 0.03,
) -> MassEvalResult:
    reasons: list[str] = []
    try:
        target = finite_number(target_net_g)
        tolerance = finite_number(tolerance_g)
        tare = finite_number(tare_g)
        delta = finite_number(max_step_delta_g)
        if tolerance < 0 or delta < 0:
            raise ValueError("negative tolerance")
        decoded = [parse_si_frame(frame.raw) for frame in frames]
        if any(frame.unit != "g  " for frame in decoded):
            raise ValueError("mass scoring requires gram frames")
        chosen = _window([frame.t_s for frame in frames], settle_window_s)
        settled = [decoded[i] for i in chosen]
        if any(frame.stability != " " for frame in settled):
            reasons.append("unstable or out-of-range settled reading")
        if any(
            abs(b.mass_g - a.mass_g) > delta + 1e-9
            for a, b in zip(settled, settled[1:])
        ):
            reasons.append("settled adjacent mass delta exceeds limit")
        net = median(frame.mass_g - tare for frame in settled)
        if not target - tolerance - 1e-9 <= net <= target + tolerance + 1e-9:
            reasons.append("settled net mass outside target interval")
        return MassEvalResult(not reasons, tuple(reasons), net, len(settled))
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        return MassEvalResult(False, (str(exc),), None, 0)


def _bounds(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("four occupancy bounds required")
    x0, y0, x1, y1 = [finite_number(v) for v in value]
    if x0 >= x1 or y0 >= y1:
        raise ValueError("occupancy bounds must have positive area")
    return [x0, y0, x1, y1]


def evaluate_overhead_stream(
    frames: list[dict], *, target_spec: dict,
    settle_window_s: float = 2.0, max_bezel_drift_mm: float = 0.5,
) -> GeometryEvalResult:
    reasons: list[str] = []
    try:
        limit = finite_number(max_bezel_drift_mm)
        if limit < 0:
            raise ValueError("negative drift limit")
        pan = _bounds(target_spec["pan_bounds_mm"])
        expected = target_spec["expected_objects"]
        expected_by_id = {item["id"]: item for item in expected}
        if len(expected_by_id) != len(expected) or not expected:
            raise ValueError("expected object IDs must be unique and nonempty")
        # Validate every frame structurally, including the motion interval.
        for frame in frames:
            finite_number(frame["t_s"])
            if frame["coordinate_frame"] != target_spec["coordinate_frame"]:
                raise ValueError("overhead coordinate frame mismatch")
            drift = finite_number(frame["bezel_fiducial_drift_mm"])
            contact = finite_number(frame["scale_pan_contact_n"])
            if drift < 0 or contact < 0 or type(frame["hands_in_home_zone"]) is not bool:
                raise ValueError("invalid overhead status")
            if not isinstance(frame["objects"], list):
                raise ValueError("overhead objects must be a list")
            ids = [item["id"] for item in frame["objects"]]
            if (
                any(not isinstance(value, str) or not value for value in ids)
                or len(ids) != len(set(ids))
            ):
                raise ValueError("overhead object IDs must be unique")
            for item in frame["objects"]:
                _bounds(item["bounds_mm"])
                if type(item["intact"]) is not bool:
                    raise ValueError("object intactness must be boolean")
                if not isinstance(item["color"], str) or not isinstance(item["kind"], str):
                    raise ValueError("object class must be text")
        chosen = _window([frame["t_s"] for frame in frames], settle_window_s)
        for i in chosen:
            frame = frames[i]
            if frame["bezel_fiducial_drift_mm"] > limit:
                reasons.append("bezel drift exceeds limit")
            if frame["hands_in_home_zone"] is not True:
                reasons.append("hands outside home zone")
            if frame["scale_pan_contact_n"] != 0:
                reasons.append("robot contact with scale pan")
            actual = {item["id"]: item for item in frame["objects"]}
            if set(actual) != set(expected_by_id):
                reasons.append("placed object identities or counts differ")
            for item in actual.values():
                if item["intact"] is not True:
                    reasons.append("torn, missing, or crushed object")
                reference = expected_by_id.get(item["id"])
                if reference is None or any(
                    item[key] != reference[key] for key in ("color", "kind")
                ):
                    reasons.append("placed object class differs")
                x0, y0, x1, y1 = _bounds(item["bounds_mm"])
                if not (pan[0] <= x0 < x1 <= pan[2] and pan[1] <= y0 < y1 <= pan[3]):
                    reasons.append("occupancy outside bezel bounds")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(chosen))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)


_HIDDEN = (
    "target_net_g", "decoy_mass_g", "decoy_masses_g",
    "scale_trace", "overhead_trace", "referee_targets",
    "beaker_tare_g", "scale_zero_offset_g", "bezel_fiducial_origin_mm",
)


def _leaks(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(token in str(key).casefold() for token in _HIDDEN):
                errors.append(f"{path}: hidden field")
            _leaks(child, f"{path}.{key}", errors)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _leaks(child, f"{path}[{index}]", errors)
    elif isinstance(value, str) and any(token in value.casefold() for token in _HIDDEN):
        errors.append(f"{path}: hidden token")


def verify_athlete_blindness(
    prereg: dict, record: dict, actions_lines: list[dict],
    chunks_lines: list[dict], *, target_spec: dict | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for name, value in (
        ("prereg", prereg), ("record", record),
        ("actions", actions_lines), ("chunks", chunks_lines),
    ):
        _leaks(value, name, errors)
    try:
        configuration = record["configuration"]
        scene = configuration["scene"]
        if scene.get("target", object()) is not None or scene.get("metadata") != {}:
            errors.append("record Scene must have target=None and empty metadata")
        for public_scene in prereg["configuration"]["scenes"]:
            if public_scene.get("target", object()) is not None or public_scene["metadata"] != {}:
                errors.append("preregistered Scene exposes private data")
        for owner in ("body", "policy"):
            observation = configuration["spaces"][owner]["observation"]
            cameras = observation["cameras"]
            if (
                {camera["name"] for camera in cameras} != {"head_left", "head_right"}
                or len(cameras) != 2
                or any(
                    camera["shape"] != [32, 32, 3] or camera["dtype"] != "uint8"
                    for camera in cameras
                )
                or observation["state_keys"] != ["joint_pos"]
                or observation["state"] != [
                    {"key": "joint_pos", "shape": [14], "unit": "rad", "dtype": "float64"}
                ]
            ):
                errors.append(f"{owner} observation space exceeds blind contract")
        views = record["referee"]["athlete_views"]
        if len(views) != record["steps"]:
            errors.append("missing public observation audit")
        for step in views:
            if step["result_info"] != {}:
                errors.append("StepResult.info exceeds blind contract")
            for key in ("observation", "result_observation"):
                observation = step[key]
                if set(observation["images"]) != {"head_left", "head_right"}:
                    errors.append("unexpected athlete camera")
                if any(
                    descriptor != {"shape": [32, 32, 3], "dtype": "uint8"}
                    for descriptor in observation["images"].values()
                ):
                    errors.append("unexpected athlete image type")
                state = observation["state"]
                if set(state) != {"joint_pos"} or len(state["joint_pos"]) != 14:
                    errors.append("unexpected athlete state")
                else:
                    for number in state["joint_pos"]:
                        finite_number(number)
                if set(observation["extra"]) - {"env_step", "approvals", "operator_messages"}:
                    errors.append("unexpected athlete observation extra")
        if target_spec is not None:
            if target_spec["family_id"] not in {"E1-poured-mass", "E3-mass-sort"}:
                errors.append("unsupported private assignment")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(f"blindness schema: {exc}")
    return not errors, list(dict.fromkeys(errors))


class InstrumentSession:
    """Referee-owned memory. Public API separation has no process isolation."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root).absolute() if root is not None else None
        self._stamp: str | None = None
        self._assignments: dict[tuple[str, int], dict] = {}
        self._traces: dict[tuple[str, int], tuple[list[ScaleSample], list[dict]]] = {}
        self._frozen: dict[tuple[str, int], tuple[bytes, bytes]] = {}
        self._active: tuple[str, int] | None = None
        self._closed = False

    @classmethod
    def current(cls) -> InstrumentSession | None:
        return _ACTIVE.get()

    @contextmanager
    def activate(self) -> Iterator[InstrumentSession]:
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    def bind(self, root: Path, stamp: str) -> None:
        if self._stamp is not None and (self._root != root.absolute() or self._stamp != stamp):
            raise ValueError("instrument session already bound")
        self._root, self._stamp = root.absolute(), stamp

    def assign(self, scene_id: str, epoch: int, spec: dict) -> None:
        key = (scene_id, epoch)
        if key in self._assignments:
            raise ValueError("duplicate instrument assignment")
        self._assignments[key] = copy.deepcopy(spec)

    def begin_trial(self, scene_id: str, epoch: int) -> None:
        key = (scene_id, epoch)
        if self._closed or key not in self._assignments or key in self._traces:
            raise ValueError("invalid instrument trial")
        self._active = key
        self._traces[key] = ([], [])

    def active_spec(self, scene_id: str) -> dict:
        if self._active is None or self._active[0] != scene_id:
            raise ValueError("a referee session must begin the instrument trial")
        return copy.deepcopy(self._assignments[self._active])

    def sample(self, t_s: float, raw: bytes, overhead: dict) -> None:
        if self._active is None or self._active in self._frozen:
            raise ValueError("instrument trial is unavailable or already flushed")
        parse_si_frame(raw)
        scale, camera = self._traces[self._active]
        scale.append(ScaleSample(t_s, raw))
        camera.append(copy.deepcopy(overhead))

    def trial(self, record: Any) -> tuple[list[ScaleSample], list[dict], dict]:
        key = (record.scene_id, record.epoch)
        scale, camera = self._traces[key]
        return list(scale), copy.deepcopy(camera), copy.deepcopy(self._assignments[key])

    def paths(self, record: Any) -> tuple[Path, Path]:
        if self._root is None or self._stamp is None:
            raise ValueError("instrument session requires bound log storage")
        base = f"{_safe(record.scene_id)}-e{record.epoch}"
        directory = self._root / "instruments" / self._stamp
        return directory / f"{base}_scale.txt", directory / f"{base}_overhead.json"

    def flush_trial_files(self, record: Any) -> tuple[Path, Path]:
        key = (record.scene_id, record.epoch)
        scale, camera, _ = self.trial(record)
        raw = b"".join(sample.raw for sample in scale)
        end = len(record.steps) / 10
        document = {
            "schema": "habilis-instruments-v0",
            "clock": "episode-simulated-seconds",
            "capture_start_s": 0.0,
            "capture_end_s": end,
            "scale_sha256": sha256_bytes(raw),
            "scale_samples": [
                {"index": index, "t_s": sample.t_s}
                for index, sample in enumerate(scale)
            ],
            "frames": camera,
        }
        encoded = canonical_json(document)
        if key in self._frozen and self._frozen[key] != (raw, encoded):
            raise ValueError("instrument trace changed after scoring")
        scale_path, overhead_path = self.paths(record)
        if key in self._frozen:
            if scale_path.read_bytes() != raw or overhead_path.read_bytes() != encoded:
                raise ValueError("flushed instrument evidence changed")
            return scale_path, overhead_path
        scale_path.parent.mkdir(parents=True, exist_ok=True)
        scale_path.write_bytes(raw)
        write_json(overhead_path, document)
        self._frozen[key] = (raw, encoded)
        return scale_path, overhead_path

    def disclose_targets(self, ordered_trials: list[dict]) -> Path:
        if self._root is None or self._closed:
            raise ValueError("invalid target disclosure lifecycle")
        expected = {(trial["scene_id"], trial["epoch"]) for trial in ordered_trials}
        if expected != set(self._assignments) or expected != set(self._frozen):
            raise ValueError("every assigned trial must be flushed before disclosure")
        path = self._root / "referee_targets.json"
        write_json(path, {
            "schema": "habilis-targets-v0",
            "trials": [
                {
                    "trial_index": trial["trial_index"],
                    "scene_id": trial["scene_id"], "epoch": trial["epoch"],
                    "spec": self._assignments[(trial["scene_id"], trial["epoch"])],
                }
                for trial in ordered_trials
            ],
        })
        self._closed = True
        return path


def read_instrument_files(
    scale_path: Path, overhead_path: Path, *, expected_end_s: float,
) -> tuple[list[ScaleSample], list[dict]]:
    raw = scale_path.read_bytes()
    if not raw or len(raw) % 21:
        raise ValueError("scale stream must contain complete 21-byte frames")
    document = read_json(overhead_path, canonical=True)
    if document["schema"] != "habilis-instruments-v0":
        raise ValueError("unsupported instrument schema")
    if document["clock"] != "episode-simulated-seconds":
        raise ValueError("instrument clock mismatch")
    if (
        document["capture_start_s"] != 0.0
        or document["capture_end_s"] != expected_end_s
        or document["scale_sha256"] != sha256_bytes(raw)
    ):
        raise ValueError("instrument capture interval or digest mismatch")
    timestamps = document["scale_samples"]
    count = len(raw) // 21
    if len(timestamps) != count:
        raise ValueError("scale timestamp count mismatch")
    samples = []
    for index, item in enumerate(timestamps):
        if set(item) != {"index", "t_s"} or type(item["index"]) is not int or item["index"] != index:
            raise ValueError("scale sample index mismatch")
        frame = raw[index * 21:(index + 1) * 21]
        parse_si_frame(frame)
        samples.append(ScaleSample(finite_number(item["t_s"]), frame))
    frames = document["frames"]
    for times in (
        [sample.t_s for sample in samples],
        [finite_number(frame["t_s"]) for frame in frames],
    ):
        if (
            not times or times[0] != 0.0
            or not math.isclose(times[-1], expected_end_s, abs_tol=1e-9)
            or any(t < 0 or t > expected_end_s + 1e-9 for t in times)
            or any(b <= a or b - a > MAX_SAMPLE_GAP_S for a, b in zip(times, times[1:]))
        ):
            raise ValueError("instrument stream has missing or stale coverage")
    return samples, frames


def _centroid_mm(item: dict[str, Any]) -> tuple[float, float]:
    if "centroid_xy_mm" in item:
        cx, cy = item["centroid_xy_mm"]
        return finite_number(cx), finite_number(cy)
    x0, y0, x1, y1 = _bounds(item["bounds_mm"])
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def evaluate_relations(
    objects: list[dict[str, Any]],
    *,
    rules: list[dict[str, Any]],
    hands_in_home_zone: bool = True,
    min_separation_mm: float = 2.0,
) -> GeometryEvalResult:
    """E3 spatial relation predicate: left_of, right_of, between, collinear, evenly_spaced."""
    reasons: list[str] = []
    try:
        if not hands_in_home_zone:
            reasons.append("hands outside home zone")
        if not rules:
            raise ValueError("relation rules must be nonempty")
        by_id: dict[str, dict[str, Any]] = {}
        for item in objects:
            oid = item["id"]
            if oid in by_id:
                raise ValueError("duplicate object id in relation check")
            if item.get("intact", True) is not True:
                reasons.append(f"object {oid} not intact")
            by_id[oid] = item

        # Pairwise footprint non-overlap when bounds are supplied
        ids = list(by_id)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = by_id[ids[i]]
                b = by_id[ids[j]]
                if "bounds_mm" in a and "bounds_mm" in b:
                    ax0, ay0, ax1, ay1 = _bounds(a["bounds_mm"])
                    bx0, by0, bx1, by1 = _bounds(b["bounds_mm"])
                    gap_x = max(bx0 - ax1, ax0 - bx1)
                    gap_y = max(by0 - ay1, ay0 - by1)
                    if max(gap_x, gap_y) < min_separation_mm - 1e-9:
                        reasons.append("insufficient footprint separation")

        for rule in rules:
            kind = rule["kind"]
            tol_mm = finite_number(rule.get("distance_tol_mm", 5.0))
            tol_deg = finite_number(rule.get("angle_tol_deg", 10.0))
            if kind == "left_of":
                ax, ay = _centroid_mm(by_id[rule["a"]])
                bx, by = _centroid_mm(by_id[rule["b"]])
                if not (ax < bx - finite_number(rule.get("min_gap_mm", 5.0)) and abs(ay - by) <= tol_mm):
                    reasons.append(f"failed left_of({rule['a']}, {rule['b']})")
            elif kind == "right_of":
                ax, ay = _centroid_mm(by_id[rule["a"]])
                bx, by = _centroid_mm(by_id[rule["b"]])
                if not (ax > bx + finite_number(rule.get("min_gap_mm", 5.0)) and abs(ay - by) <= tol_mm):
                    reasons.append(f"failed right_of({rule['a']}, {rule['b']})")
            elif kind == "between":
                mx, my = _centroid_mm(by_id[rule["mid"]])
                ax, ay = _centroid_mm(by_id[rule["a"]])
                bx, by = _centroid_mm(by_id[rule["b"]])
                abx, aby = bx - ax, by - ay
                ab_len = math.hypot(abx, aby)
                if ab_len < 1e-6:
                    reasons.append("degenerate endpoints for between")
                else:
                    t = ((mx - ax) * abx + (my - ay) * aby) / (ab_len * ab_len)
                    perp = abs((mx - ax) * (-aby) + (my - ay) * abx) / ab_len
                    if not (0.05 <= t <= 0.95 and perp <= tol_mm):
                        reasons.append(f"failed between({rule['mid']})")
            elif kind in {"collinear", "evenly_spaced"}:
                pts = [_centroid_mm(by_id[oid]) for oid in rule["ids"]]
                if len(pts) < 3:
                    raise ValueError("collinear/evenly_spaced requires at least 3 objects")
                vx, vy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
                vlen = math.hypot(vx, vy)
                if vlen < 1e-6:
                    reasons.append("collinear endpoints collapsed")
                else:
                    for px, py in pts[1:-1]:
                        perp = abs((px - pts[0][0]) * (-vy) + (py - pts[0][1]) * vx) / vlen
                        ang = math.degrees(math.atan2(perp, max(vlen / 2.0, 1e-6)))
                        if perp > tol_mm or ang > tol_deg:
                            reasons.append("objects deviate from line")
                            break
                    if kind == "evenly_spaced":
                        dists = [
                            math.hypot(b[0] - a[0], b[1] - a[1])
                            for a, b in zip(pts, pts[1:])
                        ]
                        mean_d = sum(dists) / len(dists)
                        if any(abs(d - mean_d) > tol_mm for d in dists):
                            reasons.append("spacing outside tolerance")
            else:
                raise ValueError(f"unsupported relation kind: {kind!r}")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(objects))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)


def evaluate_seating(
    frames: list[dict[str, Any]],
    *,
    min_depth_mm: float,
    max_tilt_deg: float = 5.0,
    settle_window_s: float = 1.0,
) -> GeometryEvalResult:
    """H1 seating predicate: fixture continuity switch closed, insertion depth, tilt, clear release."""
    reasons: list[str] = []
    try:
        chosen = _window([finite_number(f["t_s"]) for f in frames], settle_window_s)
        for idx in chosen:
            frame = frames[idx]
            if frame.get("hands_in_home_zone") is not True:
                reasons.append("hands outside home zone during seating check")
            if frame.get("fixture_switch_closed") is not True:
                reasons.append("fixture continuity switch open")
            if finite_number(frame["insertion_depth_mm"]) < finite_number(min_depth_mm) - 1e-9:
                reasons.append("insertion depth below seating threshold")
            if abs(finite_number(frame.get("tilt_deg", 0.0))) > finite_number(max_tilt_deg) + 1e-9:
                reasons.append("peg tilt exceeds seating tolerance")
            if finite_number(frame.get("hand_fixture_contact_n", 0.0)) != 0.0:
                reasons.append("robot hand still pressing fixture")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(chosen))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)


def evaluate_opening(
    frames: list[dict[str, Any]],
    *,
    min_transfer_net_g: float,
    empty_vessel_g: float,
    settle_window_s: float = 1.0,
) -> GeometryEvalResult:
    """H2 two-hand opening predicate: closure separated, intact container, non-empty transfer."""
    reasons: list[str] = []
    try:
        chosen = _window([finite_number(f["t_s"]) for f in frames], settle_window_s)
        min_net = finite_number(min_transfer_net_g)
        empty_g = finite_number(empty_vessel_g)
        for idx in chosen:
            frame = frames[idx]
            if frame.get("hands_in_home_zone") is not True:
                reasons.append("hands outside home zone")
            if frame.get("container_intact") is not True:
                reasons.append("container damaged or torn")
            if frame.get("closure_open") is not True:
                reasons.append("cap, lid, or closure remains sealed")
            if frame.get("two_hand_hold_observed") is not True:
                reasons.append("required stabilization hold unverified")
            net_g = finite_number(frame["transferred_net_g"])
            if net_g <= empty_g * 0.05 and net_g < min_net - 1e-9:
                reasons.append("empty or zero contents transfer")
            elif net_g < min_net - 1e-9:
                reasons.append("transferred mass below requirement")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(chosen))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)


def evaluate_flatness(
    objects: list[dict[str, Any]],
    *,
    target_color: str,
    zone_bounds_mm: list[float],
    min_area_mm2: float,
    min_flatness_ratio: float = 0.72,
    hands_in_home_zone: bool = True,
) -> GeometryEvalResult:
    """E4/H3/A4 flatness & integrity predicate: un-bunched single intact component inside zone."""
    reasons: list[str] = []
    try:
        if not hands_in_home_zone:
            reasons.append("hands outside home zone")
        zone = _bounds(zone_bounds_mm)
        matches = [o for o in objects if o.get("color") == target_color]
        if len(matches) != 1:
            reasons.append(f"expected single intact {target_color} item, saw {len(matches)}")
        for item in matches:
            if item.get("intact") is not True:
                reasons.append("deformable object torn or split")
            area = finite_number(item["area_mm2"])
            if area < finite_number(min_area_mm2) - 1e-9:
                reasons.append("bunched or under-sized area")
            ratio = finite_number(item.get("flatness_ratio", 0.0))
            if ratio < finite_number(min_flatness_ratio) - 1e-9:
                reasons.append("folded or bunched flatness ratio below threshold")
            bx0, by0, bx1, by1 = _bounds(item["bounds_mm"])
            if not (zone[0] <= bx0 < bx1 <= zone[2] and zone[1] <= by0 < by1 <= zone[3]):
                reasons.append("flat object extends outside target zone")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(matches))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)


def evaluate_slot_passage(
    crossings: list[dict[str, Any]],
    *,
    expected_count: int,
    catch_box_mass_g: float,
    unit_mass_g: float,
    tolerance_g: float = 0.25,
    min_gap_s: float = 0.15,
    hands_in_home_zone: bool = True,
) -> GeometryEvalResult:
    """H4 slot-passage predicate: N distinct sequential slot crossings + catch-box mass match."""
    reasons: list[str] = []
    try:
        if not hands_in_home_zone:
            reasons.append("hands outside home zone")
        if type(expected_count) is not int or expected_count < 1:
            raise ValueError("positive integer expected_count required")
        times = [finite_number(ev["t_s"]) for ev in crossings]
        if any(b - a < min_gap_s - 1e-9 for a, b in zip(times, times[1:])):
            reasons.append("simultaneous batch crossing violates individual-slot rule")
        seen_ids: set[str] = set()
        for ev in crossings:
            if ev.get("intact") is not True or ev.get("released") is not True:
                reasons.append("unreleased or damaged small object at slot")
            oid = str(ev["object_id"])
            if oid in seen_ids:
                reasons.append("duplicate object id in slot crossing")
            seen_ids.add(oid)
        if len(crossings) != expected_count:
            reasons.append(f"expected {expected_count} slot crossings, saw {len(crossings)}")
        expected_g = expected_count * finite_number(unit_mass_g)
        actual_g = finite_number(catch_box_mass_g)
        tol = finite_number(tolerance_g)
        if abs(actual_g - expected_g) > tol + 1e-9:
            reasons.append("isolated catch-box mass disagrees with expected count")
        unique = tuple(dict.fromkeys(reasons))
        return GeometryEvalResult(not unique, unique, len(crossings))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return GeometryEvalResult(False, (str(exc),), 0)
