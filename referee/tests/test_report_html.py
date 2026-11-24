"""Tests for self-contained CSP-hardened offline HTML audit viewer."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

from eutropos_referee.cli import main as cli_main
from eutropos_referee.protocol_v1 import run_v1_session_bundle
from eutropos_referee.report_html import render_audit_html
from eutropos_referee.runner import run_bundle


def test_render_audit_html_v1_and_v02_with_xss_escaping(tmp_path: Path) -> None:
    pub1 = tmp_path / "v1_pub.pem"
    ev1 = run_v1_session_bundle(
        tmp_path / "ev1",
        pareto_profile="P2",
        mask_tactile=True,
        families=("E1", "E3"),
        write_trusted_public_key=pub1,
    )
    html1 = render_audit_html(ev1, public_key=pub1)
    assert "Content-Security-Policy" in html1
    assert "style-src 'sha256-" in html1
    assert "'unsafe-inline'" not in html1
    assert "base-uri 'none'" in html1
    assert "form-action 'none'" in html1
    assert "#C8AA74" in html1
    assert 'name="viewport"' in html1
    assert "VERIFIED PASS" in html1
    assert "eutropos-referee-certificate-v1.0" in html1
    assert "slot-00-attempt-0" in html1
    assert "slot-00-attempt-1" in html1
    assert "Executed Referee Checks" in html1
    assert "{'commitment':" not in html1
    assert "passed=<code>True</code>" not in html1

    # CLI smoke test + tampered ledger and unauthenticated XSS payload properly escaped
    ledger_p = ev1 / "manifests" / "slot_ledger.jsonl"
    raw_txt = ledger_p.read_text(encoding="utf-8")
    xss = "<script>alert('xss')</script>"
    lines = [json.loads(ln) for ln in raw_txt.splitlines() if ln.strip()]
    lines[0]["reason"] = xss
    ledger_p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    html_bad = render_audit_html(ev1, public_key=pub1)
    assert "VERIFICATION FAILED" in html_bad
    assert "UNAUTHENTICATED DIAGNOSTIC PREVIEW" in html_bad
    assert "slot-00-attempt-0" not in html_bad
    assert "<script>alert" not in html_bad

    # Inject XSS inside unauthenticated certificate subject payload -> must escape cleanly in diagnostic preview
    cert_p = ev1 / "certificate.json"
    cert_doc = json.loads(cert_p.read_text(encoding="utf-8"))
    bad_payload = json.dumps({"certificate_version": "eutropos-referee-certificate-v1.0", "subject": {"name": xss}})
    cert_doc["payload"] = base64.urlsafe_b64encode(bad_payload.encode("utf-8")).decode("ascii").rstrip("=")
    cert_p.write_text(json.dumps(cert_doc), encoding="utf-8")
    html_xss = render_audit_html(ev1, public_key=pub1)
    assert "UNAUTHENTICATED DIAGNOSTIC PREVIEW" in html_xss
    assert "<script>alert" not in html_xss
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_xss

    # v0.2 bundle with real .npy image thumbnails renders inline base64 PNGs for manifest-covered frames only
    pub0 = tmp_path / "v0_pub.pem"
    ev0 = run_bundle(tmp_path / "ev0", epochs=1, policy="scripted", write_trusted_public_key=pub0)
    rogue_npy = ev0 / "frames" / "rogue_unmanifested.npy"
    np.save(rogue_npy, np.zeros((16, 16, 3), dtype=np.uint8))
    out_html = tmp_path / "report_v0.html"
    rc = cli_main([
        "render-report",
        "--evidence-dir", str(ev0),
        "--public-key", str(pub0),
        "--out", str(out_html),
    ])
    assert rc == 0
    doc0 = out_html.read_text(encoding="utf-8")
    assert "VERIFICATION FAILED" in doc0
    assert '<figure class="thumb">' not in doc0
    assert "data:image/png;base64," not in doc0

    rogue_npy.unlink()
    rc_clean = cli_main([
        "render-report",
        "--evidence-dir", str(ev0),
        "--public-key", str(pub0),
        "--out", str(out_html),
    ])
    assert rc_clean == 0
    doc_clean = out_html.read_text(encoding="utf-8")
    assert "VERIFIED PASS" in doc_clean
    assert "data:image/png;base64," in doc_clean
