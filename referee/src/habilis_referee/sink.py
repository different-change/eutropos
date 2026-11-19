"""Seal native logs after scorer-time instrument flushing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspect_robots.frames import _safe
from inspect_robots.logging.sink import NullSink
from inspect_robots.rollout import derive_seed
from inspect_robots.scorer import success_at_end

from .certificate import CERTIFICATE_VERSION, sign_certificate, write_public_key
from .instruments import InstrumentSession, verify_athlete_blindness
from .manifest import (
    file_entries, object_hash, read_json, read_jsonl,
    relative_path, sha256_file, write_json,
)
from .results import summarize
from .schema import (
    configuration_matches, observation_document, plain,
    scene_document, space_document,
)
from .scorers import InstrumentGeometryScorer, InstrumentMassScorer
from .seed import derive_instance_seed


class RefereeSink(NullSink):
    critical = True

    def __init__(
        self, log_dir: str = "logs", *,
        preregistration=None, sealed_seed=None, json_sink=None,
        private_key=None, session: InstrumentSession | None = None,
    ) -> None:
        self.root = Path(log_dir).absolute()
        self.preregistration = preregistration
        self.sealed_seed = sealed_seed
        self.json_sink = json_sink
        self.private_key = private_key
        self._session = session
        self.frames_dir: Path | None = None
        self.spaces = None
        self.scenes: dict[str, Any] = {}
        self.trials: list[dict] = []
        self.pending: tuple[str, int] | None = None
        self.genesis_hash = None
        self.previous_hash = None
        self.started = False
        self.closed = False
        self._views: list[dict] = []
        self._runtime: dict = {}

    def bind_spaces(self, action_space, observation_space) -> None:
        self.spaces = (action_space, observation_space)

    def bind_frames_dir(self, frames_dir: str | None) -> None:
        self.frames_dir = Path(frames_dir).absolute() if frames_dir else None

    def bind_scenes(self, scenes) -> None:
        self.scenes = {scene.id: scene for scene in scenes}

    def on_eval_start(self, spec) -> None:
        if self.started or any(value is None for value in (
            self.preregistration, self.sealed_seed, self.json_sink,
            self.private_key, self.frames_dir, self.spaces,
        )):
            raise ValueError("RefereeSink requires one configured sealed session")
        assert self.frames_dir is not None
        assert self.spaces is not None
        expected = self.preregistration["configuration"]
        runtime = {
            "task": spec.task, "inspect_robots_version": spec.inspect_robots_version,
            "seed": spec.seed, "max_steps": spec.max_steps, "max_seconds": spec.max_seconds,
            "policy": {
                "name": spec.policy, "checkpoint": spec.policy_checkpoint,
                "config": plain(spec.policy_config),
            },
            "embodiment": {"name": spec.embodiment, **plain(spec.embodiment_info)},
            "spaces": {
                "body": space_document(*self.spaces),
                "policy": expected["spaces"]["policy"],
            },
            "scenes": [scene_document(scene) for scene in self.scenes.values()],
        }
        if not configuration_matches(runtime, expected):
            raise ValueError("bound evaluation differs from preregistered configuration")
        if spec.seed != self.sealed_seed.eval_seed:
            raise ValueError("evaluation seed differs from sealed seed")
        if read_json(self.root / "preregistration.json", canonical=True) != self.preregistration:
            raise ValueError("preregistration changed before evaluation")
        if relative_path(self.root, self.frames_dir).split("/")[0] != "frames":
            raise ValueError("invalid frame directory")
        self._runtime = runtime
        self.genesis_hash = object_hash(self.preregistration)
        self.previous_hash = self.genesis_hash
        self.started = True
        if self._session is not None:
            self._session.bind(self.root, self.frames_dir.name)

    def on_trial_start(self, scene_id: str, epoch: int) -> None:
        if not self.started or self.closed or self.pending is not None:
            raise ValueError("invalid trial lifecycle")
        plan = self.preregistration["planned_trials"]
        index = len(self.trials)
        if index >= len(plan) or (scene_id, epoch) != (plan[index]["scene_id"], plan[index]["epoch"]):
            raise ValueError("unplanned trial order")
        self.pending = (scene_id, epoch)
        self._views = []
        if self._session is not None:
            self._session.begin_trial(scene_id, epoch)

    def log_step(self, t, observation, action, result) -> None:
        self._views.append({
            "t": t,
            "observation": observation_document(observation),
            "result_observation": observation_document(result.observation),
            "action_meta": plain(dict(action.meta)),
            "result_info": plain(dict(result.info)),
        })

    def on_trial_end(self, record) -> None:
        assert self.frames_dir is not None
        if self.pending != (record.scene_id, record.epoch) or record.status != "success":
            raise ValueError("trial lifecycle or completion mismatch")
        index = len(self.trials)
        planned = self.preregistration["planned_trials"][index]
        if record.seed != derive_seed(
            self.sealed_seed.eval_seed, planned["scene_init_seed"], record.epoch
        ):
            raise ValueError("framework trial seed mismatch")
        stamp = self.frames_dir.name
        base = f"{_safe(record.scene_id)}-e{record.epoch}"
        record_path = self.root / "records" / stamp / base / "record.json"
        chunks_path = record_path.with_name("chunks.jsonl")
        actions_path = self.root / "actions" / stamp / f"{base}.jsonl"
        document = read_json(record_path)
        document["configuration"]["spaces"] = self._runtime["spaces"]
        document["configuration"]["scene"]["target"] = scene_document(
            self.scenes[record.scene_id]
        )["target"]
        document["referee"] = {
            "inference_latencies_s": [float(value) for value in record.inference_latencies],
            "athlete_views": self._views,
        }
        if not configuration_matches(
            document["configuration"], self.preregistration["configuration"], trial=True
        ):
            raise ValueError("native record configuration differs from preregistration")
        write_json(record_path, document)
        frame_index: dict[str, dict] = {}
        for step in record.steps:
            for t, references in (
                (step.t, step.image_refs), (step.t + 1, step.result_image_refs),
            ):
                for camera, reference in (references or {}).items():
                    name = relative_path(self.root, Path(reference.path).absolute())
                    if not name.startswith(f"frames/{stamp}/") or not name.endswith(".npy"):
                        raise ValueError("unexpected frame reference")
                    descriptor = {"path": name, "camera": camera, "t": t}
                    if name in frame_index and frame_index[name] != descriptor:
                        raise ValueError("frame reference reused for different observations")
                    frame_index[name] = descriptor
        if not frame_index:
            raise ValueError("trial has no stored frames")
        paths = [record_path, chunks_path, actions_path]
        paths.extend(self.root / name for name in sorted(frame_index))
        instrument_paths: dict[str, str] = {}
        if self._session is None:
            scores = {
                "success_at_end": float(
                    success_at_end()(record, self.scenes[record.scene_id].target).value
                )
            }
        else:
            scale_path, camera_path = self._session.flush_trial_files(record)
            paths.extend([scale_path, camera_path])
            instrument_paths = {
                "scale_path": relative_path(self.root, scale_path),
                "overhead_path": relative_path(self.root, camera_path),
            }
            scores = {
                "habilis-mass": float(InstrumentMassScorer(self._session)(record).value),
                "habilis-geometry": float(InstrumentGeometryScorer(self._session)(record).value),
            }
            blind, errors = verify_athlete_blindness(
                self.preregistration, document,
                read_jsonl(actions_path), read_jsonl(chunks_path),
            )
            if not blind:
                raise ValueError("athlete blindness failed: " + "; ".join(errors))
        manifest = {
            "manifest_version": "habilis-trial-manifest-v0.2",
            **planned, **instrument_paths,
            "record_id": record.record_id,
            "inspect_robots_trial_seed": record.seed,
            "derived_instance_seed_hex": derive_instance_seed(
                self.sealed_seed.run_seed, planned["family_id"], index
            ).hex(),
            "prev_manifest_hash": self.previous_hash,
            "record_path": relative_path(self.root, record_path),
            "chunks_path": relative_path(self.root, chunks_path),
            "actions_path": relative_path(self.root, actions_path),
            "frame_paths": sorted(frame_index),
            "frame_index": [frame_index[name] for name in sorted(frame_index)],
            "step_count": len(record.steps),
            "inference_latencies_s": document["referee"]["inference_latencies_s"],
            "scores": scores, "status": record.status,
            "files": file_entries(self.root, paths),
        }
        path = self.root / "manifests" / f"trial_{index:04d}.json"
        write_json(path, manifest)
        self.previous_hash = sha256_file(path)
        self.trials.append(manifest)
        self.pending = None

    def on_eval_end(self, log) -> None:
        assert self.frames_dir is not None
        if (
            not self.started or self.closed or self.pending is not None
            or log.status != "success"
            or len(self.trials) != len(self.preregistration["planned_trials"])
            or log.results.total_trials != len(self.trials)
        ):
            raise ValueError("incomplete evaluation")
        if self.json_sink.path is None or not self.json_sink.path.is_file():
            raise ValueError("JsonLogSink must finish before RefereeSink")
        log_path = self.json_sink.path
        disk_log = read_json(log_path)
        disk_log["configuration"] = self._runtime
        write_json(log_path, disk_log)
        reveal_path = self.root / "seed_reveal.json"
        write_json(reveal_path, self.sealed_seed.reveal())
        closing_paths = [log_path, reveal_path]
        if self._session is not None:
            closing_paths.append(self._session.disclose_targets(self.trials))
        stamp = self.frames_dir.name
        close = {
            "manifest_version": "habilis-session-close-v0.2",
            "bundle_profile": self.preregistration["bundle_profile"],
            "genesis_hash": self.genesis_hash,
            "prev_manifest_hash": self.previous_hash,
            "trial_count": len(self.trials),
            "eval_log_path": relative_path(self.root, log_path),
            "frames_dir": f"frames/{stamp}", "records_dir": f"records/{stamp}",
            "actions_dir": f"actions/{stamp}",
            "created_utc": log.stats.completed_at,
            "files": file_entries(self.root, closing_paths),
        }
        close_path = self.root / "manifests" / "session_close.json"
        write_json(close_path, close)
        payload = {
            "certificate_version": CERTIFICATE_VERSION,
            "subject": self.preregistration["subject"],
            "hashes": self.preregistration["hashes"],
            "seed": self.sealed_seed.reveal(),
            "evidence": {
                "bundle_profile": self.preregistration["bundle_profile"],
                "genesis_hash": self.genesis_hash,
                "chain_root_hash": sha256_file(close_path),
                "trial_count": len(self.trials),
                "created_utc": close["created_utc"],
                "timestamp_stub": {
                    "provider": "local-clock", "externally_verified": False,
                    "value": close["created_utc"],
                },
            },
            "results": summarize(self.trials),
            "deviations_and_incidents": self.preregistration["deviations_and_incidents"],
            "operator_and_witness": self.preregistration["operator_and_witness"],
            "conflict_of_interest_statement": self.preregistration["conflict_of_interest_statement"],
        }
        write_public_key(self.root / "public_key.pem", self.private_key.public_key())
        write_json(self.root / "certificate.json", sign_certificate(payload, self.private_key))
        self.closed = True


def referee_sink(log_dir: str = "logs", **kwargs) -> RefereeSink:
    return RefereeSink(log_dir, **kwargs)
