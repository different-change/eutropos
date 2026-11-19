"""Bimanual 26-DoF AgileX NERO + 5-finger hand MuJoCo tabletop with hidden referee sensors."""

from __future__ import annotations

import copy
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from inspect_robots.embodiment import EmbodimentInfo
from inspect_robots.spaces import (
    ActionSemantics,
    Box,
    CameraSpec,
    ObservationSpace,
    StateField,
    StateSpec,
)
from inspect_robots.types import Action, Observation, StepResult

from .instruments import InstrumentSession, encode_si_frame
from .profiles import get_profile

_DEFAULT_SANDBOX = Path(
    os.environ.get("HABILIS_SANDBOX_DIR", str(Path(__file__).resolve().parents[3] / "sandbox"))
)
DEFAULT_NERO_SCENE_XML = _DEFAULT_SANDBOX / "logs" / "a3-nero" / "nero_scene.xml"
DEFAULT_AGX_MESHES = _DEFAULT_SANDBOX / "agx_arm_urdf" / "nero" / "meshes"
DEFAULT_G1_MESHES = _DEFAULT_SANDBOX / "unitree_ros" / "robots" / "g1_description" / "meshes"


def _prefix_element_names(elem: ET.Element, prefix: str, *, mirror_left_hand: bool) -> None:
    if "name" in elem.attrib:
        elem.attrib["name"] = f"{prefix}{elem.attrib['name']}"
    if elem.tag == "joint" and "joint1" in elem.attrib:
        elem.attrib["joint1"] = f"{prefix}{elem.attrib['joint1']}"
        elem.attrib["joint2"] = f"{prefix}{elem.attrib['joint2']}"
    if elem.tag == "position" and "joint" in elem.attrib:
        elem.attrib["joint"] = f"{prefix}{elem.attrib['joint']}"
    if mirror_left_hand and elem.tag == "geom" and "mesh" in elem.attrib:
        mesh = elem.attrib["mesh"]
        if mesh == "R_hand_base_link":
            elem.attrib["mesh"] = "L_hand_base_link"
        elif mesh.startswith("Link") and mesh.endswith("_R"):
            elem.attrib["mesh"] = mesh[:-2] + "_L"
    for child in list(elem):
        _prefix_element_names(child, prefix, mirror_left_hand=mirror_left_hand)


def _strip_empty_or_dup_equalities(root: ET.Element) -> tuple[list[ET.Element], list[ET.Element], list[ET.Element]]:
    """Return base_link, single deduplicated equality joints, and position actuators."""
    wb = root.find("worldbody")
    assert wb is not None
    base_link = wb.find("body[@name='base_link']")
    assert base_link is not None
    seen_eq: set[tuple[str, str]] = set()
    eq_items: list[ET.Element] = []
    for eq in root.findall("equality"):
        for item in eq:
            key = (item.attrib.get("joint1", ""), item.attrib.get("joint2", ""))
            if key not in seen_eq:
                seen_eq.add(key)
                copied = copy.deepcopy(item)
                if "polycoef" not in copied.attrib:
                    copied.attrib["polycoef"] = "0 1.0 0 0 0"
                eq_items.append(copied)
    act_items = [copy.deepcopy(a) for a in (root.find("actuator") if root.find("actuator") is not None else ())]
    return [copy.deepcopy(base_link)], eq_items, act_items


