"""Tests for zero-dependency CSP-hardened offline HTML audit viewer."""

from __future__ import annotations

import json
from pathlib import Path

from habilis_referee.cli import main as cli_main
from habilis_referee.manifest import read_json, write_json
from habilis_referee.protocol_v1 import run_v1_session_bundle
from habilis_referee.report_html import render_audit_html
from habilis_referee.runner import run_bundle


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
    assert "VERIFIED PASS" in html1
    assert "habilis-referee-certificate-v1.0" in html1
    assert "slot-00-attempt-0" in html1
    assert "slot-00-attempt-1" in html1

    # CLI smoke test + tampered slot reason with XSS payload properly escaped
    ledger_p = ev1 / "manifests" / "slot_ledger.jsonl"
    raw_txt = ledger_p.read_text(encoding="utf-8")
    xss = "<script>alert('xss')</script>"
    # Tamper reason in ledger -> fails verification AND must escape raw HTML tag
    lines = [json.loads(ln) for ln in raw_txt.splitlines() if ln.strip()]
    lines[0]["reason"] = xss
    ledger_p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    html_bad = render_audit_html(ev1, public_key=pub1)
    assert "VERIFICATION FAILED" in html_bad
    assert "<script>alert" not in html_bad
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_bad

    # v0.2 bundle with real .npy image thumbnails renders inline base64 PNGs
    pub0 = tmp_path / "v0_pub.pem"
    ev0 = run_bundle(tmp_path / "ev0", epochs=1, policy="scripted", write_trusted_public_key=pub0)
    out_html = tmp_path / "report_v0.html"
    rc = cli_main([
        "render-report",
        "--evidence-dir", str(ev0),
        "--public-key", str(pub0),
        "--out", str(out_html),
    ])
    assert rc == 0
    doc0 = out_html.read_text(encoding="utf-8")
    assert "VERIFIED PASS" in doc0
    assert "data:image/png;base64," in doc0
