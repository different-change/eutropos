"""Inspect Robots scorers backed by the active hidden session."""

from __future__ import annotations

from inspect_robots.scorer import Score

from .instruments import (
    InstrumentSession,
    evaluate_overhead_stream,
    evaluate_scale_stream,
)


class InstrumentMassScorer:
    name = "habilis-mass"

    def __init__(self, session: InstrumentSession | None = None) -> None:
        self._session = session

    def __call__(self, record, target=None) -> Score:
        session = self._session or InstrumentSession.current()
        if session is None:
            return Score(value=None, explanation="A referee InstrumentSession is required.")
        session.flush_trial_files(record)
        scale, _, spec = session.trial(record)
        result = evaluate_scale_stream(
            scale, target_net_g=spec["target_net_g"],
            tolerance_g=spec["tolerance_g"], tare_g=spec["tare_g"],
            settle_window_s=spec["settle_window_s"],
            max_step_delta_g=spec["max_step_delta_g"],
        )
        return Score(
            value=1.0 if result.passed else 0.0,
            explanation="instrument predicates passed" if result.passed else "; ".join(result.reasons),
            metadata={"settled_samples": result.sample_count},
        )


class InstrumentGeometryScorer:
    name = "habilis-geometry"

    def __init__(self, session: InstrumentSession | None = None) -> None:
        self._session = session

    def __call__(self, record, target=None) -> Score:
        session = self._session or InstrumentSession.current()
        if session is None:
            return Score(value=None, explanation="A referee InstrumentSession is required.")
        session.flush_trial_files(record)
        _, camera, spec = session.trial(record)
        result = evaluate_overhead_stream(
            camera, target_spec=spec, settle_window_s=spec["settle_window_s"],
            max_bezel_drift_mm=spec["max_bezel_drift_mm"],
        )
        return Score(
            value=1.0 if result.passed else 0.0,
            explanation="instrument predicates passed" if result.passed else "; ".join(result.reasons),
            metadata={"settled_samples": result.sample_count},
        )


def mass_scorer(session: InstrumentSession | None = None) -> InstrumentMassScorer:
    return InstrumentMassScorer(session)


def geometry_scorer(session: InstrumentSession | None = None) -> InstrumentGeometryScorer:
    return InstrumentGeometryScorer(session)
