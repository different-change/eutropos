"""Offline authentication, complete artifact parsing, and score recomputation."""

from __future__ import annotations

import math
import ntpath
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from inspect_robots.frames import _safe
from inspect_robots.rollout import derive_seed

from . import __version__
from .certificate import (
    CERTIFICATE_VERSION_V1,
    key_id,
    load_public_key,
    public_key_bytes,
    verify_certificate,
)
from .evidence import validate_native_artifacts
from .generator import derive_trial_params, hidden_target_spec
from .instruments import (
    evaluate_overhead_stream, evaluate_scale_stream,
    read_instrument_files, verify_athlete_blindness,
)
from .manifest import (
    bundle_path, canonical_json, inventory, make_plan, object_hash,
    provenance_hashes, read_json, sha256_file, validate_relative_path,
)
from .results import summarize
from .schema import configuration_matches
from .seed import (
    commit, decode_hex, derive_eval_seed, derive_instance_seed,
    derive_run_seed, verify_stub_beacon,
)


@dataclass
class VerificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationReport:
    passed: bool = False
    trusted_key_mode: str | None = None
    checks: list[VerificationCheck] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def check(self, name: str, condition: bool, detail: str) -> bool:
        passed = bool(condition)
        self.checks.append(VerificationCheck(name, passed, detail))
        if not passed:
            self.failures.append(f"{name}: {detail}")
        return passed

    def capture(self, name: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            self.check(name, False, f"{type(exc).__name__}: {exc}")
            return None

    def finish(self):
        self.passed = not self.failures
        return self


def _native_path_matches(raw: Any, expected: str, *, absolute_allowed: bool) -> bool:
    try:
        validate_relative_path(expected)
    except ValueError:
        return False
    if not isinstance(raw, str):
        return False
    normalized = raw.replace("\\", "/")
    if normalized == expected:
        return True
    drive, tail = ntpath.splitdrive(raw)
    anchored = (
        (bool(drive) and tail.startswith(("/", "\\")))
        or (not drive and normalized.startswith("/"))
    )
    if not absolute_allowed or not anchored:
        return False
    parts = normalized.split("/")
    if any(part in {".", ".."} for part in parts):
        return False
    return normalized.endswith("/" + expected)


def _number_equal(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (
        type(left) in (int, float) and type(right) in (int, float)
        and math.isfinite(left) and math.isfinite(right)
        and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    )


def verify_bundle(
    evidence_dir,
    certificate=None,
    public_key=None,
    *,
    allow_bundled_key=False,
    trusted_tsa_pem=None,
    escrow_dir=None,
    require_live_beacon: bool = False,
    require_live_tsa: bool = False,
) -> VerificationReport:
    report = VerificationReport()
    root = Path(evidence_dir).absolute()
    certificate_path = Path(certificate) if certificate is not None else root / "certificate.json"
    if public_key is None and not allow_bundled_key:
        report.check("trusted_public_key", False, "supply public_key or explicitly allow_bundled_key")
        return report.finish()
    mode = "external-key" if public_key is not None else "self-asserted-bundled-key"
    report.trusted_key_mode = mode
    report.check("trusted_key_mode", True, mode)
    key = report.capture(
        "dsse_signature",
        lambda: load_public_key(public_key if public_key is not None else root / "public_key.pem"),
    )
    if key is None:
        return report.finish()

    def authenticate():
        raw = certificate_path.read_bytes()
        envelope = read_json(certificate_path, canonical=True)
        if canonical_json(envelope) != raw:
            raise ValueError("noncanonical certificate bytes")
        payload = verify_certificate(envelope, key)
        report.check("dsse_signature", True, f"Ed25519 DSSEv1 PAE; keyid={key_id(key)}")
        return payload

    payload = report.capture("dsse_signature", authenticate)
    if payload is None:
        return report.finish()
    if payload.get("certificate_version") == CERTIFICATE_VERSION_V1:
        from .protocol_v1 import verify_v1_bundle

        return verify_v1_bundle(
            evidence_dir,
            certificate=certificate,
            public_key=public_key,
            allow_bundled_key=allow_bundled_key,
            trusted_tsa_pem=trusted_tsa_pem,
            escrow_dir=escrow_dir,
            require_live_beacon=require_live_beacon,
            require_live_tsa=require_live_tsa,
        )

    if require_live_beacon or require_live_tsa:
        report.check(
            "live_crypto_required",
            False,
            "legacy v0.2 stub bundles cannot satisfy require_live_beacon or require_live_tsa",
        )
        return report.finish()

    def structure():
        count = payload["evidence"]["trial_count"]
        if type(count) is not int or not 1 <= count <= 10000:
            raise ValueError("unsupported trial count")
        prereg = read_json(bundle_path(root, "preregistration.json"), canonical=True)
        reveal = read_json(bundle_path(root, "seed_reveal.json"), canonical=True)
        close = read_json(bundle_path(root, "manifests/session_close.json"), canonical=True)
        task = read_json(bundle_path(root, "task_spec.json"), canonical=True)
        body = read_json(bundle_path(root, "body_configuration.json"), canonical=True)
        log = read_json(bundle_path(root, close["eval_log_path"]))
        return count, prereg, reveal, close, task, body, log

    loaded = report.capture("bundle_structure", structure)
    if loaded is None:
        return report.finish()
    count, prereg, reveal, close, task, body, log = loaded
    trials: list[dict | None] = []
    for index in range(count):
        name = f"manifests/trial_{index:04d}.json"
        path = bundle_path(root, name)
        if not path.is_file():
            report.check("missing_manifest", False, name)
            trials.append(None)
        else:
            trials.append(report.capture(
                "manifest_format", lambda path=path: read_json(path, canonical=True)
            ))

    def seed_checks():
        secret = decode_hex(reveal["S_hex"], length=32)
        nonce = decode_hex(reveal["nonce_hex"], length=16)
        submitter = decode_hex(reveal["submitter_N_hex"])
        beacon_value = decode_hex(reveal["beacon"]["value_hex"], length=32)
        commitment = read_json(root / "seed_commitment.json", canonical=True)
        report.check(
            "commitment_C",
            commit(secret, nonce) == reveal["commitment_C"]
            == prereg["seed"]["commitment_C"] == commitment["commitment_C"]
            == payload["seed"]["commitment_C"],
            "seed_reveal.json and preregistration",
        )
        public_values = {
            "commitment_C": reveal["commitment_C"],
            "submitter_N_hex": reveal["submitter_N_hex"], "beacon": reveal["beacon"],
        }
        report.check("seed_preregistration", public_values == prereg["seed"], "seed_reveal.json")
        report.check(
            "beacon",
            verify_stub_beacon(reveal["beacon"])
            and commitment["beacon_provider"] == reveal["beacon"]["provider"]
            and commitment["beacon_round_number"] == reveal["beacon"]["round_number"],
            "declared local stub beacon",
        )
        run_seed = derive_run_seed(secret, submitter, beacon_value)
        eval_seed = derive_eval_seed(run_seed)
        report.check("derived_R", run_seed.hex() == reveal["derived_R_hex"], "seed_reveal.json")
        report.check("certificate_seed", reveal == payload["seed"], "complete seed reveal")
        report.check(
            "eval_seed",
            type(log["eval"]["seed"]) is int
            and type(reveal["eval_seed"]) is int
            and log["eval"]["seed"] == reveal["eval_seed"] == eval_seed,
            f"{close['eval_log_path']}: eval.seed",
        )
        return run_seed, eval_seed

    seeds = report.capture("seed_integrity", seed_checks)
    plan = report.capture("preregistered_plan", lambda: make_plan(task))
    if plan is None or seeds is None:
        return report.finish()
    run_seed, eval_seed = seeds
    report.check("preregistered_plan", plan == prereg["planned_trials"], "task_spec.json")
    profile = prereg.get("bundle_profile")
    instruments = profile == "instruments-v0"
    report.check(
        "bundle_profile",
        profile in {"cubepick-mock-v0", "instruments-v0"}
        and profile == close.get("bundle_profile") == payload["evidence"].get("bundle_profile"),
        str(profile),
    )

    def chain():
        genesis = object_hash(prereg)
        report.check(
            "genesis_hash", genesis == close["genesis_hash"] == payload["evidence"]["genesis_hash"],
            "preregistration.json",
        )
        report.check(
            "trial_count",
            count == len(plan) == len(prereg["planned_trials"])
            == close["trial_count"] == log["results"]["total_trials"],
            "signed, planned, chained, and logged trial counts",
        )
        previous = genesis
        for index, trial in enumerate(trials):
            if trial is None:
                continue
            name = f"manifests/trial_{index:04d}.json"
            report.check(
                "manifest_version",
                trial.get("manifest_version") == "eutropos-trial-manifest-v0.2", name,
            )
            report.check(
                "trial_order", index < len(plan)
                and all(trial.get(k) == v for k, v in plan[index].items()), name,
            )
            report.check("prev_manifest_hash", trial["prev_manifest_hash"] == previous, name)
            previous = sha256_file(root / name)
        report.check(
            "session_close",
            close["manifest_version"] == "eutropos-session-close-v0.2"
            and close["prev_manifest_hash"] == previous,
            "manifests/session_close.json",
        )
        report.check(
            "chain_root_hash",
            sha256_file(root / "manifests/session_close.json") == payload["evidence"]["chain_root_hash"],
            "manifests/session_close.json",
        )

    report.capture("chain_integrity", chain)
    referenced: set[str] = set()
    verified_digests: dict[str, str] = {}

    def descriptor(entry):
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise ValueError("invalid file descriptor")
        name = validate_relative_path(entry["path"])
        report.check("duplicate_file_reference", name not in referenced, name)
        referenced.add(name)
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValueError("invalid file size")
        decode_hex(entry["sha256"], length=32)
        path = bundle_path(root, name)
        if report.check("file_missing", path.is_file(), name):
            size_ok = report.check("file_size", path.stat().st_size == entry["size_bytes"], name)
            actual_sha = sha256_file(path)
            sha_ok = report.check("file_sha256", actual_sha == entry["sha256"], name)
            if size_ok and sha_ok:
                verified_digests[name] = actual_sha

    for owner in [prereg, *(trial for trial in trials if trial is not None), close]:
        entries = owner.get("files")
        if not isinstance(entries, list):
            report.check("file_descriptors", False, "files must be a list")
            continue
        names = [entry.get("path") if isinstance(entry, dict) else None for entry in entries]
        report.check(
            "file_order",
            all(isinstance(name, str) for name in names)
            and names == sorted(name for name in names if isinstance(name, str)),
            "descriptor paths must be sorted",
        )
        for entry in entries:
            report.capture("file_descriptor", lambda entry=entry: descriptor(entry))

    def complete_inventory():
        actual = inventory(root)
        expected = referenced | {
            "preregistration.json", "certificate.json", "public_key.pem",
            "manifests/session_close.json",
            *(f"manifests/trial_{index:04d}.json" for index in range(count)),
        }
        for name in sorted(actual - expected):
            report.check("orphan_file", False, name)
        for name in sorted(expected - actual):
            report.check("missing_bundle_file", False, name)
        report.check("complete_inventory", actual == expected, "exact recursive file inventory")
        report.check(
            "certificate_copy",
            (root / "certificate.json").read_bytes() == certificate_path.read_bytes(),
            "bundled and supplied certificate bytes",
        )
        read_json(root / "certificate.json", canonical=True)
        report.check(
            "public_key_copy",
            public_key_bytes(load_public_key(root / "public_key.pem")) == public_key_bytes(key),
            "bundled and trusted public keys",
        )

    report.capture("inventory", complete_inventory)

    def metadata_checks():
        scorer_names = ["eutropos-mass", "eutropos-geometry"] if instruments else ["success_at_end"]
        report.check(
            "scoring_rule",
            prereg["scoring_rule"] == {
                "names": scorer_names, "overall": "all scores equal 1.0",
                "reducer": "mean", "interval": "Wilson", "confidence": 0.95,
            }
            and task["scorers"] == scorer_names and task["reducer"] == "mean",
            "fixed scoring predicates and aggregation",
        )
        expected_task = "eutropos-instruments-mock" if instruments else "cubepick-reach"
        expected_body = "eutropos-bench" if instruments else "cubepick"
        report.check(
            "task_identity",
            task["name"] == expected_task and prereg["configuration"]["task"] == expected_task
            and prereg["configuration"]["embodiment"]["name"] == expected_body,
            "supported mock profile",
        )
        report.check(
            "body_configuration",
            body == {
                "identity": prereg["configuration"]["embodiment"],
                "spaces": prereg["configuration"]["spaces"]["body"],
            },
            "body_configuration.json",
        )
        scenes = [
            {key: value for key, value in scene.items() if key != "family_id"}
            for scene in task["scenes"]
        ]
        report.check(
            "task_configuration",
            scenes == prereg["configuration"]["scenes"]
            and task["max_steps"] == prereg["configuration"]["max_steps"],
            "task_spec.json and preregistered configuration",
        )
        report.check(
            "eval_configuration",
            configuration_matches(log["configuration"], prereg["configuration"]),
            "EvalLog.configuration body, policy, task, and spaces",
        )
        report.check(
            "log_identity",
            log["version"] == 3 and log["status"] == "success" and log["error"] is None
            and log["eval"]["inspect_robots_version"] == "1.0.0"
            and log["eval"]["task"] == task["name"]
            and log["eval"]["policy"] == prereg["subject"]["name"]
            and log["eval"]["embodiment"] == expected_body
            and log["eval"]["max_steps"] == task["max_steps"]
            and log["eval"]["reducer"] == "mean"
            and log["eval"]["policy_config"] == prereg["configuration"]["policy"]["config"],
            "EvalLog identity and configuration",
        )
        paths = {entry["path"] for entry in prereg["files"]}
        fixed = {"seed_commitment.json", "body_configuration.json", "task_spec.json"}
        report.check(
            "preregistration_file_set",
            fixed <= paths and all(
                name in fixed or (
                    name.endswith(".py") and name.startswith(
                        ("provenance/inspect_robots/", "provenance/eutropos_referee/")
                    )
                ) for name in paths
            ),
            "preregistered source and configuration files",
        )
        recorded_ref_ver = prereg.get("hashes", {}).get("referee", {}).get("version")
        expected_ref_ver = (
            recorded_ref_ver if recorded_ref_ver in {"0.2.0", __version__} else __version__
        )
        report.check(
            "provenance_hashes",
            provenance_hashes(
                prereg["files"], prereg["hashes"]["scoring_code"]["path"],
                harness_version="1.0.0", referee_version=expected_ref_ver,
            ) == prereg["hashes"] == payload["hashes"],
            "package and configuration hashes",
        )
        for field_name in (
            "subject", "deviations_and_incidents", "operator_and_witness",
            "conflict_of_interest_statement",
        ):
            report.check(
                "certificate_metadata", payload[field_name] == prereg[field_name], field_name
            )
        closing = {close["eval_log_path"], "seed_reveal.json"}
        if instruments:
            closing.add("referee_targets.json")
        report.check(
            "closing_file_set", {entry["path"] for entry in close["files"]} == closing,
            "session-close file roles",
        )
        log_name = validate_relative_path(close["eval_log_path"])
        report.check("eval_log_location", "/" not in log_name and log_name.endswith(".json"), log_name)
        parts = validate_relative_path(close["frames_dir"]).split("/")
        report.check(
            "run_directories",
            len(parts) == 2 and parts[0] == "frames"
            and close["records_dir"] == f"records/{parts[-1]}"
            and close["actions_dir"] == f"actions/{parts[-1]}",
            "common native run stamp",
        )
        report.check(
            "log_directories",
            _native_path_matches(log["stats"]["frames_dir"], close["frames_dir"], absolute_allowed=True)
            and _native_path_matches(
                log["stats"]["records_dir"], close["records_dir"], absolute_allowed=True
            ),
            "EvalLog run directories",
        )
        report.check(
            "closing_timestamp",
            close["created_utc"] == log["stats"]["completed_at"] == payload["evidence"]["created_utc"]
            and payload["evidence"]["timestamp_stub"] == {
                "provider": "local-clock", "externally_verified": False,
                "value": close["created_utc"],
            },
            "local timestamp fields",
        )

    report.capture("metadata", metadata_checks)
    targets = None
    if instruments:
        targets = report.capture(
            "instrument_targets",
            lambda: read_json(root / "referee_targets.json", canonical=True),
        )
        if targets is not None:
            report.check(
                "instrument_targets",
                targets.get("schema") == "eutropos-targets-v0"
                and len(targets.get("trials", [])) == count,
                "target disclosure schema and count",
            )

    computed_trials: list[dict] = []
    records: dict[str, dict] = {}
    stamp = close["frames_dir"].split("/")[-1]
    for index, trial in enumerate(trials):
        if trial is None or index >= len(plan):
            continue
        planned = plan[index]
        name = trial["record_path"]
        record = report.capture("record_format", lambda name=name: read_json(bundle_path(root, name)))
        if record is None:
            continue
        records[trial["record_id"]] = record
        expected_seed = derive_seed(eval_seed, planned["scene_init_seed"], planned["epoch"])
        report.check(
            "trial_seed", type(trial["inspect_robots_trial_seed"]) is int
            and trial["inspect_robots_trial_seed"] == expected_seed,
            f"manifests/trial_{index:04d}.json",
        )
        instance = derive_instance_seed(run_seed, planned["family_id"], index)
        report.check(
            "derived_instance_seed", trial["derived_instance_seed_hex"] == instance.hex(),
            f"manifests/trial_{index:04d}.json",
        )

        def record_checks():
            report.check(
                "record_seed", type(record["seed"]) is int and record["seed"] == expected_seed, name
            )
            report.check(
                "record_trial_seed",
                type(record["configuration"]["trial_seed"]) is int
                and record["configuration"]["trial_seed"] == expected_seed, name,
            )
            report.check(
                "record_eval_seed",
                type(record["configuration"]["seed"]) is int
                and record["configuration"]["seed"] == eval_seed, name,
            )
            report.check(
                "record_identity",
                record["record_id"] == trial["record_id"]
                and record["scene_id"] == planned["scene_id"] and record["run_id"] == stamp, name,
            )
            report.check(
                "record_epoch",
                type(record["epoch"]) is int and record["epoch"] == planned["epoch"], name,
            )
            for event_index, event in enumerate(record["events"]):
                if event["kind"] in {"trial_start", "reset"}:
                    value = event["data"].get("seed")
                    report.check(
                        "record_event_seed",
                        type(value) is int and value == expected_seed,
                        f"{name}: events[{event_index}].data.seed",
                    )
            report.check(
                "record_configuration",
                configuration_matches(
                    record["configuration"], prereg["configuration"], trial=True
                ), name,
            )
            expected_scene = prereg["configuration"]["scenes"][planned["scene_index"]]
            report.check(
                "record_scene", record["configuration"]["scene"] == expected_scene, name,
            )
            report.check(
                "trial_status",
                trial["status"] == record["status"] == "success" and record["error"] is None, name,
            )

        report.capture("record_schema", record_checks)

        def recompute():
            base = f"{_safe(planned['scene_id'])}-e{planned['epoch']}"
            required = {
                f"records/{stamp}/{base}/record.json",
                f"records/{stamp}/{base}/chunks.jsonl",
                f"actions/{stamp}/{base}.jsonl",
                *trial["frame_paths"],
            }
            if (
                trial["record_path"] != f"records/{stamp}/{base}/record.json"
                or trial["chunks_path"] != f"records/{stamp}/{base}/chunks.jsonl"
                or trial["actions_path"] != f"actions/{stamp}/{base}.jsonl"
                or trial["frame_paths"] != sorted(set(trial["frame_paths"]))
                or any(
                    not path.startswith(f"frames/{stamp}/") or not path.endswith(".npy")
                    for path in trial["frame_paths"]
                )
            ):
                raise ValueError("trial file role mismatch")
            if instruments:
                expected_scale = f"instruments/{stamp}/{base}_scale.txt"
                expected_camera = f"instruments/{stamp}/{base}_overhead.json"
                if trial["scale_path"] != expected_scale or trial["overhead_path"] != expected_camera:
                    raise ValueError("instrument file role mismatch")
                required.update({expected_scale, expected_camera})
            if {entry["path"] for entry in trial["files"]} != required:
                raise ValueError("trial file set mismatch")
            actions, chunks = validate_native_artifacts(
                root, trial, record, prereg["configuration"], stamp,
            )
            if instruments:
                if targets is None:
                    raise ValueError("missing target disclosure")
                entry = targets["trials"][index]
                expected_spec = hidden_target_spec(
                    derive_trial_params(instance, planned["family_id"], planned["scene_index"])
                )
                if entry != {
                    "trial_index": index, "scene_id": planned["scene_id"],
                    "epoch": planned["epoch"], "spec": expected_spec,
                }:
                    raise ValueError("target disclosure differs from seed-derived assignment")
                if prereg["assignment_commitments"][str(index)] != object_hash(expected_spec):
                    raise ValueError("private assignment commitment mismatch")
                scale, camera = read_instrument_files(
                    bundle_path(root, trial["scale_path"]),
                    bundle_path(root, trial["overhead_path"]),
                    expected_end_s=record["steps"] / 10,
                )
                mass = evaluate_scale_stream(
                    scale, target_net_g=expected_spec["target_net_g"],
                    tolerance_g=expected_spec["tolerance_g"], tare_g=expected_spec["tare_g"],
                    settle_window_s=expected_spec["settle_window_s"],
                    max_step_delta_g=expected_spec["max_step_delta_g"],
                )
                geometry = evaluate_overhead_stream(
                    camera, target_spec=expected_spec,
                    settle_window_s=expected_spec["settle_window_s"],
                    max_bezel_drift_mm=expected_spec["max_bezel_drift_mm"],
                )
                blind, errors = verify_athlete_blindness(
                    prereg, record, actions, chunks, target_spec=expected_spec
                )
                report.check("athlete_blindness", blind, name + ": " + "; ".join(errors))
                scores = {
                    "eutropos-mass": float(mass.passed),
                    "eutropos-geometry": float(geometry.passed),
                }
            else:
                termination = record["termination"]
                if (
                    type(termination["terminated"]) is not bool
                    or type(termination["truncated"]) is not bool
                    or (termination["reason"] == "success" and not termination["terminated"])
                ):
                    raise ValueError("invalid termination fields")
                scores = {"success_at_end": float(termination["reason"] == "success")}
            report.check("recomputed_scores", scores == trial["scores"], name)
            latencies = record["referee"]["inference_latencies_s"]
            report.check(
                "record_diagnostics", latencies == trial["inference_latencies_s"], name
            )
            computed_trials.append({
                **trial, "scores": scores, "step_count": record["steps"],
                "inference_latencies_s": latencies,
            })

        report.capture("artifact_parsing", recompute)

    def aggregate():
        if not report.check(
            "complete_trial_set", len(computed_trials) == count,
            "every trial parsed and independently scored",
        ):
            return
        ids = [trial["record_id"] for trial in computed_trials]
        report.check("unique_record_ids", len(set(ids)) == count, "one record per trial")
        samples = log["samples"]
        scene_ids = [scene["id"] for scene in task["scenes"]]
        report.check(
            "sample_order", [sample["scene_id"] for sample in samples] == scene_ids,
            "EvalLog samples",
        )
        report.check(
            "sample_count",
            len(samples) == len(scene_ids) == log["results"]["total_scenes"]
            and sum(len(sample["epochs"]) for sample in samples) == count,
            "scene and epoch counts",
        )
        reductions = []
        for scene, sample in zip(task["scenes"], samples):
            group = [trial for trial in computed_trials if trial["scene_id"] == scene["id"]]
            scores = [trial["scores"] for trial in group]
            directories = [str(Path(trial["record_path"]).parent).replace("\\", "/") for trial in group]
            report.check(
                "sample_trials",
                len(group) == task["epochs"] and sample["status"] == "success"
                and sample["error"] is None and sample["epochs"] == scores
                and sample["record_ids"] == [trial["record_id"] for trial in group]
                and len(sample["record_dirs"]) == len(directories)
                and all(
                    _native_path_matches(actual, expected, absolute_allowed=False)
                    for actual, expected in zip(sample["record_dirs"], directories)
                ),
                f"EvalLog sample {scene['id']}",
            )
            reduced = {
                key: mean(trial["scores"][key] for trial in group)
                for key in task["scorers"]
            }
            reductions.append(reduced)
            report.check("sample_results", sample["reduced"] == reduced, scene["id"])
            report.check(
                "sample_events",
                sample["events"] == [records[trial["record_id"]]["events"] for trial in group],
                scene["id"],
            )
            if instruments:
                report.check(
                    "sample_blindness",
                    sample["scene_metadata"] == {}
                    and all(
                        transcript.get("scene_target_none") is True
                        and transcript.get("scene_metadata_empty") is True
                        for transcript in sample["policy_transcripts"]
                    ),
                    scene["id"],
                )
        computed = summarize(computed_trials)
        report.check(
            "certificate_results", computed == payload["results"],
            "raw-artifact scores, overall conjunction, and Wilson intervals",
        )
        metrics = {
            key: mean(reduced[key] for reduced in reductions) for key in task["scorers"]
        }
        report.check(
            "log_results",
            log["results"]["metrics"] == metrics and log["results"]["errored_trials"] == 0
            and log["results"]["abstentions"] == {},
            "EvalLog recomputed metrics",
        )
        report.check(
            "log_diagnostics",
            log["stats"]["total_steps"] == computed["diagnostics"]["total_steps"]
            and _number_equal(
                log["stats"]["mean_inference_latency_s"],
                computed["diagnostics"]["mean_inference_latency_s"],
            ),
            "reconciled steps and latency",
        )

    report.capture("aggregate_results", aggregate)
    setattr(report, "_verified_file_digests", verified_digests)
    return report.finish()
