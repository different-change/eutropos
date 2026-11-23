"""Self-contained single-file offline HTML audit viewer (no runtime viewer dependencies) for eutropos-referee evidence bundles."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import __version__
from .certificate import (
    CERTIFICATE_VERSION_V1,
    load_public_key,
    public_key_bytes,
    verify_certificate,
)
from .manifest import bundle_path, read_json, read_jsonl
from .verifier import verify_bundle


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _npy_to_data_uri(npy_path: Path, max_side: int = 240, max_pixels: int = 4096 * 4096) -> str | None:
    try:
        arr = np.load(npy_path, mmap_mode="r", allow_pickle=False)
        if arr.dtype != np.uint8:
            return None
        if arr.ndim == 2:
            h, w = int(arr.shape[0]), int(arr.shape[1])
            c = 1
        elif arr.ndim == 3 and arr.shape[2] in {3, 4}:
            h, w, c = int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2])
        else:
            return None
        if h <= 0 or w <= 0 or (h * w) > max_pixels:
            return None
        stride = max(1, max(h, w) // max_side)
        sub = np.asarray(arr[::stride, ::stride], dtype=np.uint8)
        if sub.ndim == 2:
            sub = np.stack([sub, sub, sub], axis=-1)
        elif c == 4:
            sub = sub[..., :3]
        img = Image.fromarray(sub)
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def _collect_manifest_covered_paths(root: Path, is_v1: bool) -> set[str]:
    covered: set[str] = set()
    manifests_dir = root / "manifests"
    if not manifests_dir.is_dir():
        return covered
    pattern = "trial_*.json" if is_v1 else "*.json"
    for mp in sorted(manifests_dir.glob(pattern)):
        try:
            doc = read_json(mp, canonical=True)
            for entry in doc.get("files", []):
                rel = entry.get("path")
                if isinstance(rel, str):
                    covered.add(rel.replace("\\", "/"))
        except Exception:
            continue
    return covered


def _render_tsa_rows(tsa_rec: dict[str, Any], is_v1: bool) -> str:
    if not is_v1:
        stub = tsa_rec.get("timestamp_stub", tsa_rec)
        if not isinstance(stub, dict):
            return f"<tr><td>Stub Timestamp</td><td><code>{_esc(stub)}</code></td><td>—</td><td>—</td></tr>"
        return (
            "<tr>"
            "<td>Timestamp Stub</td>"
            f"<td><code>{_esc(stub.get('provider', 'local-stub'))}</code></td>"
            f"<td><code>{_esc(stub.get('gen_time_utc', 'n/a'))}</code></td>"
            f"<td><code>{_esc(stub.get('digest_sha256', 'n/a'))}</code></td>"
            "</tr>"
        )
    rows: list[str] = []
    ordered_keys = [("Commitment (Pre-Beacon)", tsa_rec.get("commitment")),
                    ("Post-Beacon Inputs", tsa_rec.get("post_beacon")),
                    ("Session Close Root", tsa_rec.get("session_close"))]
    for idx, chk in enumerate(tsa_rec.get("checkpoints", [])):
        ordered_keys.append((f"Checkpoint #{idx}", chk))
    for stage, blk in ordered_keys:
        if not isinstance(blk, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(stage)}</td>"
            f"<td><code>{_esc(blk.get('provider', 'n/a'))}</code></td>"
            f"<td><code>{_esc(blk.get('gen_time_utc', 'n/a'))}</code></td>"
            f"<td><code>{_esc(blk.get('tsr_sha256', blk.get('digest_sha256', 'n/a')))}</code></td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="4">No TSA receipt records present</td></tr>'


def render_audit_html(
    evidence_dir: str | Path,
    *,
    public_key: str | Path | None = None,
    allow_bundled_key: bool = False,
    trusted_tsa_pem: str | Path | None = None,
    escrow_dir: str | Path | None = None,
    require_live_beacon: bool = False,
    require_live_tsa: bool = False,
) -> str:
    """Authenticate an evidence bundle and render a self-contained CSP-hardened audit HTML page."""
    root = Path(evidence_dir).absolute()
    report = verify_bundle(
        root,
        public_key=public_key,
        allow_bundled_key=allow_bundled_key,
        trusted_tsa_pem=trusted_tsa_pem,
        escrow_dir=escrow_dir,
        require_live_beacon=require_live_beacon,
        require_live_tsa=require_live_tsa,
    )
    key_path = Path(public_key) if public_key is not None else root / "public_key.pem"
    key_kid = "unavailable"
    key_fp = "unavailable"
    cert_env: dict[str, Any] = {}
    auth_cert: dict[str, Any] = {}
    unauth_cert: dict[str, Any] = {}
    cert_authenticated = False
    try:
        key = load_public_key(key_path)
        key_fp = hashlib.sha256(public_key_bytes(key)).hexdigest()
        key_kid = key_fp[:16]
        cert_env = read_json(root / "certificate.json", canonical=True)
        auth_cert = verify_certificate(cert_env, key)
        cert_authenticated = True
    except Exception:
        try:
            if not cert_env and (root / "certificate.json").is_file():
                cert_env = json.loads((root / "certificate.json").read_text(encoding="utf-8"))
            raw_p = cert_env.get("payload", "")
            if isinstance(raw_p, str) and raw_p:
                pad = "=" * (-len(raw_p) % 4)
                unauth_cert = json.loads(base64.urlsafe_b64decode(raw_p + pad).decode("utf-8"))
        except Exception:
            unauth_cert = {}

    check_outcomes = {c.name: bool(c.passed) for c in report.checks}
    live_beacon_verified = bool(
        check_outcomes.get("drand_beacon") and check_outcomes.get("drand_pinned_network")
    )
    live_tsa_verified = bool(
        check_outcomes.get("tsa_commitment")
        and check_outcomes.get("tsa_post_beacon")
        and check_outcomes.get("tsa_session_close")
    )

    generated_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ver = (auth_cert if cert_authenticated else unauth_cert).get("certificate_version", "unknown")
    is_v1 = ver == CERTIFICATE_VERSION_V1

    badge_cls = "badge-pass" if report.passed else "badge-fail"
    if not report.passed:
        badge_txt = f"VERIFICATION FAILED ({len(report.failures)})"
        scope_sub = "Bundle authentication failed; scores below are withheld from authenticated certification tables."
    elif is_v1 and live_beacon_verified and live_tsa_verified:
        badge_txt = "VERIFIED PASS (LIVE CRYPTO)"
        scope_sub = "Bundle Integrity Verified · Live drand-quicknet BLS12-381 & RFC 3161 TSA checks passed."
    else:
        badge_txt = "VERIFIED PASS (LOCAL STUB DEMO)"
        scope_sub = "Bundle Integrity Verified · Local stub randomness and timestamp mode."

    passed_count = sum(1 for c in report.checks if c.passed)
    checks_rows_html = "".join(
        "<tr>"
        f"<td><code>{_esc(c.name)}</code></td>"
        f"<td><span class=\"{'badge-pass' if c.passed else 'badge-fail'}\">{'PASS' if c.passed else 'FAIL'}</span></td>"
        f"<td><code>{_esc(c.detail)}</code></td>"
        "</tr>"
        for c in report.checks
    )

    failures_html = (
        "<ul class=\"fail-list\">" + "".join(f"<li><code>{_esc(f)}</code></li>" for f in report.failures) + "</ul>"
        if report.failures
        else '<p class="muted">Zero verification failures recorded.</p>'
    )

    if cert_authenticated and report.passed:
        subj = auth_cert.get("subject", {})
        seed = auth_cert.get("seed", {})
        beacon = seed.get("beacon", {})
        ev = auth_cert.get("evidence", {})
        tsa_rec = ev.get("tsa_receipts", {}) if is_v1 else {"timestamp_stub": ev.get("timestamp_stub", {})}

        deviations = []
        if is_v1 and (root / "pre_beacon_registration.json").is_file():
            try:
                pre_doc = read_json(root / "pre_beacon_registration.json", canonical=True)
                deviations = pre_doc.get("deviations_and_incidents", [])
            except Exception:
                deviations = []
        sim_note_html = ""
        if any("simulat" in str(d).lower() for d in deviations) or subj.get("name") == "v1-compliant-bench":
            sim_note_html = '<div class="notice-banner"><strong>Evidence Provenance Notice:</strong> Pre-registration declares simulated/synthetic bench instruments for protocol verification; physical hardware data awaits bench assembly.</div>'

        # Build slot ledger safely
        ledger_rows_html = ""
        if is_v1 and (root / "manifests" / "slot_ledger.jsonl").is_file():
            try:
                for row in read_jsonl(root / "manifests" / "slot_ledger.jsonl"):
                    ledger_rows_html += (
                        "<tr>"
                        f"<td>{_esc(row.get('seq'))}</td>"
                        f"<td><code>{_esc(row.get('slot_id'))}</code></td>"
                        f"<td><code>{_esc(row.get('execution_attempt_id'))}</code></td>"
                        f"<td>{_esc(row.get('status'))}</td>"
                        f"<td><code>{_esc(row.get('retry_of_attempt_id') or '-')}</code></td>"
                        f"<td>{_esc(row.get('trial_passed'))}</td>"
                        f"<td>{_esc(row.get('reason'))}</td>"
                        "</tr>"
                    )
            except Exception:
                ledger_rows_html = '<tr><td colspan="7">Slot ledger unreadable</td></tr>'

        fam_rows_html = ""
        per_fam = auth_cert.get("results", {}).get("per_family", {})
        fam_items = (
            sorted(per_fam.items())
            if isinstance(per_fam, dict)
            else [(str(item.get("family_id", item.get("family", i))), item) for i, item in enumerate(per_fam)]
        )
        for fam, vals in fam_items:
            passed_cnt = vals.get("passed", vals.get("successes", "-"))
            reg_cnt = vals.get("registered", vals.get("trials", "-"))
            ci_val = vals.get("ci95", vals.get("wilson_95", "-"))
            fam_rows_html += (
                "<tr>"
                f"<td><code>{_esc(fam)}</code></td>"
                f"<td>{_esc(passed_cnt)} / {_esc(reg_cnt)}</td>"
                f"<td>{_esc(vals.get('pass_rate', '-'))}</td>"
                f"<td>{_esc(ci_val)}</td>"
                "</tr>"
            )

        adj_rows_html = ""
        for adj in auth_cert.get("adjudications", []):
            adj_rows_html += (
                "<tr>"
                f"<td><code>{_esc(adj.get('execution_attempt_id'))}</code></td>"
                f"<td><code>{_esc(adj.get('original_scores'))}</code></td>"
                f"<td><code>{_esc(adj.get('adjudicated_scores'))}</code></td>"
                f"<td>{_esc(adj.get('reason'))}</td>"
                f"<td><code>{_esc(adj.get('adjudicator_id'))}</code></td>"
                "</tr>"
            )

        # Collect up to 6 sanitized frame thumbnails strictly from manifest-covered paths under frames/
        thumbs_html = ""
        covered_paths = _collect_manifest_covered_paths(root, is_v1=is_v1)
        frame_rels = sorted(
            p for p in covered_paths if p.startswith("frames/") and p.endswith(".npy")
        )[:6]
        for rel in frame_rels:
            try:
                npy_path = bundle_path(root, rel)
            except Exception:
                continue
            if npy_path.is_file():
                uri = _npy_to_data_uri(npy_path)
                if uri:
                    thumbs_html += (
                        '<figure class="thumb">'
                        f'<img src="{uri}" alt="{_esc(rel)}"/>'
                        f'<figcaption><code>{_esc(rel)}</code></figcaption>'
                        "</figure>"
                    )

        main_sections_html = f"""
{sim_note_html}
<h2>Subject &amp; Physical Architecture</h2>
<div class="table-wrap">
<table>
  <tr><th>Certificate Version</th><td><code>{_esc(ver)}</code></td></tr>
  <tr><th>Subject / Snapshot</th><td><code>{_esc(subj.get('name'))}</code> / <code>{_esc(subj.get('snapshot'))}</code></td></tr>
  <tr><th>Pareto Profile &amp; Division</th><td><code>{_esc(auth_cert.get('pareto_profile', 'n/a'))}</code> &middot; <code>{_esc(subj.get('division'))}</code> &middot; <code>mask_tactile={_esc(auth_cert.get('mask_tactile', 'n/a'))}</code></td></tr>
  <tr><th>Disclosure Mode</th><td><code>{_esc(auth_cert.get('disclosure_mode', 'v0.2-open'))}</code></td></tr>
