# Security Policy — Eutropos

## Supported Versions

| Release Line | Security Status |
|---|---|
| `1.0.x` | Active security patches and verifier hardening |
| `< 1.0` | Superseded; upgrade to `v1.0.3` |

## Reporting Vulnerabilities or Verification Bypasses

Report cryptographic verification flaws, custody-chain bypasses, containment escapes, or dependency vulnerabilities privately to `different.change@pm.me` with reproduction steps and bundle digests.

## Response Timeline & Disclosure

Maintainers acknowledge vulnerability reports within `5` business days, assess reproduction against a pinned bundle or failing unit test, and coordinate public release notes once a patched release is available.

## Safe Harbor

Good-faith security testing scoped to published source code, local verifier invocations, and public demo bundles hosted under `https://different-change.github.io/eutropos/` (`/.well-known/security.txt` resolves under `/eutropos/.well-known/security.txt`) is authorized under coordinated disclosure. Keep testing confined to local software instances and published demo artifacts.

## Encryption & PGP

Plaintext vulnerability reports go to `different.change@pm.me`. Maintainers provide an ASCII-armored PGP key during initial triage ahead of custom-domain key publication.

## Verification Trust Boundaries (`v1.0.3`)

- **Browser Verifier (`site/verify.html` & `site/js/verifier-core.js`):** Checks external key trust mode (pinned demo keys vs uploaded `.pem`), enforces `certificate_version` (`eutropos-referee-certificate-v1.0`) and Ed25519 DSSEv1 PAE signatures via Web Crypto (`crypto.subtle`), verifies `certificate_seed`, `submitter_commitment`, `pre_post_binding`, `drand_pinned_network` (48-byte `signature_hex` + `SHA256(sig)==value_hex`), `post_beacon_after_round` timing, `commitment_C`, `derived_R_v1`, `slot_ledger_machine`, `slot_summary`, chained `manifest_chain`, exact `manifest_inventory` completeness/sizes/SHA-256 digests, strict CMS `SignedData` ASN.1 DER RFC 3161 `TSTInfo` tokens (`PKIStatus` `0`/`1`, `id-sha256` OID, strict calendar `genTime` bounds, full outer/inner DER byte consumption), and explicit `disclosure_receipt` rules (`general-open` `seed_reveal.json` + `referee_targets.json` SHA-256 & byte length vs `hazard-escrowed` canonical `escrow_root_sha256` & redacted artifact absence).
- **Offline CLI (`eutropos-referee verify`):** Enforces all custody invariants above plus full `drand-quicknet` BLS12-381 beacon signature verification and full FreeTSA CMS / X.509 certificate verification, and `render-report` captures one verified byte snapshot before rendering CSP-hardened HTML with an amber self-asserted trust badge whenever a bundled signer key supplies verification outside an explicit external `.pem`.

## Pinned Demo Public Keys (Software Demo Bundles)

Demo certificates hosted under `site/data/bundles/` represent software-simulated custody proofs anchored to live `drand-quicknet` beacons and FreeTSA RFC 3161 timestamps:

- **Open Track Demo (`open_live`):** `kid=1ce3689cc2c269b4` · `sha256=1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744`
- **Escrowed Track Demo (`hazard_live`):** `kid=1d496df7c8a8001a` · `sha256=1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd`
