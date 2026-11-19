# Eutropos — Independent Physical Certification & Open-Kit Standard

Cryptographically sealed referee engine, hidden physical metrology specs, browser Web Crypto bundle verifier, and interactive Pareto rig catalog (`eutropos-referee==1.0.0`).

- **Live Product Site:** https://different-change.github.io/eutropos/
- **Client Web Crypto Verifier:** https://different-change.github.io/eutropos/verify.html
- **Interactive Multi-Track Pitch Deck:** https://different-change.github.io/eutropos/pitch/deck.html
- **Release Packages (`v1.0.0`):** https://github.com/different-change/eutropos/releases/tag/v1.0.0

## Quickstart

```bash
pip install "git+https://github.com/different-change/eutropos.git#subdirectory=referee"
# Or from a local checkout:
pip install -e ./referee
pytest referee/tests -q
node deploy/test_web_verifier.mjs
```

## Layout

- `referee/`: `eutropos-referee==1.0.0` Python package, CLI (`prove`, `prove-instruments`, `prove-v1`, `verify`, `render-report`, `bench-check`), OCI Dockerfile, and test suite.
- `site/`: Zero-server static web product and offline-capable Web Crypto bundle verifier (`index.html`, `verify.html`, `a4-study.html`, `rig.html`).
- `pitch/`: Interactive 12-slide presentation (`pitch/deck.html`) + Markdown script (`pitch/DECK.md`).
- `spec/`: Canonical task specifications (`TASK-SPEC-v1.md`, `REFEREE-PROTOCOL-v1.md`, `PARETO-FRONTIER-v1.md`, `JUDGE-EXPERIMENT-v0.md`).
