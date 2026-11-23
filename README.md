# Eutropos — Independent Physical Certification & Open-Kit Standard

Cryptographically sealed referee engine, hidden physical metrology specs, browser Web Crypto bundle verifier, and interactive Pareto rig catalog (`eutropos-referee==1.0.1`).

- **Live Product Site:** https://different-change.github.io/eutropos/
- **Client Web Crypto Verifier:** https://different-change.github.io/eutropos/verify.html
- **Why Cameras Fail (`n=60` MuJoCo Study):** https://different-change.github.io/eutropos/a4-study.html
- **Interactive Multi-Track Pitch Deck:** https://different-change.github.io/eutropos/pitch/deck.html
- **Release Packages (`v1.0.1`):** https://github.com/different-change/eutropos/releases/tag/v1.0.1
- **Security Policy & Key Fingerprints:** [SECURITY.md](SECURITY.md)
- **Citation Metadata:** [CITATION.cff](CITATION.cff)

## Install & User Quickstart

Install the pinned `v1.0.1` release (or download the pre-built wheel and `SHA256SUMS.txt` from [Release v1.0.1](https://github.com/different-change/eutropos/releases/tag/v1.0.1)):

```bash
pip install "git+https://github.com/different-change/eutropos.git@v1.0.1#subdirectory=referee"
eutropos-referee --version
```

Verify the bundled Open Demo (`track=general-open`) certificate chain and render an offline HTML audit report:

```bash
eutropos-referee verify site/data/bundles/open_live
eutropos-referee render-report site/data/bundles/open_live --out audit_report.html
```

## Contributor Test Commands

```bash
git clone https://github.com/different-change/eutropos.git
cd eutropos
pip install -e "./referee[dev]"
pytest referee/tests -q
node deploy/test_web_verifier.mjs
```

## Verified Software vs. Pending Physical Hardware

| Component | Status (`v1.0.1`) | Scope & Boundary |
|---|---|---|
| `eutropos-referee` Python engine & CLI | Built & verified | `125` pytest tests (`.venv-nero`), `ProcessTreeGuard`, OCI spec, strict RFC 3161 & BLS12-381 verifiers |
| Browser Web Crypto + DER `.tsr` verifier | Built & verified | Ed25519 PAE, SHA-256 chain/manifest, RFC 3161 ASN.1 DER timestamps, `20` Open / `19` Hazard checks |
| Blinded `A4` VLM judge study (`n=60`) | Completed in simulation | MuJoCo stereo frames (`gpt-6-astra`, `claude-opus-5-5`, Dual, `Gemini 4 Neon`) vs simulator GT |
| Stage-1 `$1,291` sensor bench & `n=240` study | Pending hardware purchase | `Radwag WTC 2000` (`$466`) + `Basler ace 2` + `8 mm` lens (`$825`) + stereo/H1/H4 fixtures |
| Physical `P1` / `P2` bimanual referee cells | Spec & vendor RFQs open | `YAM Ultra 2 + ORCA v2.1 Base` / `UFACTORY 850 + ORCA v2.1 Touch`; physical runs follow RFQs |

## Pinned Demo Signing Key Fingerprints

- **Track B Open Demo (`open_live`):** `kid=1ce3689cc2c269b4` · `sha256=1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744`
- **Track C Hazard-Escrowed Demo (`hazard_live`):** `kid=1d496df7c8a8001a` · `sha256=1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd`

## Layout

- `referee/`: `eutropos-referee==1.0.1` Python package, CLI (`prove`, `prove-instruments`, `prove-v1`, `verify`, `render-report`, `bench-check`), OCI Dockerfile, and pytest suite.
- `site/`: Zero-server static product site, `.well-known/security.txt`, and offline-capable Web Crypto + DER bundle verifier (`index.html`, `verify.html`, `a4-study.html`, `rig.html`).
- `pitch/`: Interactive 12-slide presentation (`pitch/deck.html`) + Markdown script (`pitch/DECK.md`).
- `spec/`: Canonical specifications (`TASK-SPEC-v1.md`, `REFEREE-PROTOCOL-v1.md`, `PARETO-FRONTIER-v1.md`, `JUDGE-EXPERIMENT-v0.md`).
- `deploy/`: Site dataset exporter (`export_site_data.py`) and Node Web Crypto + tamper regression runner (`test_web_verifier.mjs`).

## License

Released under the [MIT License](LICENSE).
