"""Self-contained single-file offline HTML audit viewer (no runtime viewer dependencies) for eutropos-referee evidence bundles."""

from __future__ import annotations

import base64
import functools
import hashlib
import html
import importlib.resources
import io
import json
import os
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
)
from .verifier import verify_bundle

PINNED_DEMO_KEYS: dict[str, str] = {
    "1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744": "Eutropos Demo Signer (Open Track · Software Demo)",
    "1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd": "Eutropos Demo Signer (Escrowed Track · Software Demo)",
}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if value is None:
        return "—"
    return str(value)


def _fmt_rate(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value * 100:.1f}%"
    if value is None or value == "-":
        return "—"
    return str(value)


def _fmt_ci(value: Any) -> str:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)
    ):
        return f"[{value[0]:.3f}, {value[1]:.3f}]"
    if value is None or value == "-":
        return "—"
    return str(value)


def _fmt_scores(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
    if value is None:
        return "—"
    return str(value)


def _npy_bytes_to_data_uri(raw_bytes: bytes, max_side: int = 240, max_pixels: int = 4096 * 4096) -> str | None:
    try:
        arr = np.load(io.BytesIO(raw_bytes), allow_pickle=False)
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


def _read_font_bytes(filename: str) -> bytes | None:
    try:
        res = importlib.resources.files("eutropos_referee").joinpath("assets", "fonts", filename)
        if res.is_file():
            return res.read_bytes()
    except Exception:
        pass
    fallback = Path(__file__).resolve().parent / "assets" / "fonts" / filename
    if fallback.is_file():
        return fallback.read_bytes()
    return None


@functools.lru_cache(maxsize=1)
def _build_embedded_font_css() -> str:
    specs = (
        ("EB Garamond", "normal", 400, "eb-garamond-latin-400-normal.woff2"),
        ("EB Garamond", "italic", 400, "eb-garamond-latin-400-italic.woff2"),
        ("JetBrains Mono", "normal", 400, "jetbrains-mono-latin-400-normal.woff2"),
    )
    rules: list[str] = []
    for family, style, weight, fname in specs:
        raw = _read_font_bytes(fname)
        if not raw:
            continue
        b64 = base64.b64encode(raw).decode("ascii")
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-style: {style}; font-weight: {weight}; '
            f'font-display: swap; src: url("data:font/woff2;base64,{b64}") format("woff2"); }}'
        )
    return "\n  ".join(rules)


def _render_tsa_rows(tsa_rec: Any, is_v1: bool) -> str:
    if not isinstance(tsa_rec, dict):
        return '<tr><td colspan="4">TSA receipt records: absent</td></tr>'
    if not is_v1:
        stub = tsa_rec.get("timestamp_stub", tsa_rec)
        if not isinstance(stub, dict):
            return f"<tr><td>Timestamp Stub</td><td><code>{_esc(stub)}</code></td><td>—</td><td>—</td></tr>"
        return (
            "<tr>"
            "<td>Timestamp Stub</td>"
            f"<td><code>{_esc(stub.get('provider', 'local-stub'))}</code></td>"
            f"<td><code>{_esc(stub.get('gen_time_utc', 'n/a'))}</code></td>"
            f"<td><code>{_esc(stub.get('digest_sha256', 'n/a'))}</code></td>"
            "</tr>"
        )
    rows: list[str] = []
    ordered_keys: list[tuple[str, Any]] = [
        ("Commitment (Pre-Beacon)", tsa_rec.get("commitment")),
        ("Post-Beacon Inputs", tsa_rec.get("post_beacon")),
        ("Session Close Root", tsa_rec.get("session_close")),
    ]
    raw_checkpoints = tsa_rec.get("checkpoints")
    if isinstance(raw_checkpoints, list):
        for idx, chk in enumerate(raw_checkpoints):
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
    return "".join(rows) or '<tr><td colspan="4">TSA receipt records: absent</td></tr>'


