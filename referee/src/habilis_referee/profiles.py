"""Pareto-optimal body profiles, tactile masking, and dexterous semantic validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inspect_robots.spaces import Box, ObservationSpace


@dataclass(frozen=True)
class BodyProfile:
    profile_id: str
    title: str
    arm_model: str
    hand_model: str
    arm_dof: int
    finger_dof_per_hand: int
    has_thumb_opposition: bool
    nominal_reach_mm: float
    nominal_payload_kg: float
    has_tactile: bool
    open_cad_licence: str
    cost_tier_usd: int

    @property
    def total_dof(self) -> int:
        return 2 * (self.arm_dof + self.finger_dof_per_hand)

    @property
    def effective_reach_mm(self) -> float:
        return round(self.nominal_reach_mm * 0.72, 1)


PROFILES: dict[str, BodyProfile] = {
    "P0": BodyProfile(
        profile_id="P0",
        title="sim-bimanual-nero",
        arm_model="2x AgileX NERO (MuJoCo)",
        hand_model="2x Inspire/6-DoF 5-finger hands",
        arm_dof=7,
        finger_dof_per_hand=6,
        has_thumb_opposition=True,
        nominal_reach_mm=580.0,
        nominal_payload_kg=3.0,
        has_tactile=False,
        open_cad_licence="MIT (inspect-robots-agilex-nero)",
        cost_tier_usd=0,
    ),
    "P1": BodyProfile(
        profile_id="P1",
        title="open-commercial-c1",
        arm_model="2x I2RT YAM Ultra 2",
        hand_model="2x ORCA v2.1 Base",
        arm_dof=6,
        finger_dof_per_hand=17,
        has_thumb_opposition=True,
        nominal_reach_mm=750.0,
        nominal_payload_kg=4.0,
        has_tactile=False,
        open_cad_licence="CC BY 4.0 hand CAD + MIT orca_core",
        cost_tier_usd=26486,
    ),
    "P2": BodyProfile(
        profile_id="P2",
        title="precision-tactile-c2",
        arm_model="2x UFACTORY 850",
        hand_model="2x ORCA v2.1 Touch",
        arm_dof=6,
        finger_dof_per_hand=17,
        has_thumb_opposition=True,
        nominal_reach_mm=850.0,
        nominal_payload_kg=5.0,
        has_tactile=True,
        open_cad_licence="CC BY 4.0 mechanical CAD + proprietary Touch sensor",
        cost_tier_usd=40886,
    ),
}


def get_profile(profile_id: str) -> BodyProfile:
    if profile_id not in PROFILES:
        raise ValueError(f"unknown body profile: {profile_id!r}")
    return PROFILES[profile_id]


def mask_tactile_observation(
    observation: dict[str, Any], *, mask_tactile: bool = True,
) -> dict[str, Any]:
    """Strip or zero tactile channels so a P2 bench can run P1 non-tactile divisions."""
    if not mask_tactile:
        return dict(observation)
    copied = dict(observation)
    state = dict(copied.get("state", {}))
    for key in list(state):
        if "tactile" in key or "fingertip" in key or "touch" in key:
            del state[key]
    copied["state"] = state
    extra = dict(copied.get("extra", {}))
    for key in list(extra):
        if "tactile" in key or "fingertip" in key or "touch" in key:
            del extra[key]
    copied["extra"] = extra
    return copied


def validate_dexterous_semantics(
    policy_action: Box,
    policy_observation: ObservationSpace,
    body_action: Box,
    body_observation: ObservationSpace,
    *,
    require_thumb_opposition: bool = True,
    mask_tactile: bool = False,
) -> tuple[bool, list[str]]:
    """Reject parallel-gripper vs dexterous-finger mismatches missed by inspect_robots compat."""
    errors: list[str] = []
    p_sem = policy_action.semantics
    b_sem = body_action.semantics
    p_labels = tuple(p_sem.dim_labels) if p_sem and p_sem.dim_labels else ()
    b_labels = tuple(b_sem.dim_labels) if b_sem and b_sem.dim_labels else ()

    if policy_action.shape != body_action.shape:
        errors.append(
            f"action shape mismatch: policy {policy_action.shape} != body {body_action.shape}"
        )

    def _has_parallel_jaw(labels: tuple[str, ...], obs: ObservationSpace) -> bool:
        if any("gripper" in lbl.casefold() and "finger" not in lbl.casefold() for lbl in labels):
            return True
        if obs.state is not None:
            for fld in obs.state.fields:
                if fld.unit in {"gripper", "gripper_width"}:
                    return True
        return False

    def _has_dexterous_fingers(labels: tuple[str, ...]) -> bool:
        lower = " ".join(labels).casefold()
        return any(tok in lower for tok in ("thumb", "index", "finger", "mcp", "pip", "abd"))

    p_jaw = _has_parallel_jaw(p_labels, policy_observation)
    b_dex = _has_dexterous_fingers(b_labels)
    p_dex = _has_dexterous_fingers(p_labels)
    b_jaw = _has_parallel_jaw(b_labels, body_observation)

    if p_jaw and b_dex:
        errors.append("parallel-gripper policy cannot bind to dexterous-finger embodiment")
    if p_dex and b_jaw:
        errors.append("dexterous-finger policy cannot bind to parallel-gripper embodiment")
    if p_labels and b_labels and len(p_labels) == len(b_labels):
        for p_lbl, b_lbl in zip(p_labels, b_labels):
            p_is_finger = any(k in p_lbl.casefold() for k in ("thumb", "finger", "index"))
            b_is_finger = any(k in b_lbl.casefold() for k in ("thumb", "finger", "index"))
            if p_is_finger != b_is_finger:
                errors.append(f"joint semantic role mismatch at {p_lbl!r} vs {b_lbl!r}")
                break

    if require_thumb_opposition and b_labels:
        has_thumb = any("thumb" in lbl.casefold() for lbl in b_labels)
        if not has_thumb:
            errors.append("body action labels omit opposable thumb axes")

    if mask_tactile and policy_observation.state is not None:
        for fld in policy_observation.state.fields:
            if any(k in fld.key.casefold() for k in ("tactile", "touch", "fingertip")):
                errors.append(f"tactile state field {fld.key!r} forbidden under mask_tactile=True")

    return not errors, errors
