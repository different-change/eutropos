# Eutropos — Independent Physical Referee & Open-Kit Standard

[![Eutropos CI](https://github.com/different-change/eutropos/actions/workflows/ci.yml/badge.svg)](https://github.com/different-change/eutropos/actions/workflows/ci.yml)

In trial `tr_57_962127` of our blinded 60-trial MuJoCo pilot, four vision-language judge pipelines across three providers approved a simulated pour whose actual settled mass reached **14.0 g** below the **35.0 g** threshold (`-21.0 g` deficit). Eutropos replaces camera guesswork with concealed bench metrology, pre-committed randomness, and cryptographic custody (`eutropos-referee==1.0.3`).

- **Live Product Site:** https://different-change.github.io/eutropos/
- **Client Web Crypto Verifier:** https://different-change.github.io/eutropos/verify.html
- **Why Vision Judges Fail (`n=60` MuJoCo Study):** https://different-change.github.io/eutropos/a4-study.html
- **Interactive Multi-Track Brief:** https://different-change.github.io/eutropos/pitch/deck.html?track=partner
- **Release Packages (`v1.0.3`):** https://github.com/different-change/eutropos/releases/tag/v1.0.3
- **Security Policy & Key Fingerprints:** [SECURITY.md](SECURITY.md)
- **Citation Metadata:** [CITATION.cff](CITATION.cff)

## Install & User Quickstart

Clone the pinned `v1.0.3` release (or install `eutropos_referee-1.0.3-py3-none-any.whl` from [GitHub Releases](https://github.com/different-change/eutropos/releases/tag/v1.0.3); PyPI registration is pending), verify **both** bundled live-anchored demos, and render a standalone CSP-hardened HTML audit report:

```bash
git clone --branch v1.0.3 --depth 1 https://github.com/different-change/eutropos.git
cd eutropos
pip install ./referee
eutropos-referee --version
eutropos-referee verify --evidence-dir site/data/bundles/open_live --public-key site/data/bundles/open_live.trusted.pem --require-live-beacon --require-live-tsa
eutropos-referee verify --evidence-dir site/data/bundles/hazard_live --public-key site/data/bundles/hazard_live.trusted.pem --require-live-beacon --require-live-tsa
eutropos-referee render-report --evidence-dir site/data/bundles/open_live --public-key site/data/bundles/open_live.trusted.pem --require-live-beacon --require-live-tsa --out audit_report.html
```

Verify downloaded `v1.0.3` GitHub Release assets against `SHA256SUMS.txt` and Sigstore build provenance:

```bash
sha256sum --ignore-missing -c SHA256SUMS.txt
gh attestation verify eutropos_referee-1.0.3-py3-none-any.whl --repo different-change/eutropos
```

On Windows PowerShell (exits nonzero on checksum mismatch):

```powershell
Get-Content SHA256SUMS.txt | ForEach-Object { $h,$f = $_ -split '\s+',2; if (Test-Path $f) { $a = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower(); Write-Output "${f}: $($a -eq $h)"; if ($a -ne $h) { throw "Checksum mismatch for $f" } } }
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

| Component | Status (`v1.0.3`) | Scope & Boundary |
|---|---|---|
| `eutropos-referee` Python engine & CLI | Built & verified | `125` pytest tests (with MuJoCo installed; `121` passed, `4` skipped when optional MuJoCo is absent), `ProcessTreeGuard`, OCI spec, strict RFC 3161 & BLS12-381 verifiers, single-snapshot embedded-font SHA-256 CSP HTML reports |
| Browser Web Crypto + DER `.tsr` verifier | Built & verified | Ed25519 PAE, strict `certificate_version`, SHA-256 chain/manifest, `disclosure_receipt`, fixed CMS SignedData DER timestamps, `22` Open / `21` Hazard checks |
| Blinded `A4` VLM judge study (`n=60`) | Completed in simulation | MuJoCo `640x480` stereo frames (`gpt-6-astra`, `claude-opus-5-5`, 2-stage Dual, `Gemini 4 Neon`) vs simulator GT |
| Stage-1 `$1,291` core sensor bench & `n=240` study | Pending hardware purchase | `$1,291` 2-item core sensor subtotal (`Radwag WTC 2000` `$466` + `Basler ace 2 a2A2448-75ucBAS` `$689` + `Basler C23-0824-5M 8 mm` lens `$136`); stereo camera (`ZED 2i` `$529` / `OAK-D LR` `$809`) & `H1`/`H4` fixtures budgeted separately |
| Physical `P1` / `P2` bimanual referee cells | Spec & vendor RFQs open | `YAM Ultra 2 + ORCA v2.1 Base` (`P1`) / `UFACTORY 850 + ORCA v2.1 Touch` (`P2`); physical runs follow RFQs |

## Pinned Demo Signing Key Fingerprints

- **Open Track Demo (`open_live`):** `kid=1ce3689cc2c269b4` · `sha256=1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744`
- **Escrowed Track Demo (`hazard_live`):** `kid=1d496df7c8a8001a` · `sha256=1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd`

## Layout

- `referee/`: `eutropos-referee==1.0.3` Python package, CLI (`prove`, `prove-instruments`, `prove-v1`, `verify`, `render-report`, `bench-check`), OCI Dockerfile, embedded `.woff2` fonts, and pytest suite.
- `site/`: Static product site (client-side Web Crypto + DER verifier), `.well-known/security.txt`, and offline-capable bundle verifier (`index.html`, `verify.html`, `a4-study.html`, `rig.html`).
- `pitch/`: Interactive 12-slide presentation (`pitch/deck.html`) + Markdown script (`pitch/DECK.md`).
- `spec/`: Canonical specifications (`TASK-SPEC-v1.md`, `REFEREE-PROTOCOL-v1.md`, `PARETO-FRONTIER-v1.md`, `JUDGE-EXPERIMENT-v0.md`).
- `deploy/`: Site dataset exporter (`export_site_data.py`) and Node Web Crypto + tamper regression runner (`test_web_verifier.mjs`).

## License

Released under the [MIT License](LICENSE).
