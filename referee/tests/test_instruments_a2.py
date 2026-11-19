from __future__ import annotations

import copy
import hashlib
from importlib.metadata import entry_points
from types import SimpleNamespace

import numpy as np
import pytest
from inspect_robots.compat import check_compatibility
from inspect_robots.registry import resolve

from habilis_referee.beacon import (
    DrandHttpBeacon, RFC3161Client, StubTimestampAuthority, timestamp_request,
)
from habilis_referee.bench_mock import (
    BlindAthletePolicy, CHEAT_POLICIES, HabilisBenchEmbodiment, habilis_e1_task,
)
from habilis_referee.certificate import load_public_key, verify_certificate
from habilis_referee.cli import main
from habilis_referee.generator import (
    E1, E3, derive_trial_params, hidden_target_spec, split_athlete_scene,
)
from habilis_referee.instruments import (
    InstrumentSession, ScaleSample, encode_si_frame, evaluate_overhead_stream,
    evaluate_scale_stream, parse_si_frame, verify_athlete_blindness,
)
from habilis_referee.manifest import read_json, read_jsonl
from habilis_referee.runner import run_instruments_bundle
from habilis_referee.scorers import InstrumentMassScorer
from habilis_referee.tamper import INSTRUMENT_ATTACK_REASONS, copy_and_tamper
from habilis_referee.verifier import verify_bundle


@pytest.mark.parametrize("value", [0.0, 18.5, 125.04, -12.4])
@pytest.mark.parametrize("marker", [" ", "?", "^", "v"])
def test_si_roundtrip(value, marker):
    raw = encode_si_frame(value, stability=marker)
    assert len(raw) == 21
    assert raw[:3] == b"SI " and raw[3:4] == marker.encode()
    assert raw[4:5] == b" " and raw[15:16] == b" " and raw[19:] == b"\r\n"
    decoded = parse_si_frame(raw)
    assert decoded.mass_g == value
    assert decoded.stability == marker and decoded.unit == "g  "


def test_manual_example_and_exact_field_width():
    raw = b"SI ?       18.5 kg \r\n"
    assert len(raw) == 21
    assert parse_si_frame(raw).mass_g == 18.5
    assert parse_si_frame(raw).unit == "kg "
    stable = encode_si_frame(125.04)
    assert stable[6:15] == b"   125.04"


@pytest.mark.parametrize("raw", [
    b"", b"SI\r\n", b"x" * 21,
    b"SI    " + b"      nan" + b" g  \r\n",
    b"SI   -" + b"     0.00" + b" g  \r\n",
])
def test_si_rejects_malformed(raw):
    with pytest.raises((ValueError, UnicodeError)):
        parse_si_frame(raw)


@pytest.mark.parametrize("value", [-0.0, float("nan"), float("inf"), 10000000.0])
def test_si_encoder_rejects_edges(value):
    with pytest.raises(ValueError):
        encode_si_frame(value)


def scale_samples(count=31, mass=145.0, marker=" "):
    return [ScaleSample(index / 10, encode_si_frame(mass, stability=marker)) for index in range(count)]


def test_scale_settling_rules():
    kwargs = {"target_net_g": 100.0, "tolerance_g": 0.5, "tare_g": 45.0}
    assert evaluate_scale_stream(scale_samples(), **kwargs).passed
    assert not evaluate_scale_stream(scale_samples(count=20), **kwargs).passed
    for marker in ("?", "^", "v"):
        assert not evaluate_scale_stream(scale_samples(marker=marker), **kwargs).passed
    oscillating = [
        ScaleSample(index / 10, encode_si_frame(145.0 + (0.1 if index % 2 else 0.0)))
        for index in range(31)
    ]
    assert not evaluate_scale_stream(oscillating, **kwargs).passed
    sparse = [sample for i, sample in enumerate(scale_samples()) if i != 20]
    assert not evaluate_scale_stream(sparse, **kwargs).passed


def geometry_fixture():
    spec = hidden_target_spec(derive_trial_params(bytes(32), E3, 0))
    dx, dy = spec["bezel_jitter_mm"]
    objects = [
        {**item, "intact": True, "bounds_mm": [dx - 2, dy - 2, dx + 2, dy + 2]}
        for item in spec["expected_objects"]
    ]
    frames = [
        {
            "t_s": index / 10, "coordinate_frame": "bench-mm",
            "bezel_fiducial_drift_mm": 0.0, "hands_in_home_zone": True,
            "scale_pan_contact_n": 0.0, "objects": copy.deepcopy(objects),
        }
        for index in range(31)
    ]
    return spec, frames


