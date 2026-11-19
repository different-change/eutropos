"""Zero-dependency single-file offline HTML audit viewer for habilis-referee evidence bundles."""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .certificate import CERTIFICATE_VERSION_V1, load_public_key, verify_certificate
from .manifest import bundle_path, read_json, read_jsonl
from .verifier import verify_bundle


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _npy_to_data_uri(npy_path: Path, max_side: int = 240, max_pixels: int = 4096 * 4096) -> str | None:
    try:
        arr = np.load(npy_path, mmap_mode="r", allow_pickle=False)
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
        img = Image.fromarray(sub, mode="RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


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
    cert_env: dict[str, Any] = {}
    cert: dict[str, Any] = {}
    try:
        cert_env = read_json(root / "certificate.json", canonical=True)
        key = load_public_key(key_path)
        cert = verify_certificate(cert_env, key)
    except Exception:
        try:
            raw_p = cert_env.get("payload", "")
            if isinstance(raw_p, str) and raw_p:
                import json

                pad = "=" * (-len(raw_p) % 4)
                cert = json.loads(base64.urlsafe_b64decode(raw_p + pad).decode("utf-8"))
        except Exception:
            cert = {}

    ver = cert.get("certificate_version", "unknown")
    is_v1 = ver == CERTIFICATE_VERSION_V1
    subj = cert.get("subject", {})
    seed = cert.get("seed", {})
    beacon = seed.get("beacon", {})
    ev = cert.get("evidence", {})
    tsa = ev.get("tsa_receipts", {}) if is_v1 else {"timestamp_stub": ev.get("timestamp_stub", {})}

    badge_cls = "badge-pass" if report.passed else "badge-fail"
    if not report.passed:
        badge_txt = f"VERIFICATION FAILED ({len(report.failures)})"
    elif (
        is_v1
        and beacon.get("scheme") == "drand-quicknet"
        and tsa.get("commitment", {}).get("provider") == "rfc3161"
        and tsa.get("session_close", {}).get("provider") == "rfc3161"
    ):
        badge_txt = "VERIFIED PASS (LIVE CRYPTO)"
    else:
        badge_txt = "VERIFIED PASS (LOCAL STUB DEMO)"

    # Build slot ledger rows if v1
    ledger_rows_html = ""
    if is_v1 and (root / "manifests" / "slot_ledger.jsonl").is_file():
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

    # Family summary rows (handles dict in v1.0 and list in v0.2)
    fam_rows_html = ""
    per_fam = cert.get("results", {}).get("per_family", {})
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

    # Adjudication rows
    adj_rows_html = ""
    for adj in cert.get("adjudications", []):
        adj_rows_html += (
            "<tr>"
            f"<td><code>{_esc(adj.get('execution_attempt_id'))}</code></td>"
            f"<td><code>{_esc(adj.get('original_scores'))}</code></td>"
            f"<td><code>{_esc(adj.get('adjudicated_scores'))}</code></td>"
            f"<td>{_esc(adj.get('reason'))}</td>"
            f"<td><code>{_esc(adj.get('adjudicator_id'))}</code></td>"
            "</tr>"
        )

    # Collect up to 6 sanitized frame thumbnails strictly under frames/ on verified bundles
    thumbs_html = ""
    frames_dir = root / "frames"
    if report.passed and frames_dir.is_dir():
        npys = sorted(frames_dir.rglob("*.npy"))[:6]
        for npy in npys:
            rel = npy.relative_to(root).as_posix()
            bundle_path(root, rel)
            uri = _npy_to_data_uri(npy)
            if uri:
                thumbs_html += (
                    '<figure class="thumb">'
                    f'<img src="{uri}" alt="{_esc(rel)}"/>'
                    f'<figcaption><code>{_esc(rel)}</code></figcaption>'
                    "</figure>"
                )

    failures_html = (
        "<ul>" + "".join(f"<li><code>{_esc(f)}</code></li>" for f in report.failures) + "</ul>"
        if report.failures
        else "<p>Zero verification failures recorded.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline';"/>
<title>Habilis Referee Audit Report</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2rem auto; max-width: 1040px; color: #1f2328; background: #fafbfc; line-height: 1.45; }}
  h1, h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 0.3rem; }}
  .badge-pass {{ display: inline-block; background: #1a7f37; color: #fff; padding: 0.3rem 0.75rem; border-radius: 6px; font-weight: 600; }}
  .badge-fail {{ display: inline-block; background: #cf222e; color: #fff; padding: 0.3rem 0.75rem; border-radius: 6px; font-weight: 600; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; background: #fff; }}
  th, td {{ border: 1px solid #d0d7de; padding: 0.45rem 0.65rem; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f6f8fa; }}
  code {{ background: #f0f2f4; padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.85em; word-break: break-all; }}
  .thumbs {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
  figure.thumb {{ margin: 0; border: 1px solid #d0d7de; padding: 0.4rem; background: #fff; max-width: 256px; }}
  figure.thumb img {{ max-width: 100%; height: auto; display: block; }}
</style>
</head>
<body>
<h1>Habilis Certified Referee Audit Report</h1>
<p><span class="{badge_cls}">{_esc(badge_txt)}</span> &nbsp; Checks evaluated: <strong>{len(report.checks)}</strong> &nbsp;|&nbsp; Key mode: <code>{_esc(report.trusted_key_mode)}</code></p>

<h2>Subject &amp; Architecture</h2>
<table>
  <tr><th>Certificate Version</th><td><code>{_esc(ver)}</code></td></tr>
  <tr><th>Subject / Snapshot</th><td><code>{_esc(subj.get('name'))}</code> / <code>{_esc(subj.get('snapshot'))}</code></td></tr>
  <tr><th>Pareto Profile &amp; Division</th><td><code>{_esc(cert.get('pareto_profile', 'n/a'))}</code> &middot; <code>{_esc(subj.get('division'))}</code> &middot; <code>mask_tactile={_esc(cert.get('mask_tactile', 'n/a'))}</code></td></tr>
  <tr><th>Disclosure Mode</th><td><code>{_esc(cert.get('disclosure_mode', 'v0.2-open'))}</code></td></tr>
</table>

<h2>Cryptographic Provenance</h2>
<table>
  <tr><th>Commitment C</th><td><code>{_esc(seed.get('commitment_C'))}</code></td></tr>
  <tr><th>Randomness Beacon</th><td><code>{_esc(beacon.get('provider'))}</code> &middot; round <code>{_esc(beacon.get('round_number'))}</code> &middot; <code>{_esc(beacon.get('scheme', 'stub'))}</code> &middot; verified=<code>{_esc(beacon.get('cryptographically_verified', False))}</code></td></tr>
  <tr><th>Genesis / Chain Root</th><td><code>{_esc(ev.get('genesis_hash'))}</code><br/><code>{_esc(ev.get('chain_root_hash'))}</code></td></tr>
  <tr><th>RFC 3161 TSA Receipts</th><td><code>{_esc(tsa)}</code></td></tr>
</table>

<h2>Failures &amp; Anomalies</h2>
{failures_html}

<h2>Per-Family Scores &amp; Wilson 95% CIs</h2>
<table>
  <tr><th>Family</th><th>Passed / Registered</th><th>Pass Rate</th><th>Wilson 95% CI</th></tr>
  {fam_rows_html or '<tr><td colspan="4">See certificate overall summary</td></tr>'}
</table>

<h2>Slot Ledger</h2>
<table>
  <tr><th>Seq</th><th>Slot ID</th><th>Attempt ID</th><th>Status</th><th>Retry Of</th><th>Passed</th><th>Reason</th></tr>
  {ledger_rows_html or '<tr><td colspan="7">Not applicable for v0.2 bundle</td></tr>'}
</table>

<h2>Adjudications (Raw Scores Preserved)</h2>
<table>
  <tr><th>Attempt ID</th><th>Original Scores</th><th>Adjudicated Scores</th><th>Reason</th><th>Adjudicator</th></tr>
  {adj_rows_html or '<tr><td colspan="5">None recorded</td></tr>'}
</table>

<h2>Evidence Frame Thumbnails</h2>
<div class="thumbs">{thumbs_html or '<p>No inline .npy image frames present in this bundle.</p>'}</div>
</body>
</html>
"""