def build_bimanual_mjcf(
    *,
    props_xml: str = "",
    scale_pan_pos: tuple[float, float, float] = (0.48, 0.0, 0.01),
    drift_mm: tuple[float, float] = (0.0, 0.0),
    nero_scene_xml: Path = DEFAULT_NERO_SCENE_XML,
    g1_meshes_dir: Path = DEFAULT_G1_MESHES,
) -> str:
    """Construct a 26-actuator bimanual NERO + G1 5-finger MuJoCo MJCF XML string."""
    tree = ET.parse(nero_scene_xml)
    src_root = tree.getroot()
    src_asset = src_root.find("asset")
    assert src_asset is not None

    out_root = ET.Element("mujoco", {"model": "habilis_bimanual_nero"})
    ET.SubElement(out_root, "compiler", {"angle": "radian"})
    ET.SubElement(out_root, "option", {"timestep": "0.002", "integrator": "implicitfast"})
    visual = ET.SubElement(out_root, "visual")
    ET.SubElement(visual, "global", {"offwidth": "640", "offheight": "640"})

    asset = ET.SubElement(out_root, "asset")
    for item in src_asset:
        asset.append(copy.deepcopy(item))
    # Also register left-hand mirrored meshes if present on disk.
    left_meshes = ["L_hand_base_link"] + [f"Link{i}_L" for i in range(11, 23)]
    for mname in left_meshes:
        fpath = g1_meshes_dir / f"{mname}.STL"
        if fpath.exists():
            ET.SubElement(
                asset, "mesh", {"name": mname, "content_type": "model/stl", "file": str(fpath)}
            )
    ET.SubElement(
        asset,
        "texture",
        {"name": "bench_mat_tex", "type": "2d", "builtin": "checker", "width": "512", "height": "512", "rgb1": "0.50 0.48 0.45", "rgb2": "0.44 0.42 0.39"},
    )
    ET.SubElement(asset, "material", {"name": "bench_mat", "texture": "bench_mat_tex", "texrepeat": "8 8"})

    wb = ET.SubElement(out_root, "worldbody")
    ET.SubElement(wb, "light", {"pos": "0.25 -0.35 1.45", "dir": "0.15 0.15 -1", "diffuse": "0.58 0.58 0.58", "specular": "0.15 0.15 0.15"})
    ET.SubElement(wb, "light", {"pos": "0.25 0.35 1.35", "dir": "0.15 -0.15 -1", "diffuse": "0.35 0.35 0.35", "specular": "0.1 0.1 0.1"})
    ET.SubElement(
        wb,
        "geom",
        {
            "name": "table",
            "type": "plane",
            "size": "1.2 1.2 0.02",
            "material": "bench_mat",
            "friction": "1 0.01 0.001",
            "contype": "1",
            "conaffinity": "3",
        },
    )

    # Head-mounted stereo RGB cameras aimed at workspace center (0.47, 0.0, 0.03) from (0.10, +-0.06, 0.45)
    ET.SubElement(
        wb,
        "camera",
        {
            "name": "head_left",
            "pos": "0.10 0.06 0.45",
            "xyaxes": "0.0 -1.0 0.0  0.750 0.0 0.661",
            "fovy": "46",
        },
    )
    ET.SubElement(
        wb,
        "camera",
        {
            "name": "head_right",
            "pos": "0.10 -0.06 0.45",
            "xyaxes": "0.0 -1.0 0.0  0.750 0.0 0.661",
            "fovy": "46",
        },
    )
    # Perpendicular referee-only overhead camera aligned left-to-right (+Y to -Y, top +X)
    ET.SubElement(
        wb,
        "camera",
        {
            "name": "overhead_cam",
            "pos": f"{scale_pan_pos[0]:.4f} {scale_pan_pos[1]:.4f} 0.52",
            "xyaxes": "0 -1 0  1 0 0",
            "fovy": "32",
        },
    )

    # Masked balance tray pad (128x128 mm) + referee-only corner fiducials in geom group 3
    px, py, pz = scale_pan_pos
    dx, dy = drift_mm[0] / 1000.0, drift_mm[1] / 1000.0
    pan_body = ET.SubElement(wb, "body", {"name": "scale_pan_bezel", "pos": f"{px + dx:.4f} {py + dy:.4f} {pz:.4f}"})
    ET.SubElement(
        pan_body,
        "geom",
        {
            "name": "scale_pan_geom",
            "type": "box",
            "size": "0.064 0.064 0.006",
            "rgba": "0.22 0.24 0.28 1",
            "contype": "1",
            "conaffinity": "3",
        },
    )
    for fi, (fx, fy) in enumerate(((-0.105, -0.105), (0.105, -0.105), (-0.105, 0.105), (0.105, 0.105))):
        ET.SubElement(
            wb,
            "geom",
            {
                "name": f"fiducial_{fi}",
                "type": "box",
                "group": "3",
                "pos": f"{px + dx + fx:.4f} {py + dy + fy:.4f} 0.002",
                "size": "0.007 0.007 0.002",
                "rgba": "0.0 0.92 0.95 1",
                "contype": "0",
                "conaffinity": "0",
            },
        )

    bases, eq_items, act_items = _strip_empty_or_dup_equalities(src_root)
    eq_el = ET.SubElement(out_root, "equality")
    act_el = ET.SubElement(out_root, "actuator")

    left_has_meshes = all((g1_meshes_dir / f"{m}.STL").exists() for m in left_meshes)
    arm_specs = (
        ("left_", "0.0 0.29 0.0", left_has_meshes),
        ("right_", "0.0 -0.29 0.0", False),
    )
    for prefix, base_pos, mirror_l in arm_specs:
        b = copy.deepcopy(bases[0])
        _prefix_element_names(b, prefix, mirror_left_hand=mirror_l)
        b.attrib["pos"] = base_pos
        wb.append(b)
        for eq in eq_items:
            ce = copy.deepcopy(eq)
            _prefix_element_names(ce, prefix, mirror_left_hand=False)
            eq_el.append(ce)
        for act in act_items:
            ca = copy.deepcopy(act)
            _prefix_element_names(ca, prefix, mirror_left_hand=False)
            act_el.append(ca)

    if props_xml.strip():
        frag = ET.fromstring(f"<frag>{props_xml}</frag>")
        for child in list(frag):
            wb.append(child)

    return ET.tostring(out_root, encoding="unicode")