@pytest.mark.parametrize("attack", [
    "drift", "home", "contact", "intact", "identity", "color", "count", "bounds",
])
def test_overhead_predicates(attack):
    spec, frames = geometry_fixture()
    assert evaluate_overhead_stream(frames, target_spec=spec).passed
    last = frames[-1]
    if attack == "drift":
        last["bezel_fiducial_drift_mm"] = 0.51
    elif attack == "home":
        last["hands_in_home_zone"] = False
    elif attack == "contact":
        last["scale_pan_contact_n"] = 0.001
    elif attack == "intact":
        last["objects"][0]["intact"] = False
    elif attack == "identity":
        last["objects"][0]["id"] = "wrong"
    elif attack == "color":
        last["objects"][0]["color"] = "blue"
    elif attack == "count":
        last["objects"].pop()
    else:
        last["objects"][0]["bounds_mm"] = [1000.0, 1000.0, 1001.0, 1001.0]
    assert not evaluate_overhead_stream(frames, target_spec=spec).passed


def test_generator_nonaliasing_and_public_split():
    for index in range(256):
        seed = hashlib.sha256(str(index).encode()).digest()
        params = derive_trial_params(seed, E3, index)
        assert params == derive_trial_params(seed, E3, index)
        assert params["N_target"] in {3, 4}
        target_cg = round(params["target_net_g"] * 100)
        decoy_cg = round(params["m_b_g"] * 100)
        assert all(abs(k * decoy_cg - target_cg) > 80 for k in range(9))
        public = split_athlete_scene(params)
        assert set(public) == {"instruction", "layout"}
        assert "target_net_g" not in str(public)
        e1 = derive_trial_params(seed, E1, index)
        assert 50 <= e1["target_net_g"] <= 180
        assert 42 <= e1["beaker_tare_g"] <= 48
        assert all(-8 <= value <= 8 for value in e1["bezel_jitter_mm"])
        assert len(e1["containers"]) == 3


