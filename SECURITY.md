# Security Policy — Eutropos

## Reporting Vulnerabilities or Verification Bypasses

Report cryptographic verification flaws, custody-chain bypasses, containment escapes, or dependency vulnerabilities privately to `different.change@pm.me` with reproduction steps and bundle digests.

## Verification Trust Boundaries (`v1.0.1`)

- **Browser Verifier (`site/verify.html` & `site/js/verifier-core.js`):** Verifies Ed25519 DSSEv1 PAE signatures via Web Crypto (`crypto.subtle`), recomputes SHA-256 `slot_ledger` chains and artifact manifests, parses ASN.1 DER RFC 3161 `TSTInfo` `genTime` bounds against `drand-quicknet` round timestamps, checks Track C `seed_reveal.json` key bindings, and requires explicit user upload of an external trusted `.pem` key to grant third-party trust outside the pinned demo keys below.
- **Offline CLI (`eutropos-referee verify`):** Performs full cryptographic signature checks for both the browser-covered checks and full `drand-quicknet` BLS12-381 beacon signature verification plus FreeTSA CMS / X.509 certificate verification.

## Pinned Demo Public Keys (Software Demo Bundles)

Demo certificates hosted under `site/data/bundles/` represent software-simulated custody proofs anchored to live `drand-quicknet` beacons and FreeTSA RFC 3161 timestamps:

- **Open Demo (`open_live`):** `kid=1ce3689cc2c269b4` · `sha256=1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744`
- **Escrowed Demo (`hazard_live`):** `kid=1d496df7c8a8001a` · `sha256=1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd`