def bimanual_action_space() -> Box:
    labels: list[str] = []
    for arm in ("left", "right"):
        labels.extend(f"{arm}_joint{i}" for i in range(1, 8))
        labels.extend(
            f"{arm}_{fn}"
            for fn in (
                "little_finger",
                "ring_finger",
                "middle_finger",
                "index_finger",
                "thumb_bend",
                "thumb_rotate",
            )
        )
    return Box(
        shape=(26,),
        low=np.full(26, -0.25),
        high=np.full(26, 0.25),
        semantics=ActionSemantics(control_mode="joint_delta", dim_labels=tuple(labels)),
    )


def bimanual_observation_space() -> ObservationSpace:
    return ObservationSpace(
        cameras=(
            CameraSpec(name="head_left", height=480, width=640, channels=3),
            CameraSpec(name="head_right", height=480, width=640, channels=3),
        ),
        state=StateSpec(
            fields=(StateField(key="joint_pos", shape=(26,), unit="rad", dtype="float64"),)
        ),
    )


class BimanualNeroBench:
    """Minimal Inspect Robots embodiment wrapper for the 26-DoF MuJoCo twin (Profile P0)."""

    def __init__(
        self,
        *,
        props_xml: str = "",
        pan_mass_g: float = 0.0,
        drift_mm: tuple[float, float] = (0.0, 0.0),
        session: InstrumentSession | None = None,
    ) -> None:
        import mujoco  # Lazy so .venv without MuJoCo remains unaffected

        self._mj = mujoco
        self._profile = get_profile("P0")
        self._xml = build_bimanual_mjcf(props_xml=props_xml, drift_mm=drift_mm)
        self.model = mujoco.MjModel.from_xml_string(self._xml)
        self.data = mujoco.MjData(self.model)
        self._renderer = mujoco.Renderer(self.model, height=480, width=640)
        self._ov_renderer = mujoco.Renderer(self.model, height=240, width=240)
        self._pan_mass_g = float(pan_mass_g)
        self._session = session
        self._tick = 0
        self.info = EmbodimentInfo(
            name="habilis-bimanual-nero",
            action_space=bimanual_action_space(),
            observation_space=bimanual_observation_space(),
            control_hz=10.0,
            is_simulated=True,
            capabilities=frozenset({"seedable", "resettable", "renderable"}),
            morphology=self._profile.title,
            environment_id="habilis-mujoco-bimanual",
            environment_revision="0.3.0",
            docs="26-DoF bimanual NERO + 5-finger hands with head stereo and hidden overhead cam.",
        )

    def _arm_qpos_indices(self) -> list[int]:
        names: list[str] = []
        for prefix in ("left_", "right_"):
            for i in range(1, 8):
                names.append(f"{prefix}joint{i}")
            for j in (
                "R_pinky_proximal_joint",
                "R_ring_proximal_joint",
                "R_middle_proximal_joint",
                "R_index_proximal_joint",
                "R_thumb_proximal_pitch_joint",
                "R_thumb_proximal_yaw_joint",
            ):
                names.append(f"{prefix}{j}")
        return [int(self.model.joint(n).qposadr[0]) for n in names]

    def set_home_pose(self) -> None:
        self._mj.mj_resetData(self.model, self.data)
        parked = {
            "joint1": 0.45, "joint2": -1.35, "joint3": -0.35, "joint4": 1.65,
            "joint5": 0.0, "joint6": 0.15, "joint7": 0.0,
        }
        for side, sign in (("left_", 1.0), ("right_", -1.0)):
            for jname, val in parked.items():
                jid = self.model.joint(f"{side}{jname}").id
                adr = int(self.model.jnt_qposadr[jid])
                v = sign * val if jname in {"joint1", "joint3"} else val
                self.data.qpos[adr] = v
                act_id = self.model.actuator(f"{side}{jname}").id
                self.data.ctrl[act_id] = v
        self._mj.mj_forward(self.model, self.data)

    def set_joint_targets(self, q26: np.ndarray) -> None:
        arr = np.asarray(q26, dtype=np.float64)
        if arr.shape != (26,):
            raise ValueError("26 joint target values required")
        self.data.ctrl[:26] = arr
        q_idx = self._arm_qpos_indices()
        for i, qadr in enumerate(q_idx):
            self.data.qpos[qadr] = arr[i]
        self._mj.mj_forward(self.model, self.data)

    def reset_scene(self) -> dict[str, np.ndarray]:
        self.set_home_pose()
        for _ in range(25):
            self._mj.mj_step(self.model, self.data)
        self._tick = 0
        return self.render_all()

    def step_action(self, delta: Action | np.ndarray, *, substeps: int = 50) -> StepResult:
        vec = np.asarray(delta.data if isinstance(delta, Action) else delta, dtype=np.float64)
        if vec.shape != (26,) or not np.isfinite(vec).all():
            raise ValueError("26 finite delta values required")
        self.data.ctrl[:26] = self.data.ctrl[:26] + vec
        for _ in range(substeps):
            self._mj.mj_step(self.model, self.data)
        self._tick += 1
        views = self.render_all()
        obs = Observation(
            images={"head_left": views["head_left"], "head_right": views["head_right"]},
            state={"joint_pos": self.joint_positions()},
            instruction="",
            image_times={"head_left": self._tick / 10.0, "head_right": self._tick / 10.0},
            state_time=self._tick / 10.0,
        )
        return StepResult(observation=obs, info={})

    def joint_positions(self) -> np.ndarray:
        idx = self._arm_qpos_indices()
        return np.asarray([float(self.data.qpos[i]) for i in idx], dtype=np.float64)

    def render_all(self) -> dict[str, np.ndarray]:
        opt_athlete = self._mj.MjvOption()
        opt_athlete.geomgroup[3] = 0
        self._renderer.update_scene(self.data, camera="head_left", scene_option=opt_athlete)
        left = self._renderer.render().copy()
        self._renderer.update_scene(self.data, camera="head_right", scene_option=opt_athlete)
        right = self._renderer.render().copy()

        opt_ref = self._mj.MjvOption()
        opt_ref.geomgroup[3] = 1
        self._ov_renderer.update_scene(self.data, camera="overhead_cam", scene_option=opt_ref)
        overhead = self._ov_renderer.render().copy()
        return {"head_left": left, "head_right": right, "overhead": overhead}

    def simulated_si_frame(self, net_g: float | None = None, *, stability: str = " ") -> bytes:
        val = self._pan_mass_g if net_g is None else float(net_g)
        return encode_si_frame(val, stability=stability)

    def close(self) -> None:
        self._renderer.close()
        self._ov_renderer.close()