</table>
</div>

<h2>Cryptographic Provenance</h2>
<div class="table-wrap">
<table>
  <tr><th>Commitment C</th><td><code>{_esc(seed.get('commitment_C'))}</code></td></tr>
  <tr><th>Randomness Beacon</th><td><code>{_esc(beacon.get('provider'))}</code> &middot; round <code>{_esc(beacon.get('round_number'))}</code> &middot; scheme <code>{_esc(beacon.get('scheme', 'stub'))}</code> &middot; CLI BLS check passed=<code>{_esc(live_beacon_verified)}</code></td></tr>
  <tr><th>Genesis / Chain Root</th><td><code>{_esc(ev.get('genesis_hash'))}</code><br/><code>{_esc(ev.get('chain_root_hash'))}</code></td></tr>
</table>
</div>

<h2>RFC 3161 TSA Receipts</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Stage</th><th>Provider</th><th>UTC Timestamp</th><th>Receipt / Digest SHA-256</th></tr></thead>
  <tbody>{_render_tsa_rows(tsa_rec, is_v1)}</tbody>
</table>
</div>

<h2>Per-Family Scores &amp; Wilson 95% CIs</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Family</th><th>Passed / Registered</th><th>Pass Rate</th><th>Wilson 95% CI</th></tr></thead>
  <tbody>{fam_rows_html or '<tr><td colspan="4">See certificate overall summary</td></tr>'}</tbody>
