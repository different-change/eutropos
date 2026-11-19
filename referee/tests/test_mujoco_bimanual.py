"""MuJoCo bimanual 26-DoF tabletop verification (runs in sandbox/.venv-nero)."""

from __future__ import annotations

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

from eutropos_referee.instruments import parse_si_frame
from eutropos_referee.mujoco_bench import BimanualNeroBench, bimanual_action_space, bimanual_observation_space
from eutropos_referee.profiles import validate_dexterous_semantics
from eutropos_referee.vision import OverheadCalibration, extract_overhead_scene


def test_bimanual_nero_mujoco_bench_and_cameras() -> None:
    props = (
        '<body name="copper_token_0" pos="0.48 0.02 0.025">'
        '<geom type="cylinder" size="0.014 0.008" rgba="0.72 0.24 0.05 1" mass="0.0124" />'
        '</body>'
    )
    base_bench = BimanualNeroBench(pan_mass_g=0.0)
    bench = BimanualNeroBench(props_xml=props, pan_mass_g=12.40)
    try:
        assert bench.model.nu == 26
        base_views = base_bench.reset_scene()
        views = bench.reset_scene()
        assert views["head_left"].shape == (480, 640, 3) and views["head_left"].dtype == np.uint8
        assert views["head_right"].shape == (480, 640, 3) and views["head_right"].dtype == np.uint8
        assert views["overhead"].shape == (240, 240, 3) and views["overhead"].dtype == np.uint8
        assert not np.array_equal(views["head_left"], views["head_right"])
        assert views["overhead"].mean() > 5.0

        cal = OverheadCalibration(
            width_px=240, height_px=240, mm_per_px=1.25,
            fiducial_patches=((12, 12, 48, 48), (192, 12, 228, 48), (12, 192, 48, 228), (192, 192, 228, 228)),
        )
        extracted = extract_overhead_scene(views["overhead"], base_views["overhead"], cal, diff_threshold=20.0)
        assert extracted["hands_in_home_zone"] is True
        assert extracted["bezel_fiducial_drift_mm"] <= 0.2
        assert len(extracted["objects"]) == 1 and extracted["objects"][0]["color"] == "copper"

        res = bench.step_action(np.zeros(26, dtype=np.float64), substeps=10)
        assert res.observation.state["joint_pos"].shape == (26,)

        parsed = parse_si_frame(bench.simulated_si_frame())
        assert parsed.mass_g == 12.40 and parsed.stability == " "

        ok, errs = validate_dexterous_semantics(
            bimanual_action_space(), bimanual_observation_space(),
            bench.info.action_space, bench.info.observation_space,
            require_thumb_opposition=True,
        )
        assert ok and errs == []
    finally:
        base_bench.close()
        bench.close()