_BASE_REPORT_CSS = """
  :root {
    --stone: #F5F2EB;
    --stone-deep: #EAE5D9;
    --surface: #FAF8F4;
    --line: #DCD5C7;
    --ink: #14171D;
    --muted: #5A606A;
    --aegean: #14233C;
    --bronze: #795B2B;
    --champagne: #C8AA74;
    --pass: #1F5E4B;
    --warn: #8A5A00;
    --fail: #9C2F1E;
    --obsidian: #07090D;
    --display: "EB Garamond", Georgia, "Times New Roman", serif;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { font-family: var(--display); margin: 0 auto; padding: 28px 28px 64px; max-width: 1120px; color: var(--ink); background: var(--stone); line-height: 1.55; }
  .masthead { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 12px; padding-bottom: 14px; margin-bottom: 20px; border-bottom: 1px solid var(--line); }
  .brand-lockup { font-family: var(--mono); font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink); }
  .brand-greek { font-family: var(--display); font-style: italic; font-size: 16px; letter-spacing: 0.04em; text-transform: none; color: var(--muted); margin-left: 8px; }
  .masthead-sub { font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--bronze); }
  h1 { font-weight: 400; font-size: 36px; line-height: 1.1; margin: 8px 0 12px; color: var(--ink); }
  h2 { font-weight: 400; font-size: 22px; border-bottom: 1px solid var(--line); padding-bottom: 8px; margin: 36px 0 14px; color: var(--aegean); }
  .eyebrow { font-family: var(--mono); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--bronze); margin: 0; }
  .hero-panel { background: var(--obsidian); color: var(--stone); padding: 28px 32px; border: 1px solid #2A251B; margin-bottom: 24px; }
  .hero-panel .eyebrow { color: var(--champagne); }
  .hero-panel h1 { color: #FFFFFF; margin-top: 10px; }
  .hero-meta { font-family: var(--mono); font-size: 12px; color: #C9CFD6; margin: 8px 0 0; word-break: break-word; }
  .hero-panel .notice-banner { border-left: 3px solid var(--champagne); background: rgba(200, 170, 116, 0.12); color: #F5F2EB; padding: 12px 16px; margin: 14px 0 0; font-family: var(--sans); font-size: 13.5px; }
  .badge-pass { display: inline-block; background: var(--pass); color: #FFFFFF; padding: 4px 10px; font-family: var(--mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }
  .badge-warn { display: inline-block; background: var(--warn); color: #FFFFFF; padding: 4px 10px; font-family: var(--mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }
  .badge-fail { display: inline-block; background: var(--fail); color: #FFFFFF; padding: 4px 10px; font-family: var(--mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }
  .notice-banner { border-left: 3px solid var(--bronze); background: var(--stone-deep); padding: 14px 18px; margin: 18px 0; font-family: var(--sans); font-size: 14px; }
  .unauth-panel { border: 2px solid var(--fail); background: #FFF5F4; padding: 20px 24px; margin: 24px 0; }
  .unauth-panel h2 { color: var(--fail); border-bottom-color: rgba(156, 47, 30, 0.25); margin-top: 0; }
  .fail-list { border-left: 3px solid var(--fail); background: #FFF5F4; padding: 14px 24px; margin: 12px 0; list-style: disc; }
  .table-wrap { width: 100%; overflow-x: auto; background: var(--surface); border: 1px solid var(--line); }
  .table-wrap:focus-visible { outline: 2px solid var(--aegean); outline-offset: 2px; }
  table { border-collapse: collapse; width: 100%; font-family: var(--sans); font-size: 13.5px; }
  th, td { border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }
  th { background: var(--stone-deep); font-family: var(--mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink); }
  code { font-family: var(--mono); font-size: 12px; word-break: break-all; background: transparent; color: inherit; }
  .muted { color: var(--muted); font-family: var(--sans); font-size: 14px; }
  .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  figure.thumb { margin: 0; border: 1px solid var(--line); padding: 12px; background: #FFFFFF; }
  figure.thumb img { max-width: 100%; height: auto; display: block; margin-bottom: 8px; }
  .report-footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line); font-family: var(--mono); font-size: 11px; color: var(--muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
  @media (max-width: 720px) {
    body { padding: 20px 16px 40px; }
    .hero-panel { padding: 20px 18px; }
    h1 { font-size: 28px; }
  }
  @media print {
    body { background: #FFFFFF; padding: 0; max-width: none; }
    .hero-panel { background: var(--obsidian); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
"""