@pytest.mark.parametrize(("group", "kind", "name"), [
    ("inspect_robots.sinks", "sink", "referee"),
    ("inspect_robots.scorers", "scorer", "habilis-mass"),
    ("inspect_robots.scorers", "scorer", "habilis-geometry"),
    ("inspect_robots.embodiments", "embodiment", "habilis-bench"),
    ("inspect_robots.tasks", "task", "habilis-e1-mock"),
    ("inspect_robots.tasks", "task", "habilis-e3-mock"),
])
def test_zero_argument_entry_points(monkeypatch, group, kind, name):
    monkeypatch.delenv("INSPECT_ROBOTS_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    assert name in {entry.name for entry in entry_points(group=group)}
    assert resolve(kind, name) is not None


def test_exact_spaces_and_missing_session_abstention():
    body = HabilisBenchEmbodiment()
    policy = BlindAthletePolicy()
    assert check_compatibility(policy, body, habilis_e1_task()).ok
    assert body.info.action_space.shape == (14,)
    assert body.info.action_space.semantics.control_mode == "joint_delta"
    assert body.info.observation_space.camera_names == {"head_left", "head_right"}
    assert body.info.observation_space.state_keys == {"joint_pos"}
    assert InstrumentMassScorer()(SimpleNamespace()).value is None


def test_session_flush_is_idempotent_and_targets_wait_for_close(tmp_path):
    session = InstrumentSession(tmp_path)
    session.bind(tmp_path, "stamp")
    spec = hidden_target_spec(derive_trial_params(bytes(32), E1, 0))
    scene = habilis_e1_task().scenes[0]
    session.assign(scene.id, 0, spec)
    session.begin_trial(scene.id, 0)
    body = HabilisBenchEmbodiment(session)
    observation = body.reset(scene, seed=1)
    assert observation.images["head_left"].shape == (32, 32, 3)
    assert observation.images["head_left"].dtype == np.uint8
    assert not np.array_equal(observation.images["head_left"], observation.images["head_right"])
    assert observation.extra == {}
    record = SimpleNamespace(scene_id=scene.id, epoch=0, steps=[])
    first = session.flush_trial_files(record)
    assert session.flush_trial_files(record) == first
    assert not (tmp_path / "referee_targets.json").exists()
    session.disclose_targets([{"scene_id": scene.id, "epoch": 0, "trial_index": 0}])
    assert (tmp_path / "referee_targets.json").exists()


def test_compliant_bundle_and_blindness(instrument_bundle):
    trusted = instrument_bundle.parent / "trusted.pem"
    report = verify_bundle(instrument_bundle, public_key=trusted)
    assert report.passed, report.failures
    payload = verify_certificate(
        read_json(instrument_bundle / "certificate.json", canonical=True),
        load_public_key(trusted),
    )
    assert payload["results"]["overall"]["pass_rate"] == 1.0
    assert payload["results"]["overall"]["trials"] == 8
    prereg = read_json(instrument_bundle / "preregistration.json", canonical=True)
    trial = read_json(instrument_bundle / "manifests/trial_0000.json", canonical=True)
    record = read_json(instrument_bundle / trial["record_path"])
    actions = read_jsonl(instrument_bundle / trial["actions_path"])
    chunks = read_jsonl(instrument_bundle / trial["chunks_path"])
    assert verify_athlete_blindness(prereg, record, actions, chunks)[0]
    for mutation in ("target", "metadata", "token", "camera"):
        changed = copy.deepcopy(record)
        if mutation == "target":
            changed["configuration"]["scene"]["target"] = {"mass": 1}
        elif mutation == "metadata":
            changed["configuration"]["scene"]["metadata"] = {"tare": 1}
        elif mutation == "token":
            changed["referee"]["extra"] = "target_net_g"
        else:
            changed["configuration"]["spaces"]["body"]["observation"]["cameras"].append(
                {"name": "wrist", "shape": [32, 32, 3], "dtype": "uint8"}
            )
        assert not verify_athlete_blindness(prereg, changed, actions, chunks)[0]


@pytest.mark.parametrize("policy", CHEAT_POLICIES)
def test_all_cheat_policies_are_faithfully_sealed(tmp_path, policy):
    trusted = tmp_path / "trusted.pem"
    root = run_instruments_bundle(
        tmp_path / policy, policy=policy, write_trusted_public_key=trusted,
    )
    report = verify_bundle(root, public_key=trusted)
    assert report.passed, report.failures
    payload = verify_certificate(
        read_json(root / "certificate.json", canonical=True), load_public_key(trusted)
    )
    assert payload["results"]["overall"]["pass_rate"] == 0.0
    checks = [check for check in report.checks if check.name == "athlete_blindness"]
    assert len(checks) == 8 and all(check.passed for check in checks)
    prereg = read_json(root / "preregistration.json", canonical=True)
    assert all(
        scene["target"] is None and scene["metadata"] == {}
        for scene in prereg["configuration"]["scenes"]
    )


@pytest.mark.parametrize("attack", list(INSTRUMENT_ATTACK_REASONS))
def test_instrument_tampers_fail(instrument_bundle, tmp_path, attack):
    destination = tmp_path / attack
    copy_and_tamper(instrument_bundle, destination, attack)
    report = verify_bundle(
        destination, public_key=instrument_bundle.parent / "trusted.pem",
    )
    assert not report.passed
    assert any(
        failure.startswith(INSTRUMENT_ATTACK_REASONS[attack] + ":")
        for failure in report.failures
    ), report.failures


def test_beacon_and_tsa_interfaces_use_injected_transports():
    signature = bytes(range(48))
    value = hashlib.sha256(signature).hexdigest()
    requests = []

    def fetch(url):
        requests.append(url)
        return {"round": 42, "randomness": value, "signature": signature.hex()}

    reading = DrandHttpBeacon(
        "https://beacon.example", "ab" * 32, transport=fetch,
    ).lookup(42)
    assert requests == [f"https://beacon.example/{'ab' * 32}/public/round/42"]
    assert reading.value_hex == value and reading.cryptographically_verified is False
    digest = hashlib.sha256(b"test").digest()
    der = timestamp_request(digest, 1)
    assert der[0] == 0x30 and digest in der
    posts = []

    def submit(url, data):
        posts.append((url, data))
        return b"\x30\x00"

    attestation = RFC3161Client("https://tsa.example", transport=submit).submit_digest_sha256(digest)
    assert len(posts) == 1 and digest in posts[0][1]
    assert attestation.externally_verified is False
    assert StubTimestampAuthority().submit_digest_sha256(digest).provider == "local-clock"


def test_prove_instruments_cli(tmp_path, capsys):
    root = tmp_path / "proof"
    assert main(["prove-instruments", "--out-dir", str(root)]) == 0
    capsys.readouterr()
    report = read_json(root / "proof_report.json", canonical=True)
    assert report["passed"]
    assert set(report["cheat_tests"]) == set(CHEAT_POLICIES)
    assert set(report["tamper_tests"]) == set(INSTRUMENT_ATTACK_REASONS)
