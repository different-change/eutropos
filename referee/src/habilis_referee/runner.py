"""Prepare sealed sessions and run the pinned evaluator."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

import inspect_robots
from inspect_robots.eval import eval as robots_eval
from inspect_robots.logging.json_log import JsonLogSink
from inspect_robots.registry import resolve
from inspect_robots.task import Task

import habilis_referee

from . import __version__
from .bench_mock import (
    BlindAthletePolicy, HabilisBenchEmbodiment, POLICIES, scenes_for,
)
from .certificate import generate_or_load_private_key, write_public_key
from .generator import E1, E3, derive_trial_params, hidden_target_spec
from .instruments import InstrumentSession
from .isolation import SubprocessPolicyAdapter
from .manifest import file_entries, make_plan, object_hash, provenance_hashes, write_json
from .schema import configuration_document, scene_document
from .scorers import InstrumentGeometryScorer, InstrumentMassScorer
from .seed import SealedSeed, StubBeacon, commit, derive_instance_seed, generate_secret, utc_now
from .sink import RefereeSink

DEVIATIONS = [
    "This certificate describes a software mock.",
    "The beacon is a deterministic local stub.",
    "Commitment publication and contribution sequencing use local files.",
    "The closing timestamp uses the local clock.",
    "Inspect Robots consumes its own derived integer trial seed.",
    "The policy and referee share a process and filesystem.",
    "Source snapshots supply provenance; execution attestation remains open.",
    "Body ceiling, scripted floor, independent witnesses, and Veritas mapping remain open.",
]


def prepare_empty_directory(path: Path) -> Path:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("output directory must be a regular directory")
    path = path.absolute()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output directory must be absent or empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_sources(root: Path, module, name: str) -> list[Path]:
    source_root = Path(module.__file__).resolve().parent
    if root.resolve() == source_root or source_root in root.resolve().parents:
        raise ValueError("output must be outside package source directories")
    paths = []
    for source in sorted(source_root.rglob("*.py")):
        if source.is_symlink():
            raise ValueError("linked package source")
        target = root / "provenance" / name / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        paths.append(target)
    if not paths:
        raise ValueError("package has no Python sources")
    return paths


def _run(
    out_dir, *, epochs, policy, submitter, beacon_round,
    private_key, write_trusted_public_key, family_set, isolated=False,
) -> Path:
    if type(epochs) is not int or not 1 <= epochs <= 1000:
        raise ValueError("epochs must be between 1 and 1000")
    if version("inspect-robots") != "1.0.0":
        raise ValueError("inspect-robots==1.0.0 is required")
    if len(submitter.encode("utf-8")) > 4096:
        raise ValueError("submitter contribution exceeds 4096 bytes")
    instruments = family_set is not None
    allowed_policies = (*POLICIES, "memory-disk-snooper") if isolated else POLICIES
    if instruments and (policy not in allowed_policies or family_set not in {"mixed", "e1", "e3"}):
        raise ValueError("unsupported instrument policy or family set")
    if not instruments and policy not in {"scripted", "random", "noop"}:
        raise ValueError("unsupported CubePick policy")
    key = generate_or_load_private_key(private_key)
    root = prepare_empty_directory(Path(out_dir))
    if write_trusted_public_key is not None:
        trusted = Path(write_trusted_public_key).absolute()
        if trusted.resolve() == root.resolve() or root.resolve() in trusted.resolve().parents:
            raise ValueError("trusted public key output must be outside evidence")
        if trusted.exists():
            raise ValueError("trusted public key output already exists")
        write_public_key(trusted, key.public_key())
    secret, nonce = generate_secret()
    write_json(root / "seed_commitment.json", {
        "protocol_version": "habilis-referee-v0.2",
        "commitment_C": commit(secret, nonce),
        "beacon_provider": "stub-sha256-v0",
        "beacon_round_number": beacon_round,
        "created_utc": utc_now(), "publication": "local-file-stub",
    })
    sealed = SealedSeed(secret, nonce, submitter.encode("utf-8"), StubBeacon.lookup(beacon_round))
    session = InstrumentSession(root) if instruments else None
    if instruments:
        selected = []
        if family_set in {"mixed", "e1"}:
            selected.extend(scenes_for(E1))
        if family_set in {"mixed", "e3"}:
            selected.extend(scenes_for(E3, offset=2))
        task = Task(
            name="habilis-instruments-mock", scenes=selected, max_steps=40,
            epochs=epochs,
            scorer=[InstrumentMassScorer(session), InstrumentGeometryScorer(session)],
        )
        body = HabilisBenchEmbodiment(session)
        athlete = SubprocessPolicyAdapter(policy) if isolated else BlindAthletePolicy(policy)
        profile = "instruments-v0"
        scorer_names = ["habilis-mass", "habilis-geometry"]
        scorer_path = "provenance/habilis_referee/scorers.py"
    else:
        task = replace(resolve("task", "cubepick-reach"), epochs=epochs)
        body = resolve("embodiment", "cubepick")
        athlete = resolve("policy", policy)
        profile = "cubepick-mock-v0"
        scorer_names = ["success_at_end"]
        scorer_path = "provenance/inspect_robots/scorer.py"
    bind = getattr(athlete, "bind", None)
    if callable(bind):
        bind(body.info)
    configuration = configuration_document(task, athlete, body, sealed.eval_seed)
    task_spec = {
        "name": task.name, "epochs": epochs, "max_steps": task.max_steps,
        "reducer": "mean", "scorers": scorer_names,
        "scenes": [
            {
                **scene_document(scene),
                "family_id": (
                    E1 if scene.id.startswith("E1-") else E3
                ) if instruments else "cubepick-reach",
            }
            for scene in task.scenes
        ],
    }
    plan = make_plan(task_spec)
    assignments = {}
    if session is not None:
        for trial in plan:
            seed = derive_instance_seed(sealed.run_seed, trial["family_id"], trial["trial_index"])
            spec = hidden_target_spec(
                derive_trial_params(seed, trial["family_id"], trial["scene_index"])
            )
            session.assign(trial["scene_id"], trial["epoch"], spec)
            assignments[str(trial["trial_index"])] = object_hash(spec)
    write_json(root / "task_spec.json", task_spec)
    write_json(root / "body_configuration.json", {
        "identity": configuration["embodiment"],
        "spaces": configuration["spaces"]["body"],
    })
    paths = [root / name for name in (
        "seed_commitment.json", "task_spec.json", "body_configuration.json",
    )]
    paths.extend(_snapshot_sources(root, inspect_robots, "inspect_robots"))
    paths.extend(_snapshot_sources(root, habilis_referee, "habilis_referee"))
    entries = file_entries(root, paths)
    prereg = {
        "protocol_version": "habilis-referee-v0.2",
        "bundle_profile": profile, "created_utc": utc_now(),
        "subject": {
            "name": policy, "snapshot": f"habilis-referee=={__version__}",
            "division": "mock-isolated" if isolated else "mock",
            "sampling_settings": "deterministic mock configuration",
        },
        "configuration": configuration,
        "hashes": provenance_hashes(
            entries, scorer_path, harness_version="1.0.0", referee_version=__version__,
        ),
        "seed": sealed.public_values(),
        "seed_encoding": {
            "version": "v0.2", "lengths": "u64 big-endian",
            "family_id": "NFC UTF-8, length-prefixed",
            "instance_index": "global scene-major trial index",
            "actual_trial_seed": "inspect_robots.rollout.derive_seed",
        },
        "planned_trials": plan,
        "assignment_commitments": assignments,
        "public_families": list(dict.fromkeys(trial["family_id"] for trial in plan)),
        "held_out_family_count": 0,
        "budgets": {"max_steps_per_trial": task.max_steps, "max_seconds": None},
        "scoring_rule": {
            "names": scorer_names, "overall": "all scores equal 1.0",
            "reducer": "mean", "interval": "Wilson", "confidence": 0.95,
        },
        "publication_rule": "retain every started local run",
        "runtime": {
            "python": sys.version.split()[0], "numpy": version("numpy"),
            "cryptography": version("cryptography"),
        },
        "deviations_and_incidents": [
            (
                "The athlete executes in an isolated subprocess with stripped environment and empty cwd."
                if isolated and idx == 5 else line
            )
            for idx, line in enumerate(DEVIATIONS)
        ],
        "operator_and_witness": {"operator_id": "unattended-mock", "witness_id": None},
        "conflict_of_interest_statement": "The implementation constructs this demonstration. Independent review remains open.",
        "files": entries,
    }
    write_json(root / "preregistration.json", prereg)
    json_sink = JsonLogSink(str(root))
    referee = RefereeSink(
        str(root), preregistration=prereg, sealed_seed=sealed,
        json_sink=json_sink, private_key=key, session=session,
    )
    try:
        with session.activate() if session is not None else nullcontext():
            robots_eval(
                task, policy=athlete, embodiment=body, seed=sealed.eval_seed,
                log_dir=str(root), sinks=[json_sink, referee],
                store_frames=True, store_actions=True, store_records=True,
            )
        if not referee.closed:
            raise RuntimeError("referee did not close evaluation")
    except BaseException as exc:
        write_json(root / "run_failure.json", {
            "created_utc": utc_now(), "error_type": type(exc).__name__,
            "error": str(exc), "status": "incomplete; retained locally",
        })
        raise
    finally:
        close_athlete = getattr(athlete, "close", None)
        if callable(close_athlete):
            close_athlete()
        body.close()
    return root


def run_bundle(
    out_dir, *, epochs=2, policy="scripted",
    submitter_value="a1-submitter-v0", beacon_round=1,
    private_key=None, write_trusted_public_key=None,
) -> Path:
    return _run(
        out_dir, epochs=epochs, policy=policy, submitter=submitter_value,
        beacon_round=beacon_round, private_key=private_key,
        write_trusted_public_key=write_trusted_public_key, family_set=None,
    )


def run_instruments_bundle(
    out_dir, *, epochs=2, policy="compliant", family_set="mixed",
    submitter="submitter-demo", beacon_round=42,
    private_key=None, write_trusted_public_key=None, isolated=False,
) -> Path:
    return _run(
        out_dir, epochs=epochs, policy=policy, submitter=submitter,
        beacon_round=beacon_round, private_key=private_key,
        write_trusted_public_key=write_trusted_public_key, family_set=family_set,
        isolated=isolated,
    )