def _generated_utc_str() -> str:
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is not None and raw_epoch.strip():
        try:
            dt = datetime.fromtimestamp(int(float(raw_epoch.strip())), tz=timezone.utc)
            return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (ValueError, OSError, OverflowError):
            pass
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    """Authenticate an evidence bundle once and render a self-contained CSP-hardened audit HTML page from the verified snapshot."""
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

    snap = getattr(report, "_verified_snapshot", None)
    key_info = getattr(report, "_verified_key_info", None)
    key_kid = "unavailable"
    key_fp = "unavailable"
    auth_cert: dict[str, Any] = {}
    pre_doc: dict[str, Any] = {}
    ledger_rows: list[Any] = []
    verified_frame_bytes: dict[str, bytes] = {}
    unauth_cert: dict[str, Any] = {}
    cert_authenticated = False

    if report.passed and isinstance(snap, dict) and isinstance(snap.get("auth_cert"), dict):
        cert_authenticated = True
        key_fp = str(snap.get("key_fp") or "unavailable")
        key_kid = str(snap.get("key_kid") or "unavailable")
        auth_cert = snap["auth_cert"]
        if isinstance(snap.get("pre_doc"), dict):
            pre_doc = snap["pre_doc"]
        if isinstance(snap.get("ledger_rows"), list):
            ledger_rows = snap["ledger_rows"]
        if isinstance(snap.get("verified_frame_bytes"), dict):
            verified_frame_bytes = snap["verified_frame_bytes"]
    else:
        if isinstance(key_info, dict):
            key_fp = str(key_info.get("key_fp") or "unavailable")
            key_kid = str(key_info.get("key_kid") or "unavailable")
        else:
            key_path = Path(public_key) if public_key is not None else root / "public_key.pem"
            try:
                key = load_public_key(key_path)
                key_fp = hashlib.sha256(public_key_bytes(key)).hexdigest()
                key_kid = key_fp[:16]
            except Exception:
                pass
        try:
            cert_file = root / "certificate.json"
            if cert_file.is_file():
                parsed_env = json.loads(cert_file.read_text(encoding="utf-8"))
                if isinstance(parsed_env, dict):
                    raw_p = parsed_env.get("payload", "")
                    if isinstance(raw_p, str) and raw_p:
                        pad = "=" * (-len(raw_p) % 4)
                        decoded_payload = json.loads(base64.urlsafe_b64decode(raw_p + pad).decode("utf-8"))
                        if isinstance(decoded_payload, dict):
                            unauth_cert = decoded_payload
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

    generated_utc = _generated_utc_str()
    active_cert = auth_cert if cert_authenticated else unauth_cert
    ver = active_cert.get("certificate_version", "unknown") if isinstance(active_cert, dict) else "unknown"
    is_v1 = ver == CERTIFICATE_VERSION_V1

    is_self_asserted = report.trusted_key_mode == "self-asserted-bundled-key"
    if not is_self_asserted and key_fp in PINNED_DEMO_KEYS:
        signer_trust_label = PINNED_DEMO_KEYS[key_fp]
    elif not is_self_asserted:
        signer_trust_label = f"External Auditor Key (kid={key_kid})"
    else:
        signer_trust_label = "Bundled Key Only (Self-Asserted · Issuer Unverified)"

    badge_cls = "badge-pass" if report.passed else "badge-fail"
    if not report.passed or not cert_authenticated:
        badge_cls = "badge-fail"
        badge_txt = f"VERIFICATION FAILED ({len(report.failures)})"
        anchor_summary = "Anchor validation incomplete or failed"
        scope_sub = "Bundle authentication failed; authenticated tables and frame thumbnails are omitted."
    elif is_self_asserted:
        badge_cls = "badge-warn"
        badge_txt = "SELF-CONSISTENT (BUNDLED KEY · SIGNER UNVERIFIED)"
        anchor_summary = (
            "Live drand-quicknet BLS12-381 & RFC 3161 TSA (bound to self-asserted key)"
            if (is_v1 and live_beacon_verified and live_tsa_verified)
            else "Local / stub anchors (self-asserted bundled key)"
        )
        scope_sub = "Internal hashes and signatures match the bundled public key; supply an independent --public-key to verify issuer identity."
    elif is_v1 and live_beacon_verified and live_tsa_verified:
        badge_txt = "VERIFIED PASS (LIVE CRYPTO)"
        anchor_summary = "Live drand-quicknet BLS12-381 & RFC 3161 TSA"
        scope_sub = "Bundle integrity verified with live drand-quicknet BLS12-381 and RFC 3161 TSA anchors."
    elif is_v1 and (live_beacon_verified or live_tsa_verified):
        badge_txt = "VERIFIED PASS (PARTIAL LIVE ANCHOR)"
        beacon_lbl = "drand: live BLS" if live_beacon_verified else ("drand: stub" if check_outcomes.get("drand_beacon") else "drand: unverified")
        tsa_lbl = "TSA: live RFC 3161" if live_tsa_verified else "TSA: stub"
        anchor_summary = f"{beacon_lbl} · {tsa_lbl}"
        scope_sub = f"Bundle integrity verified ({anchor_summary})."
    elif is_v1:
        badge_txt = "VERIFIED PASS (STUB ANCHOR MODE)"
        beacon_lbl = "drand: stub" if check_outcomes.get("drand_beacon") else "drand: unverified"
        anchor_summary = f"{beacon_lbl} · TSA: stub"
        scope_sub = f"Bundle integrity verified ({anchor_summary})."
    else:
        badge_txt = "VERIFIED PASS (LOCAL STUB MODE)"
        anchor_summary = "Local stub randomness & timestamp (v0.2)"
        scope_sub = "Bundle integrity verified (v0.2 local stub randomness and timestamp mode)."

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
        else '<p class="muted">All executed checks passed.</p>'
    )

    sim_note_html = ""
    if cert_authenticated:
        subj = auth_cert.get("subject") if isinstance(auth_cert.get("subject"), dict) else {}
        seed = auth_cert.get("seed") if isinstance(auth_cert.get("seed"), dict) else {}
        beacon = seed.get("beacon") if isinstance(seed.get("beacon"), dict) else {}
        ev = auth_cert.get("evidence") if isinstance(auth_cert.get("evidence"), dict) else {}
        tsa_rec = ev.get("tsa_receipts", {}) if is_v1 else {"timestamp_stub": ev.get("timestamp_stub", {})}

        raw_deviations = pre_doc.get("deviations_and_incidents", []) if isinstance(pre_doc, dict) else []
        deviations = raw_deviations if isinstance(raw_deviations, list) else []
        if any("simulat" in str(d).lower() for d in deviations) or subj.get("name") == "v1-compliant-bench":
            sim_note_html = '<div class="notice-banner"><strong>Evidence Provenance Notice:</strong> Pre-registration declares simulated/synthetic bench instruments for protocol verification; physical hardware data awaits bench assembly.</div>'

        ledger_rows_html = ""
        if is_v1 and ledger_rows:
            for row in ledger_rows:
                if not isinstance(row, dict):
                    continue
                ledger_rows_html += (
                    "<tr>"
                    f"<td>{_esc(row.get('seq'))}</td>"
                    f"<td><code>{_esc(row.get('slot_id'))}</code></td>"
                    f"<td><code>{_esc(row.get('execution_attempt_id'))}</code></td>"
                    f"<td>{_esc(row.get('status'))}</td>"
                    f"<td><code>{_esc(row.get('retry_of_attempt_id') or '—')}</code></td>"
                    f"<td>{_esc(_fmt_bool(row.get('trial_passed')))}</td>"
                    f"<td>{_esc(row.get('reason') or '—')}</td>"
                    "</tr>"
                )

        fam_rows_html = ""
        results_obj = auth_cert.get("results") if isinstance(auth_cert.get("results"), dict) else {}
        per_fam = results_obj.get("per_family", {})
        fam_items: list[tuple[str, dict[str, Any]]] = []
        if isinstance(per_fam, dict):
            fam_items = [(str(k), v) for k, v in sorted(per_fam.items()) if isinstance(v, dict)]
        elif isinstance(per_fam, list):
            for i, item in enumerate(per_fam):
                if isinstance(item, dict):
                    fam_items.append((str(item.get("family_id", item.get("family", i))), item))
        for fam, vals in fam_items:
            passed_cnt = vals.get("passed", vals.get("successes", "—"))
            reg_cnt = vals.get("registered", vals.get("trials", "—"))
            ci_val = vals.get("ci95", vals.get("wilson_95"))
            fam_rows_html += (
                "<tr>"
                f"<td><code>{_esc(fam)}</code></td>"
                f"<td>{_esc(passed_cnt)} / {_esc(reg_cnt)}</td>"
                f"<td>{_esc(_fmt_rate(vals.get('pass_rate')))}</td>"
                f"<td>{_esc(_fmt_ci(ci_val))}</td>"
                "</tr>"
            )

        adj_rows_html = ""
        raw_adj = auth_cert.get("adjudications", [])
        if isinstance(raw_adj, list):
            for adj in raw_adj:
                if not isinstance(adj, dict):
                    continue
                adj_rows_html += (
                    "<tr>"
                    f"<td><code>{_esc(adj.get('execution_attempt_id'))}</code></td>"
                    f"<td><code>{_esc(_fmt_scores(adj.get('original_scores')))}</code></td>"
                    f"<td><code>{_esc(_fmt_scores(adj.get('adjudicated_scores')))}</code></td>"
                    f"<td>{_esc(adj.get('reason') or '—')}</td>"
                    f"<td><code>{_esc(adj.get('adjudicator_id') or '—')}</code></td>"
                    "</tr>"
                )

        thumbs_html = ""
        for rel in sorted(verified_frame_bytes):
            uri = _npy_bytes_to_data_uri(verified_frame_bytes[rel])
            if uri:
                thumbs_html += (
                    '<figure class="thumb">'
                    f'<img src="{uri}" alt="Verified bundle frame {_esc(rel)}"/>'
                    f'<figcaption><code>{_esc(rel)}</code></figcaption>'
                    "</figure>"
                )

        beacon_bls_txt = (
            "passed (BLS12-381)"
            if live_beacon_verified
            else ("stub mode" if check_outcomes.get("drand_beacon") else "pending CLI")
        )

        adj_section_html = (
            f"""
<h2>Adjudications (Raw Scores Preserved)</h2>
<div class="table-wrap" role="region" aria-label="Adjudications" tabindex="0">
<table>
  <thead><tr><th scope="col">Attempt ID</th><th scope="col">Original Scores</th><th scope="col">Adjudicated Scores</th><th scope="col">Reason</th><th scope="col">Adjudicator</th></tr></thead>
  <tbody>{adj_rows_html}</tbody>
</table>
</div>
"""
            if adj_rows_html
            else ""
        )
        thumbs_section_html = (
            f"""
<h2>Manifest-Verified Frame Thumbnails</h2>
<div class="thumbs">{thumbs_html}</div>
"""
            if thumbs_html
            else ""
        )

        main_sections_html = f"""
<h2>Subject &amp; Physical Architecture</h2>
<div class="table-wrap" role="region" aria-label="Subject and Physical Architecture" tabindex="0">
<table>
  <tr><th scope="row">Certificate Version</th><td><code>{_esc(ver)}</code></td></tr>
  <tr><th scope="row">Subject / Snapshot</th><td><code>{_esc(subj.get('name'))}</code> / <code>{_esc(subj.get('snapshot'))}</code></td></tr>
  <tr><th scope="row">Pareto Profile &amp; Division</th><td><code>{_esc(auth_cert.get('pareto_profile', 'n/a'))}</code> &middot; <code>{_esc(subj.get('division'))}</code> &middot; <code>mask_tactile={_esc(_fmt_bool(auth_cert.get('mask_tactile')))}</code></td></tr>
  <tr><th scope="row">Disclosure Mode</th><td><code>{_esc(auth_cert.get('disclosure_mode', 'v0.2-open'))}</code></td></tr>
</table>
</div>

<h2>Cryptographic Provenance</h2>
<div class="table-wrap" role="region" aria-label="Cryptographic Provenance" tabindex="0">
<table>
  <tr><th scope="row">Commitment C</th><td><code>{_esc(seed.get('commitment_C'))}</code></td></tr>
  <tr><th scope="row">Randomness Beacon</th><td><code>{_esc(beacon.get('provider'))}</code> &middot; round <code>{_esc(beacon.get('round_number'))}</code> &middot; scheme <code>{_esc(beacon.get('scheme', 'stub'))}</code> &middot; CLI BLS check: <code>{_esc(beacon_bls_txt)}</code></td></tr>
  <tr><th scope="row">Genesis / Chain Root</th><td><code>{_esc(ev.get('genesis_hash'))}</code><br/><code>{_esc(ev.get('chain_root_hash'))}</code></td></tr>
</table>
</div>

<h2>RFC 3161 TSA Receipts</h2>
<div class="table-wrap" role="region" aria-label="RFC 3161 TSA Receipts" tabindex="0">
<table>
  <thead><tr><th scope="col">Stage</th><th scope="col">Provider</th><th scope="col">UTC Timestamp</th><th scope="col">Receipt / Digest SHA-256</th></tr></thead>
  <tbody>{_render_tsa_rows(tsa_rec, is_v1)}</tbody>
</table>
</div>

<h2>Per-Family Scores &amp; Wilson 95% CIs</h2>
<div class="table-wrap" role="region" aria-label="Per-Family Scores and Wilson Confidence Intervals" tabindex="0">
<table>
  <thead><tr><th scope="col">Family</th><th scope="col">Passed / Registered</th><th scope="col">Pass Rate</th><th scope="col">Wilson 95% CI</th></tr></thead>
  <tbody>{fam_rows_html or '<tr><td colspan="4">See certificate overall summary</td></tr>'}</tbody>
</table>
</div>

<h2>Slot Ledger</h2>
<div class="table-wrap" role="region" aria-label="Slot Ledger" tabindex="0">
<table>
  <thead><tr><th scope="col">Seq</th><th scope="col">Slot ID</th><th scope="col">Attempt ID</th><th scope="col">Status</th><th scope="col">Retry Of</th><th scope="col">Passed</th><th scope="col">Reason</th></tr></thead>
  <tbody>{ledger_rows_html or '<tr><td colspan="7">Applicable to v1.0 bundles</td></tr>'}</tbody>
</table>
</div>
{adj_section_html}{thumbs_section_html}
"""
    else:
        preview_subj = unauth_cert.get("subject") if isinstance(unauth_cert.get("subject"), dict) else {}
        main_sections_html = f"""
<div class="unauth-panel">
  <h2>UNAUTHENTICATED DIAGNOSTIC PREVIEW (SIGNATURE OR INTEGRITY FAILED)</h2>
  <p>Authenticated certificate subject, slot scores, adjudications, and frame thumbnails remain withheld because bundle verification failed or certificate signature validation raised an error.</p>
  <div class="table-wrap" role="region" aria-label="Unauthenticated Diagnostic Metadata" tabindex="0">
  <table>
    <tr><th scope="row">Unverified Claimed Version</th><td><code>{_esc(ver)}</code></td></tr>
    <tr><th scope="row">Unverified Claimed Subject</th><td><code>{_esc(preview_subj.get('name', 'unavailable'))}</code></td></tr>
    <tr><th scope="row">Unverified Disclosure Mode</th><td><code>{_esc(unauth_cert.get('disclosure_mode', 'unavailable') if isinstance(unauth_cert, dict) else 'unavailable')}</code></td></tr>
  </table>
  </div>
</div>
"""

    full_css = _build_embedded_font_css() + "\n" + _BASE_REPORT_CSS
    css_sha = base64.b64encode(hashlib.sha256(full_css.encode("utf-8")).digest()).decode("ascii")
    csp_header = (
        f"default-src 'none'; img-src data:; font-src data:; style-src 'sha256-{css_sha}'; "
        "base-uri 'none'; form-action 'none';"
    )
    reproduce_cmd = "eutropos-referee verify --evidence-dir <bundle_dir> --public-key <trusted.pem> --require-live-beacon --require-live-tsa"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="Content-Security-Policy" content="{csp_header}"/>
