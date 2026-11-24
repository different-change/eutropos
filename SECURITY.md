# Security Policy — Eutropos

## Supported Versions

| Release Line | Security Status |
|---|---|
| `1.0.x` | Active security patches and verifier hardening |
| `< 1.0` | Superseded; upgrade to `v1.0.2` |

## Reporting Vulnerabilities or Verification Bypasses

Report cryptographic verification flaws, custody-chain bypasses, containment escapes, or dependency vulnerabilities privately to `different.change@pm.me` with reproduction steps and bundle digests.

## Response Timeline & Disclosure

Maintainers acknowledge vulnerability reports within `5` business days, assess reproduction against a pinned bundle or failing unit test, and coordinate public release notes once a patched release is available.

## Safe Harbor

Good-faith security testing scoped to published source code, local verifier invocations, and public demo bundles is authorized under coordinated disclosure. Keep testing confined to local software instances and published demo artifacts.

## Encryption & PGP

Plaintext vulnerability reports go to `different.change@pm.me`. Maintainers provide an ASCII-armored PGP key during initial triage ahead of custom-domain key publication.

## Verification Trust Boundaries (`v1.0.2`)

- **Browser Verifier (`site/verify.html` & `site/js/verifier-core.js`):** Verifies Ed25519 DSSEv1 PAE signatures via Web Crypto (`crypto.subtle`), recomputes SHA-256 `slot_ledger` chains and artifact manifests, parses ASN.1 DER RFC 3161 `TSTInfo` `genTime` bounds against `drand-quicknet` round timestamps (`post_beacon_after_round` ordering), checks `Open Track` (`general-open`) `seed_reveal.json` key bindings and `referee_targets.json` digests, enforces `Escrowed Track` (`hazard-escrowed`) absence of `seed_reveal.json` and `referee_targets.json` while checking commitments, escrow receipt, and slot ledger, and requires explicit upload of an external trusted `.pem` key to grant third-party signer trust outside the pinned demo keys below.
- **Offline CLI (`eutropos-referee verify`):** Performs full cryptographic signature checks covering both browser checks and full `drand-quicknet` BLS12-381 beacon signature verification plus FreeTSA CMS / X.509 certificate verification.

## Pinned Demo Public Keys (Software Demo Bundles)

Demo certificates hosted under `site/data/bundles/` represent software-simulated custody proofs anchored to live `drand-quicknet` beacons and FreeTSA RFC 3161 timestamps:

- **Open Track Demo (`open_live`):** `kid=1ce3689cc2c269b4` · `sha256=1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744`
- **Escrowed Track Demo (`hazard_live`):** `kid=1d496df7c8a8001a` · `sha256=1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd`