</table>
</div>

<h2>Slot Ledger</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Seq</th><th>Slot ID</th><th>Attempt ID</th><th>Status</th><th>Retry Of</th><th>Passed</th><th>Reason</th></tr></thead>
  <tbody>{ledger_rows_html or '<tr><td colspan="7">Applicable to v1.0 bundles</td></tr>'}</tbody>
</table>
</div>

<h2>Adjudications (Raw Scores Preserved)</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Attempt ID</th><th>Original Scores</th><th>Adjudicated Scores</th><th>Reason</th><th>Adjudicator</th></tr></thead>
  <tbody>{adj_rows_html or '<tr><td colspan="5">None recorded</td></tr>'}</tbody>
</table>
</div>

<h2>Manifest-Verified Frame Thumbnails</h2>
<div class="thumbs">{thumbs_html or '<p class="muted">Zero manifest-covered .npy frame thumbnails present in this bundle.</p>'}</div>
"""
    else:
        preview_subj = unauth_cert.get("subject", {}) if isinstance(unauth_cert, dict) else {}
        main_sections_html = f"""
<div class="unauth-panel">
  <h2>UNAUTHENTICATED DIAGNOSTIC PREVIEW (SIGNATURE OR INTEGRITY FAILED)</h2>
  <p>Authenticated certificate subject, slot scores, adjudications, and frame thumbnails are suppressed because bundle verification failed or certificate signature validation raised an error.</p>
  <div class="table-wrap">
  <table>
    <tr><th>Unverified Claimed Version</th><td><code>{_esc(ver)}</code></td></tr>
    <tr><th>Unverified Claimed Subject</th><td><code>{_esc(preview_subj.get('name', 'unavailable'))}</code></td></tr>
    <tr><th>Unverified Disclosure Mode</th><td><code>{_esc(unauth_cert.get('disclosure_mode', 'unavailable') if isinstance(unauth_cert, dict) else 'unavailable')}</code></td></tr>
  </table>
  </div>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline';"/>