<title>{_esc(badge_txt)} &middot; kid {_esc(key_kid)} — Eutropos Audit Report</title>
<style>{full_css}</style>
</head>
<body>
<header class="masthead">
  <div class="brand-lockup">Eutropos <span class="brand-greek" lang="grc">εὔτροπος</span></div>
  <div class="masthead-sub">Offline Audit Report &middot; eutropos-referee=={_esc(__version__)}</div>
</header>

<div class="hero-panel">
  <p class="eyebrow">Eutropos Referee &middot; Self-Contained Offline Audit Report</p>
  <h1>Bundle Integrity &amp; Custody Audit</h1>
  <p><span class="{badge_cls}">{_esc(badge_txt)}</span> &nbsp; <span class="hero-meta">{_esc(scope_sub)}</span></p>
  <p class="hero-meta">Generated UTC: <code>{_esc(generated_utc)}</code> &middot; Tool: <code>eutropos-referee=={_esc(__version__)}</code> &middot; Checks Passed: <code>{passed_count} / {len(report.checks)}</code></p>
  <p class="hero-meta">Signer Trust: <code>{_esc(signer_trust_label)}</code> &middot; Anchors: <code>{_esc(anchor_summary)}</code></p>
  <p class="hero-meta">Trust Key Mode: <code>{_esc(report.trusted_key_mode)}</code> &middot; Key ID: <code>{_esc(key_kid)}</code> &middot; Ed25519 SHA-256: <code>{_esc(key_fp)}</code></p>
  <p class="hero-meta">Reproduce CLI: <code>{_esc(reproduce_cmd)}</code></p>
  {sim_note_html}
</div>

<h2>Failures &amp; Anomalies</h2>
{failures_html}

<h2>Executed Referee Checks ({passed_count} / {len(report.checks)})</h2>
<div class="table-wrap" role="region" aria-label="Executed Referee Checks" tabindex="0">
<table>
  <thead><tr><th scope="col">Check</th><th scope="col">Outcome</th><th scope="col">Detail</th></tr></thead>
  <tbody>{checks_rows_html}</tbody>
</table>
</div>

{main_sections_html}

<footer class="report-footer">
  <span>Eutropos &middot; Protocol v1.0 &middot; eutropos-referee=={_esc(__version__)}</span>
  <span>Single-File Offline HTML Report &middot; Zero Viewer Scripts</span>
</footer>
</body>
</html>
"""
