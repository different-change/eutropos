"""Blinded VLM judge harness and statistical analysis matching spec/JUDGE-EXPERIMENT-v0.md."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, PngImagePlugin

Z_95 = 1.959963984540054


def wilson_ci(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = successes / n
    den = 1.0 + (z * z) / n
    cen = p + (z * z) / (2.0 * n)
    half = z * math.sqrt((p * (1.0 - p)) / n + (z * z) / (4.0 * n * n))
    return (max(0.0, round((cen - half) / den, 6)), min(1.0, round((cen + half) / den, 6)))


def cohens_kappa(y_true: list[int], y_pred: list[int]) -> float:
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("nonempty aligned binary arrays required")
    n = len(y_true)
    agree = sum(int(a == b) for a, b in zip(y_true, y_pred))
    po = agree / n
    p_t1 = sum(y_true) / n
    p_p1 = sum(y_pred) / n
    pe = p_t1 * p_p1 + (1.0 - p_t1) * (1.0 - p_p1)
    if abs(1.0 - pe) < 1e-12:
        return 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    return (po - pe) / (1.0 - pe)


def exact_mcnemar_pvalue(b_only_a: int, c_only_b: int) -> float:
    if type(b_only_a) is not int or type(c_only_b) is not int or b_only_a < 0 or c_only_b < 0:
        raise ValueError("McNemar discordant counts must be non-negative integers")
    total = b_only_a + c_only_b
    if total == 0:
        return 1.0
    k = min(b_only_a, c_only_b)
    num = 2 * sum(math.comb(total, i) for i in range(k + 1))
    return min(1.0, num / (1 << total))


@dataclass(frozen=True)
class TrialBlindPackage:
    opaque_id: str
    instruction: str
    head_left_paths: tuple[Path, ...]
    head_right_paths: tuple[Path, ...]
    staging_dir: Path


def _save_clean_png(rgb_uint8: np.ndarray, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(np.asarray(rgb_uint8, dtype=np.uint8), mode="RGB")
    info = PngImagePlugin.PngInfo()
    img.save(dest, format="PNG", pnginfo=info)
    return dest


def export_blinded_trial_frames(
    root: Path,
    opaque_id: str,
    instruction: str,
    left_frames: list[np.ndarray],
    right_frames: list[np.ndarray],
) -> TrialBlindPackage:
    """Export only sanitized athlete PNG views and public instruction under opaque ID."""
    if not left_frames or len(left_frames) != len(right_frames):
        raise ValueError("aligned nonempty left/right frame sequences required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", opaque_id):
        raise ValueError("opaque_id must match [A-Za-z0-9_-]{6,64}")
    trial_dir = root / opaque_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    left_paths = tuple(
        _save_clean_png(arr, trial_dir / f"cam_left_{i:02d}.png")
        for i, arr in enumerate(left_frames)
    )
    right_paths = tuple(
        _save_clean_png(arr, trial_dir / f"cam_right_{i:02d}.png")
        for i, arr in enumerate(right_frames)
    )
    return TrialBlindPackage(opaque_id, instruction, left_paths, right_paths, trial_dir)


def export_blind_inbox(root: Path, packages: list[TrialBlindPackage]) -> Path:
    """Write blind_manifest.json containing only opaque IDs, public instructions, and frame relpaths."""
    manifest_rows = []
    for pkg in packages:
        manifest_rows.append({
            "opaque_id": pkg.opaque_id,
            "instruction": pkg.instruction,
            "left_frames": [p.relative_to(root).as_posix() for p in pkg.head_left_paths],
            "right_frames": [p.relative_to(root).as_posix() for p in pkg.head_right_paths],
        })
    out_path = root / "blind_manifest.json"
    out_path.write_text(json.dumps({"trials": manifest_rows}, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _parse_verdict(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            verdict = str(obj.get("verdict", "")).upper().strip()
            reason = str(obj.get("reason", ""))
            if verdict in {"PASS", "FAIL", "PARTIAL", "UNSURE"}:
                return verdict, reason
        except Exception:
            pass
    m = re.fullmatch(r"\s*(PASS|FAIL|PARTIAL|UNSURE)\s*[.!]?\s*", cleaned.upper())
    if m:
        return m.group(1), cleaned[:240]
    return "UNSURE", f"unparsed response: {cleaned[:200]}"


def _find_codex_binary() -> str:
    return shutil.which("codex.cmd") or shutil.which("codex") or "codex.cmd"


def _find_claude_binary() -> str:
    hit = shutil.which("claude.exe") or shutil.which("claude")
    if hit:
        return hit
    for name in ("claude.exe", "claude"):
        candidate = Path.home() / ".local" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return "claude"


def run_codex_vision(prompt: str, image_paths: list[Path], *, timeout_s: int = 120) -> tuple[str, float]:
    t0 = time.monotonic()
    codex_bin = _find_codex_binary()
    with tempfile.TemporaryDirectory(prefix="vlm_a_") as td:
        out_path = Path(td) / "out.txt"
        cmd = [codex_bin, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
               "-c", 'approval_policy="never"', "-C", td]
        for p in image_paths:
            cmd.extend(["-i", str(p)])
        cmd.extend(["-o", str(out_path), "-"])
        res = subprocess.run(
            cmd, input=prompt.encode("utf-8"), cwd=td,
            capture_output=True, timeout=timeout_s,
        )
        if res.returncode != 0 or not out_path.exists():
            raise RuntimeError(
                f"codex exec failed rc={res.returncode}: {res.stderr.decode('utf-8', 'replace')[:240]}"
            )
        return out_path.read_text("utf-8"), time.monotonic() - t0


def run_claude_vision(prompt: str, image_paths: list[Path], *, timeout_s: int = 120) -> tuple[str, float]:
    t0 = time.monotonic()
    claude_bin = _find_claude_binary()
    content: list[dict[str, Any]] = []
    for p in image_paths:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        })
    content.append({"type": "text", "text": prompt})
    payload = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
    with tempfile.TemporaryDirectory(prefix="vlm_c_") as td:
        cmd = [
            claude_bin, "-p", "--no-session-persistence",
            "--model", "opus", "--effort", "high",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep",
        ]
        res = subprocess.run(
            cmd, input=payload.encode("utf-8"), cwd=td,
            capture_output=True, timeout=timeout_s,
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"claude cli failed rc={res.returncode}: {res.stderr.decode('utf-8', 'replace')[:240]}"
            )
        text_out = ""
        for line in res.stdout.decode("utf-8", "replace").splitlines():
            if '"type":"result"' in line or '"type": "result"' in line:
                obj = json.loads(line)
                if obj.get("is_error"):
                    raise RuntimeError(f"claude error: {obj.get('result')}")
                text_out = str(obj.get("result", ""))
        if not text_out:
            raise RuntimeError("empty result from claude stream-json")
        return text_out, time.monotonic() - t0


def run_gemini_vision(
    prompt: str,
    image_paths: list[Path],
    *,
    model: str = "gemini-4-neon",
    api_key: str | None = None,
    transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    timeout_s: int = 120,
) -> tuple[str, float]:
    """Call Gemini generateContent REST endpoint (or injected mock transport) on stereo PNGs."""
    t0 = time.monotonic()
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if transport is None and not key:
        raise RuntimeError("GEMINI_API_KEY required unless custom transport is supplied")
    parts: list[dict[str, Any]] = [
        {
            "inlineData": {
                "mimeType": "image/png",
                "data": base64.b64encode(p.read_bytes()).decode("ascii"),
            }
        }
        for p in image_paths
    ]
    parts.append({"text": prompt})
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.0},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    if transport is not None:
        resp_obj = transport(url, body)
    else:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["x-goog-api-key"] = key
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urlopen(req, timeout=timeout_s) as resp:
            resp_obj = json.loads(resp.read(4 * 1024 * 1024).decode("utf-8"))
    candidates = resp_obj.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"empty Gemini candidates: {resp_obj}")
    text_parts = [
        str(p.get("text", ""))
        for p in candidates[0].get("content", {}).get("parts", [])
        if "text" in p
    ]
    return "\n".join(text_parts), time.monotonic() - t0


def _call_with_retry(
    fn: Callable[[str, list[Path]], tuple[str, float]],
    prompt: str,
    images: list[Path],
) -> tuple[str, str, float, str | None]:
    last_err: str | None = None
    total_lat = 0.0
    for attempt in range(2):
        try:
            raw, lat = fn(prompt, images)
            total_lat += lat
            verdict, reason = _parse_verdict(raw)
            return verdict, reason, total_lat, None
        except Exception as exc:
            last_err = str(exc)
            if attempt == 0:
                time.sleep(1.5)
    return "UNSURE", f"transport_error: {last_err}", total_lat, last_err


def _judge_prompt(instruction: str, frame_desc: str) -> str:
    return (
        "Do not call any shell or file tools. You are grading a physical manipulation trial "
        "from stereo head RGB frames only.\n"
        f"Task instruction: {instruction}\n"
        f"Attached images: {frame_desc}.\n"
        "Judge strictly whether the physical outcome satisfies the task instruction completely, "
        "checking orientation/seating, alignment, release, integrity, and target material/count.\n"
        'Reply ONLY with strict JSON: {"verdict":"PASS"|"FAIL"|"PARTIAL"|"UNSURE","reason":"brief explanation"}'
    )


def score_trial_robodojo_astra(
    pkg: TrialBlindPackage,
    *,
    runner: Callable[[str, list[Path]], tuple[str, float]] | None = None,
) -> dict[str, Any]:
    call = runner or run_codex_vision
    # Up to 4 pairs across sequence (start, mid, pre-end, final) matching head-stereo sequence
    n = len(pkg.head_left_paths)
    idxs = sorted({0, n // 3, (2 * n) // 3, n - 1})
    imgs: list[Path] = []
    for idx in idxs:
        imgs.append(pkg.head_left_paths[idx])
        imgs.append(pkg.head_right_paths[idx])
    prompt = _judge_prompt(
        pkg.instruction, f"{len(idxs)} timepoints x (left, right) stereo frames through final frame"
    )
    verdict, reason, lat_s, err = _call_with_retry(call, prompt, imgs)
    return {
        "judge": "robodojo_astra",
        "opaque_id": pkg.opaque_id,
        "category": verdict,
        "v_binary": int(verdict == "PASS"),
        "abstained": verdict == "UNSURE",
        "reason": reason,
        "latency_s": round(lat_s, 3),
        "transport_error": err,
    }


def score_trial_datacenterbench_dual(
    pkg: TrialBlindPackage,
    *,
    astra_runner: Callable[[str, list[Path]], tuple[str, float]] | None = None,
    claude_runner: Callable[[str, list[Path]], tuple[str, float]] | None = None,
) -> dict[str, Any]:
    a_call = astra_runner or run_codex_vision
    c_call = claude_runner or run_claude_vision
    imgs = [
        pkg.head_left_paths[0], pkg.head_right_paths[0],
        pkg.head_left_paths[-1], pkg.head_right_paths[-1],
    ]
    prompt = _judge_prompt(pkg.instruction, "start stereo pair followed by final stereo pair")
    va, ra, la, ea = _call_with_retry(a_call, prompt, imgs)
    vc, rc, lc, ec = _call_with_retry(c_call, prompt, imgs)
    if va == vc and va != "UNSURE":
        category = va
        abstained = False
    else:
        category = "UNSURE"
        abstained = True
    return {
        "judge": "datacenterbench_dual",
        "opaque_id": pkg.opaque_id,
        "category": category,
        "v_binary": int(category == "PASS"),
        "abstained": abstained,
        "astra": {"category": va, "reason": ra, "latency_s": round(la, 3), "error": ea},
        "claude": {"category": vc, "reason": rc, "latency_s": round(lc, 3), "error": ec},
        "latency_s": round(la + lc, 3),
    }


def score_trial_claude_opus(
    pkg: TrialBlindPackage,
    *,
    runner: Callable[[str, list[Path]], tuple[str, float]] | None = None,
) -> dict[str, Any]:
    call = runner or run_claude_vision
    imgs = [
        pkg.head_left_paths[0], pkg.head_right_paths[0],
        pkg.head_left_paths[-1], pkg.head_right_paths[-1],
    ]
    prompt = _judge_prompt(pkg.instruction, "start stereo pair followed by final stereo pair")
    verdict, reason, lat_s, err = _call_with_retry(call, prompt, imgs)
    return {
        "judge": "claude_opus_5_5",
        "opaque_id": pkg.opaque_id,
        "category": verdict,
        "v_binary": int(verdict == "PASS"),
        "abstained": verdict == "UNSURE",
        "reason": reason,
        "latency_s": round(lat_s, 3),
        "transport_error": err,
    }


def score_trial_gemini_neon(
    pkg: TrialBlindPackage,
    *,
    runner: Callable[[str, list[Path]], tuple[str, float]] | None = None,
) -> dict[str, Any]:
    call = runner or run_gemini_vision
    n = len(pkg.head_left_paths)
    idxs = sorted({0, n // 2, n - 1})
    imgs: list[Path] = []
    for idx in idxs:
        imgs.append(pkg.head_left_paths[idx])
        imgs.append(pkg.head_right_paths[idx])
    prompt = _judge_prompt(
        pkg.instruction, f"{len(idxs)} timepoints x (left, right) stereo frames through final frame"
    )
    verdict, reason, lat_s, err = _call_with_retry(call, prompt, imgs)
    return {
        "judge": "gemini_4_neon",
        "opaque_id": pkg.opaque_id,
        "category": verdict,
        "v_binary": int(verdict == "PASS"),
        "abstained": verdict == "UNSURE",
        "reason": reason,
        "latency_s": round(lat_s, 3),
        "transport_error": err,
    }


def analyze_a4_results(
    records: list[dict[str, Any]],
    *,
    judge_keys: tuple[str, ...] | None = None,
    bootstrap_n: int = 10000,
    seed: int = 20261118,
) -> dict[str, Any]:
    """Compute exact JUDGE-EXPERIMENT-v0 metrics, Wilson CIs, McNemar, and bootstrap intervals."""
    if not records:
        raise ValueError("at least one trial record required")
    judges = judge_keys or ("robodojo_astra", "datacenterbench_dual")
    summary: dict[str, Any] = {"n_trials": len(records), "judges": {}}

    for judge in judges:
        y_true = [int(r["ground_truth"]) for r in records]
        y_pred = [int(r[judge]["v_binary"]) for r in records]
        abst = [bool(r[judge]["abstained"]) for r in records]
        neg_idx = [i for i, g in enumerate(y_true) if g == 0]
        pos_idx = [i for i, g in enumerate(y_true) if g == 1]
        fp = sum(y_pred[i] for i in neg_idx)
        fn = sum(1 - y_pred[i] for i in pos_idx)
        acc_count = sum(int(a == b) for a, b in zip(y_true, y_pred))
        cov_count = sum(1 for a in abst if not a)
        strict_count = sum(int((not abst[i]) and y_pred[i] == y_true[i]) for i in range(len(records)))

        per_stratum: dict[str, Any] = {}
        raw_fpr_by_stratum: dict[str, float | None] = {}
        raw_ffr_by_stratum: dict[str, float | None] = {}
        for stratum in ("S1", "S2", "S3", "S4"):
            sub = [i for i, r in enumerate(records) if r["stratum"] == stratum]
            if not sub:
                raw_fpr_by_stratum[stratum] = None
                raw_ffr_by_stratum[stratum] = None
                continue
            s_neg = [i for i in sub if y_true[i] == 0]
            s_pos = [i for i in sub if y_true[i] == 1]
            s_fp = sum(y_pred[i] for i in s_neg)
            s_fn = sum(1 - y_pred[i] for i in s_pos)
            s_cov = sum(1 for i in sub if not abst[i])
            s_strict = sum(int((not abst[i]) and y_pred[i] == y_true[i]) for i in sub)
            s_fpr_raw = (s_fp / len(s_neg)) if s_neg else None
            s_ffr_raw = (s_fn / len(s_pos)) if s_pos else None
            raw_fpr_by_stratum[stratum] = s_fpr_raw
            raw_ffr_by_stratum[stratum] = s_ffr_raw
            per_stratum[stratum] = {
                "n": len(sub),
                "fp": s_fp,
                "n_neg": len(s_neg),
                "fpr": round(s_fpr_raw, 4) if s_fpr_raw is not None else None,
                "fpr_ci95": wilson_ci(s_fp, len(s_neg)),
                "fn": s_fn,
                "n_pos": len(s_pos),
                "ffr": round(s_ffr_raw, 4) if s_ffr_raw is not None else None,
                "ffr_ci95": wilson_ci(s_fn, len(s_pos)),
                "coverage": f"{s_cov}/{len(sub)}",
                "strict_accuracy": f"{s_strict}/{len(sub)}",
            }

        kappa = cohens_kappa(y_true, y_pred)
        # Stratified family x stratum bootstrap CI (fallback to stratum when 1 trial per cell)
        rng = np.random.default_rng(seed)
        buckets: dict[Any, list[int]] = {}
        for i, r in enumerate(records):
            buckets.setdefault((r["stratum"], r["family_id"]), []).append(i)
        if all(len(group) <= 1 for group in buckets.values()):
            buckets = {}
            for i, r in enumerate(records):
                buckets.setdefault(r["stratum"], []).append(i)
        boot_kappas: list[float] = []
        boot_fprs: list[float] = []
        y_t_arr = np.asarray(y_true)
        y_p_arr = np.asarray(y_pred)
        for _ in range(bootstrap_n):
            sampled: list[int] = []
            for group in buckets.values():
                picks = rng.integers(0, len(group), size=len(group))
                sampled.extend(group[p] for p in picks)
            bt = y_t_arr[sampled].tolist()
            bp = y_p_arr[sampled].tolist()
            boot_kappas.append(cohens_kappa(bt, bp))
            b_neg = [g == 0 for g in bt]
            if any(b_neg):
                fp_b = sum(p for g, p in zip(bt, bp) if g == 0)
                boot_fprs.append(fp_b / sum(b_neg))

        # Check pre-committed JUDGE-EXPERIMENT-v0 stop-use thresholds on unrounded raw counts/ratios.
        overall_fpr_raw = (fp / len(neg_idx)) if neg_idx else None
        s4_fpr_raw = raw_fpr_by_stratum.get("S4")
        s2_fpr_raw = raw_fpr_by_stratum.get("S2")
        s1_ffr_raw = raw_ffr_by_stratum.get("S1")
        min_cov = (
            min(
                int(v["coverage"].split("/")[0]) / int(v["coverage"].split("/")[1])
                for v in per_stratum.values()
            )
            if len(per_stratum) == 4
            else None
        )
        triggers: list[str] = []
        if len(per_stratum) < 4:
            missing_strata = [s for s in ("S1", "S2", "S3", "S4") if s not in per_stratum]
            triggers.append(f"incomplete_strata ({','.join(missing_strata)})")
        if s4_fpr_raw is None:
            triggers.append("S4_FPR_UNMEASURED")
        elif s4_fpr_raw >= 0.10:
            triggers.append(f"S4_FPR>=10% ({s4_fpr_raw:.3f})")
        if s2_fpr_raw is None:
            triggers.append("S2_FPR_UNMEASURED")
        elif s2_fpr_raw >= 0.10:
            triggers.append(f"S2_FPR>=10% ({s2_fpr_raw:.3f})")
        if overall_fpr_raw is None:
            triggers.append("overall_FPR_UNMEASURED")
        elif overall_fpr_raw > 0.05:
            triggers.append(f"overall_FPR>5% ({overall_fpr_raw:.3f})")
        if kappa < 0.80 or len(set(y_true)) < 2:
            triggers.append(f"kappa<0.80 ({kappa:.3f})")
        if s1_ffr_raw is None:
            triggers.append("S1_FFR_UNMEASURED")
        elif s1_ffr_raw > 0.10:
            triggers.append(f"S1_FFR>10% ({s1_ffr_raw:.3f})")
        if min_cov is None or min_cov < 0.90:
            triggers.append(f"min_stratum_coverage<90% ({0.0 if min_cov is None else min_cov:.3f})")

        summary["judges"][judge] = {
            "fp": fp,
            "n_neg": len(neg_idx),
            "overall_fpr": round(overall_fpr_raw, 4) if overall_fpr_raw is not None else None,
            "overall_fpr_ci95": wilson_ci(fp, len(neg_idx)),
            "overall_fpr_boot_ci95": [round(float(np.percentile(boot_fprs, 2.5)), 4), round(float(np.percentile(boot_fprs, 97.5)), 4)] if boot_fprs else None,
            "fn": fn,
            "n_pos": len(pos_idx),
            "overall_ffr": round(fn / len(pos_idx), 4) if pos_idx else None,
            "overall_ffr_ci95": wilson_ci(fn, len(pos_idx)),
            "accuracy": round(acc_count / len(records), 4),
            "coverage": f"{cov_count}/{len(records)}",
            "strict_accuracy": f"{strict_count}/{len(records)}",
            "kappa": round(kappa, 4),
            "kappa_boot_ci95": [round(float(np.percentile(boot_kappas, 2.5)), 4), round(float(np.percentile(boot_kappas, 97.5)), 4)],
            "per_stratum": per_stratum,
            "stop_use_triggered": bool(triggers),
            "stop_use_reasons": triggers,
        }

    # Paired McNemar on instrument failures (g == 0) across all judge pairs
    pairwise: dict[str, Any] = {}
    for i, j1 in enumerate(judges):
        for j2 in judges[i + 1:]:
            b_only_1 = sum(
                1 for r in records
                if r["ground_truth"] == 0 and r[j1]["v_binary"] == 1 and r[j2]["v_binary"] == 0
            )
            c_only_2 = sum(
                1 for r in records
                if r["ground_truth"] == 0 and r[j1]["v_binary"] == 0 and r[j2]["v_binary"] == 1
            )
            both_12 = sum(
                1 for r in records
                if r["ground_truth"] == 0 and r[j1]["v_binary"] == 1 and r[j2]["v_binary"] == 1
            )
            pairwise[f"{j1}__vs__{j2}"] = {
                "only_first_fp": b_only_1,
                "only_second_fp": c_only_2,
                "shared_fp": both_12,
                "mcnemar_exact_p": exact_mcnemar_pvalue(b_only_1, c_only_2),
            }
    summary["pairwise_mcnemar"] = pairwise
    if "robodojo_astra" in judges and "datacenterbench_dual" in judges:
        leg = pairwise["robodojo_astra__vs__datacenterbench_dual"]
        summary["paired_failure_comparison"] = {
            "astra_only_fp": leg["only_first_fp"],
            "dual_only_fp": leg["only_second_fp"],
            "shared_fp": leg["shared_fp"],
            "mcnemar_exact_p": leg["mcnemar_exact_p"],
        }
    return summary