<title>Eutropos Referee Audit Report</title>
<style>
  :root {{
    --stone: #F5F2EB;
    --stone-deep: #EAE5D9;
    --surface: #FAF8F4;
    --line: #DCD5C7;
    --ink: #14171D;
    --muted: #5A606A;
    --aegean: #14233C;
    --bronze: #795B2B;
    --pass: #1F5E4B;
    --fail: #9C2F1E;
    --obsidian: #07090D;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: Georgia, "Times New Roman", serif; margin: 0 auto; padding: 36px 28px 64px; max-width: 1120px; color: var(--ink); background: var(--stone); line-height: 1.55; }}
  h1 {{ font-weight: 400; font-size: 36px; line-height: 1.1; margin: 8px 0 12px; color: var(--ink); }}
  h2 {{ font-weight: 400; font-size: 22px; border-bottom: 1px solid var(--line); padding-bottom: 8px; margin: 36px 0 14px; color: var(--aegean); }}
  .eyebrow {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--bronze); margin: 0; }}
  .hero-panel {{ background: var(--obsidian); color: var(--stone); padding: 28px 32px; border: 1px solid #2A251B; margin-bottom: 24px; }}
  .hero-panel h1 {{ color: #FFFFFF; margin-top: 10px; }}
  .hero-meta {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #C9CFD6; margin: 8px 0 0; word-break: break-word; }}
  .badge-pass {{ display: inline-block; background: var(--pass); color: #FFFFFF; padding: 4px 10px; font-family: ui-monospace, monospace; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }}
  .badge-fail {{ display: inline-block; background: var(--fail); color: #FFFFFF; padding: 4px 10px; font-family: ui-monospace, monospace; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }}
  .notice-banner {{ border-left: 3px solid var(--bronze); background: var(--stone-deep); padding: 14px 18px; margin: 18px 0; font-family: system-ui, -apple-system, sans-serif; font-size: 14px; }}
  .unauth-panel {{ border: 2px solid var(--fail); background: #FFF5F4; padding: 20px 24px; margin: 24px 0; }}
  .unauth-panel h2 {{ color: var(--fail); border-bottom-color: rgba(156, 47, 30, 0.25); margin-top: 0; }}
  .fail-list {{ border-left: 3px solid var(--fail); background: #FFF5F4; padding: 14px 24px; margin: 12px 0; list-style: disc; }}
  .table-wrap {{ width: 100%; overflow-x: auto; background: var(--surface); border: 1px solid var(--line); }}
  table {{ border-collapse: collapse; width: 100%; font-family: system-ui, -apple-system, sans-serif; font-size: 13.5px; }}
  th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }}
  th {{ background: var(--stone-deep); font-family: ui-monospace, monospace; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink); }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; word-break: break-all; background: transparent; color: inherit; }}
  .muted {{ color: var(--muted); font-family: system-ui, sans-serif; font-size: 14px; }}
  .thumbs {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }}
  figure.thumb {{ margin: 0; border: 1px solid var(--line); padding: 12px; background: #FFFFFF; }}
  figure.thumb img {{ max-width: 100%; height: auto; display: block; margin-bottom: 8px; }}
  @media (max-width: 720px) {{
    body {{ padding: 20px 16px 40px; }}
    .hero-panel {{ padding: 20px 18px; }}
    h1 {{ font-size: 28px; }}
  }}
  @media print {{
    body {{ background: #FFFFFF; padding: 0; max-width: none; }}
    .hero-panel {{ background: var(--obsidian); -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
<div class="hero-panel">
  <p class="eyebrow">Eutropos Referee &middot; Self-Contained Offline Audit Report</p>
  <h1>Cryptographic Custody Audit</h1>
  <p><span class="{badge_cls}">{_esc(badge_txt)}</span> &nbsp; <span class="hero-meta">{_esc(scope_sub)}</span></p>
  <p class="hero-meta">Generated UTC: <code>{_esc(generated_utc)}</code> &middot; Tool: <code>eutropos-referee=={_esc(__version__)}</code> &middot; Checks Passed: <code>{passed_count} / {len(report.checks)}</code></p>
  <p class="hero-meta">Trust Key Mode: <code>{_esc(report.trusted_key_mode)}</code> &middot; Key ID: <code>{_esc(key_kid)}</code> &middot; Ed25519 SHA-256: <code>{_esc(key_fp)}</code></p>
</div>

<h2>Failures &amp; Anomalies</h2>
{failures_html}

<h2>Executed Referee Checks ({passed_count} / {len(report.checks)})</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Check</th><th>Outcome</th><th>Detail</th></tr></thead>
  <tbody>{checks_rows_html}</tbody>
</table>
</div>

{main_sections_html}
</body>
</html>
"""
