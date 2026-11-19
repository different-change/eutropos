"""Run, verify, and exercise the CubePick and hidden-instrument proofs."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .bench_mock import CHEAT_POLICIES, POLICIES
from .calibration import (
    HomographyCalibration,
    calibrate_overhead_homography,
    generate_calibration_board,
    pre_trial_bench_check,
)
from .certificate import load_public_key, verify_certificate
from .hardware_drivers import MockCBCP01Transport, OverheadCameraDriver, RadwagCBCP01Driver
from .manifest import read_json, write_json
from .protocol_v1 import prove_v1
from .report_html import render_audit_html
from .runner import prepare_empty_directory, run_bundle, run_instruments_bundle
from .tamper import ATTACK_REASONS, INSTRUMENT_ATTACK_REASONS, copy_and_tamper
from .verifier import verify_bundle


def _print(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def _tamper_cases(root: Path, evidence: Path, trusted: Path, attacks: dict) -> dict:
    result = {}
    for attack, reason in attacks.items():
        destination = root / "tamper_tests" / attack
        altered = copy_and_tamper(evidence, destination, attack)
        report = verify_bundle(destination, public_key=trusted)
        detected = not report.passed and any(
            failure.startswith(reason + ":") for failure in report.failures
        )
        case = {
            "altered_path": altered, "expected_reason": reason,
            "detected_for_expected_reason": detected, "verification": asdict(report),
        }
        if attack == "rogue_key_cli_verify":
            with contextlib.redirect_stdout(io.StringIO()):
                default_code = main(["verify", "--evidence-dir", str(destination)])
                pinned_code = main([
                    "verify", "--evidence-dir", str(destination),
                    "--public-key", str(trusted),
                ])
            case["cli_default_returncode"] = default_code
            case["cli_pinned_returncode"] = pinned_code
            case["detected_for_expected_reason"] = detected and default_code != 0 and pinned_code != 0
        result[attack] = case
    return result


def prove(out_dir) -> tuple[bool, dict]:
    root = prepare_empty_directory(Path(out_dir))
    trusted = root / "trusted-referee-public.pem"
    evidence = run_bundle(
        root / "evidence", epochs=2, policy="scripted",
        write_trusted_public_key=trusted,
    )
    clean = verify_bundle(evidence, public_key=trusted)
    cases = _tamper_cases(root, evidence, trusted, ATTACK_REASONS) if clean.passed else {}
    result = {
        "passed": clean.passed and len(cases) == len(ATTACK_REASONS)
        and all(case["detected_for_expected_reason"] for case in cases.values()),
        "evidence_dir": str(evidence), "trusted_public_key": str(trusted),
        "clean": asdict(clean), "tamper_tests": cases,
    }
    write_json(root / "proof_report.json", result)
    return result["passed"], result


def prove_instruments(out_dir) -> tuple[bool, dict]:
    root = prepare_empty_directory(Path(out_dir))
    trusted = root / "trusted-referee-public.pem"
    evidence = run_instruments_bundle(
        root / "evidence", epochs=2, policy="compliant",
        write_trusted_public_key=trusted,
    )
    clean = verify_bundle(evidence, public_key=trusted)
    payload = verify_certificate(
        read_json(evidence / "certificate.json", canonical=True), load_public_key(trusted)
    )
    clean_score = payload["results"]["overall"]["pass_rate"]
    cheats = {}
    for policy in CHEAT_POLICIES:
        cheat_key = root / f"{policy}-trusted.pem"
        destination = run_instruments_bundle(
            root / "cheat_tests" / policy, epochs=2, policy=policy,
            write_trusted_public_key=cheat_key,
        )
        report = verify_bundle(destination, public_key=cheat_key)
        certificate = verify_certificate(
            read_json(destination / "certificate.json", canonical=True),
            load_public_key(cheat_key),
        )
        rate = certificate["results"]["overall"]["pass_rate"]
        blind_checks = [check for check in report.checks if check.name == "athlete_blindness"]
        cheats[policy] = {
            "verification": asdict(report), "pass_rate": rate,
            "caught": report.passed and rate == 0.0,
            "blindness_passed": len(blind_checks) == 8 and all(check.passed for check in blind_checks),
        }
    cases = (
        _tamper_cases(root, evidence, trusted, INSTRUMENT_ATTACK_REASONS)
        if clean.passed else {}
    )
    iso_key = root / "isolated-snooper-trusted.pem"
    iso_dir = run_instruments_bundle(
        root / "isolation_tests" / "memory-disk-snooper",
        epochs=1, policy="memory-disk-snooper", isolated=True,
        write_trusted_public_key=iso_key,
    )
    iso_report = verify_bundle(iso_dir, public_key=iso_key)
    iso_cert = verify_certificate(
        read_json(iso_dir / "certificate.json", canonical=True),
        load_public_key(iso_key),
    )
    iso_close = read_json(iso_dir / "manifests/session_close.json", canonical=True)
    iso_log = read_json(iso_dir / iso_close["eval_log_path"])
    snooper_transcripts = [
        tr.get("snooper", {})
        for sample in iso_log["samples"]
        for tr in sample.get("policy_transcripts", [])
    ]
    isolation_passed = (
        iso_report.passed
        and iso_cert["results"]["overall"]["pass_rate"] == 0.0
        and len(snooper_transcripts) == 4
        and all(
            t.get("isolated_cwd_empty") is True
            and t.get("loaded_instruments_module") is False
            and t.get("leaked_tokens") == []
            for t in snooper_transcripts
        )
    )
    passed = (
        clean.passed and clean_score == 1.0
        and all(case["caught"] and case["blindness_passed"] for case in cheats.values())
        and isolation_passed
        and len(cases) == len(INSTRUMENT_ATTACK_REASONS)
        and all(case["detected_for_expected_reason"] for case in cases.values())
    )
    result = {
        "passed": passed, "clean": asdict(clean), "clean_pass_rate": clean_score,
        "evidence_dir": str(evidence), "trusted_public_key": str(trusted),
        "cheat_tests": cheats,
        "isolation_test": {
            "passed": isolation_passed,
            "verification_passed": iso_report.passed,
            "pass_rate": iso_cert["results"]["overall"]["pass_rate"],
            "snooper_transcripts": snooper_transcripts,
        },
        "tamper_tests": cases,
    }
    write_json(root / "proof_report.json", result)
    return passed, result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="habilis-referee")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "run-instruments"):
        run = commands.add_parser(name)
        run.add_argument("--out-dir", required=True)
        run.add_argument("--epochs", type=int, default=2)
        run.add_argument(
            "--policy",
            choices=(*POLICIES, "memory-disk-snooper") if name == "run-instruments" else ("scripted", "random", "noop"),
            default="compliant" if name == "run-instruments" else "scripted",
        )
        run.add_argument("--submitter-value", default="submitter-demo")
        run.add_argument("--beacon-round", type=int, default=42)
        run.add_argument("--private-key", type=Path)
        run.add_argument("--write-trusted-public-key", type=Path)
        if name == "run-instruments":
            run.add_argument("--family-set", choices=("mixed", "e1", "e3"), default="mixed")
            run.add_argument("--isolated", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("--evidence-dir", required=True)
    verify.add_argument("--certificate", type=Path)
    verify.add_argument("--trusted-tsa-pem", type=Path)
    verify.add_argument("--escrow-dir", type=Path)
    verify.add_argument("--require-live-beacon", action="store_true")
    verify.add_argument("--require-live-tsa", action="store_true")
    trust = verify.add_mutually_exclusive_group()
    trust.add_argument("--public-key", type=Path)
    trust.add_argument("--trust-bundled-key", action="store_true")
    for name in ("prove", "prove-instruments", "prove-v1"):
        proof = commands.add_parser(name)
        proof.add_argument("--out-dir", required=True)
        if name == "prove-v1":
            proof.add_argument("--live-crypto", action="store_true")

    cal = commands.add_parser("calibrate")
    cal.add_argument("--board-png", type=Path, required=True)
    cal.add_argument("--out-json", type=Path)

    bchk = commands.add_parser("bench-check")
    bchk.add_argument("--port", default="mock://")
    bchk.add_argument("--board-png", type=Path)
    bchk.add_argument("--camera-backend", choices=("mock", "opencv", "pypylon"), default="mock")
    bchk.add_argument("--camera-device", type=int, default=0)
    bchk.add_argument("--calibration-json", type=Path)

    rep_p = commands.add_parser("render-report")
    rep_p.add_argument("--evidence-dir", type=Path, required=True)
    rep_p.add_argument("--out", type=Path, required=True)
    rep_p.add_argument("--trusted-tsa-pem", type=Path)
    rep_p.add_argument("--escrow-dir", type=Path)
    rep_p.add_argument("--require-live-beacon", action="store_true")
    rep_p.add_argument("--require-live-tsa", action="store_true")
    rtrust = rep_p.add_mutually_exclusive_group()
    rtrust.add_argument("--public-key", type=Path)
    rtrust.add_argument("--trust-bundled-key", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "calibrate":
            import numpy as np
            from PIL import Image

            spec = generate_calibration_board(args.board_png)
            rgb = np.asarray(Image.open(spec.png_path).convert("RGB"), dtype=np.uint8)
            hom = calibrate_overhead_homography(rgb)
            doc = asdict(hom)
            if args.out_json is not None:
                write_json(args.out_json, doc)
            _print(doc)
            return 0
        if args.command == "bench-check":
            import numpy as np
            from PIL import Image

            cal_hom: HomographyCalibration | None = None
            mock_rgb: np.ndarray | None = None
            if args.camera_backend == "mock":
                tmp_board = args.board_png
                if tmp_board is not None:
                    spec = generate_calibration_board(tmp_board)
                    mock_rgb = np.asarray(Image.open(spec.png_path).convert("RGB"), dtype=np.uint8)
                else:
                    import tempfile

                    with tempfile.TemporaryDirectory() as td:
                        spec = generate_calibration_board(Path(td) / "board.png")
                        mock_rgb = np.asarray(Image.open(spec.png_path).convert("RGB"), dtype=np.uint8)
                cal_hom = calibrate_overhead_homography(mock_rgb)
            elif args.calibration_json is not None:
                cal_doc = read_json(args.calibration_json)
                cal_hom = HomographyCalibration(**cal_doc)

            if args.port == "mock://":
                tr = MockCBCP01Transport([(0.0, " ")] * 6)
                tick = {"ns": 0}
                scale_drv = RadwagCBCP01Driver(
                    transport=tr,
                    clock_ns=lambda: tick.__setitem__("ns", tick["ns"] + 50_000_000) or tick["ns"],
                )
            else:
                scale_drv = RadwagCBCP01Driver(args.port)
            scale_drv.enable_continuous()
            if args.camera_backend == "mock":
                cam_drv = OverheadCameraDriver(backend="mock", frame_provider=lambda _i: mock_rgb)
            else:
                cam_drv = OverheadCameraDriver(backend=args.camera_backend, device_index=args.camera_device)
            if cal_hom is None:
                frame = cam_drv.grab_frame(0)
                cal_hom = calibrate_overhead_homography(frame.rgb)
            try:
                rep = pre_trial_bench_check(
                    scale_driver=scale_drv, camera_driver=cam_drv, calibration=cal_hom,
                )
            finally:
                scale_drv.close()
                cam_drv.close()
            _print(asdict(rep))
            return 0 if rep.passed else 1
        if args.command == "render-report":
            html_doc = render_audit_html(
                args.evidence_dir,
                public_key=args.public_key,
                allow_bundled_key=args.trust_bundled_key,
                trusted_tsa_pem=args.trusted_tsa_pem,
                escrow_dir=args.escrow_dir,
                require_live_beacon=args.require_live_beacon,
                require_live_tsa=args.require_live_tsa,
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(html_doc, encoding="utf-8")
            _print({"rendered": str(args.out), "bytes": len(html_doc)})
            return 0
        if args.command == "verify":
            report = verify_bundle(
                args.evidence_dir, certificate=args.certificate,
                public_key=args.public_key, allow_bundled_key=args.trust_bundled_key,
                trusted_tsa_pem=args.trusted_tsa_pem,
                escrow_dir=args.escrow_dir,
                require_live_beacon=args.require_live_beacon,
                require_live_tsa=args.require_live_tsa,
            )
            _print(asdict(report))
            return 0 if report.passed else 1
        if args.command == "prove-v1":
            passed, result = prove_v1(args.out_dir, live_crypto=bool(args.live_crypto))
            _print(result)
            return 0 if passed else 1
        if args.command in {"prove", "prove-instruments"}:
            operation = prove if args.command == "prove" else prove_instruments
            passed, result = operation(args.out_dir)
            _print(result)
            return 0 if passed else 1
        out = Path(args.out_dir).absolute()
        trusted = args.write_trusted_public_key or out.with_name(out.name + ".trusted.pem")
        kwargs = {
            "epochs": args.epochs, "policy": args.policy,
            "beacon_round": args.beacon_round, "private_key": args.private_key,
            "write_trusted_public_key": trusted,
        }
        if args.command == "run-instruments":
            root = run_instruments_bundle(
                out, **kwargs, submitter=args.submitter_value,
                family_set=args.family_set, isolated=args.isolated,
            )
        else:
            root = run_bundle(out, **kwargs, submitter_value=args.submitter_value)
        report = verify_bundle(root, public_key=trusted)
        _print({
            "evidence_dir": str(root), "trusted_public_key": str(trusted),
            "verification": asdict(report),
        })
        return 0 if report.passed else 1
    except Exception as exc:
        _print({"passed": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 2
