# Eutropos referee 1.0.0

Protocol v1.0 release integrating C2/C3 security hardening, A2
hidden-instrument proofs, Day-1 hardware drivers (`RadwagCBCP01Driver` +
`OverheadCameraDriver`), planar homography calibration, all 15 canonical
`TASK-SPEC-v1` evaluators, `AgileX NERO` 26-DoF MuJoCo bimanual twin +
isolated closed-loop `P0` VLM control (with process-tree containment and
authentic trace/artifact sealing), 4-judge `A4` harness, live
`drand-quicknet` BLS12-381 & RFC 3161 (`freetsa.org`) cryptographic
anchoring, Docker OCI athlete sandbox blueprint (`referee/docker/`), and
single-file CSP-hardened HTML audit reports.

From `sandbox`, after running `setup-inspect-robots.ps1`:

```powershell
.\.venv\Scripts\eutropos-referee.exe prove --out-dir .\logs\a1-v1rc1
.\.venv\Scripts\eutropos-referee.exe prove-instruments --out-dir .\logs\a2-v1rc1
.\.venv\Scripts\eutropos-referee.exe prove-v1 --live-crypto --out-dir .\logs\v1-live
.\.venv\Scripts\eutropos-referee.exe render-report --evidence-dir .\logs\v1-live\evidence_open --public-key .\logs\v1-live\trusted-v1-open.pem --require-live-beacon --require-live-tsa --out .\logs\v1-live\audit_report.html
.\.venv\Scripts\python.exe -m pytest ..\referee\tests -v
```

For MuJoCo closed-loop `P0` & 15-family simulation tests, run with
`.\.venv-nero\Scripts\python.exe -m pytest ..\referee\tests -v`.

Each destination must be absent or empty.

`prove` runs eight CubePick trials. It verifies against a public key
written outside the evidence directory. It then checks the four original
tamper cases.

`prove-instruments` runs four scenes with two epochs each. It verifies
the compliant run, five cheat-policy runs, and eight tampered copies.
A cheat run must have valid evidence and an overall pass rate of zero.
The five policies are `hand-on-scale`, `unsettled`, `mass-alias`,
`false-done`, and `spy-scene`.

Individual commands:

```powershell
.\.venv\Scripts\eutropos-referee.exe run `
  --out-dir .\logs\a1-run `
  --write-trusted-public-key .\logs\a1-trusted.pem

.\.venv\Scripts\eutropos-referee.exe run-instruments `
  --out-dir .\logs\a2-run `
  --write-trusted-public-key .\logs\a2-trusted.pem

.\.venv\Scripts\eutropos-referee.exe verify `
  --evidence-dir .\logs\a2-run `
  --public-key .\logs\a2-trusted.pem
```

`verify` requires an explicit public key. An explicit
`--trust-bundled-key` flag enables a self-consistency check. Its report
uses `trusted_key_mode="self-asserted-bundled-key"`. External-key
verification uses `trusted_key_mode="external-key"`.

A caller must obtain and protect the trusted key independently. Passing
a path inside the evidence directory still leaves that trust decision
with the caller.

## Encoding

Canonical JSON uses UTF-8, `ensure_ascii=False`, sorted keys, compact
separators, and `allow_nan=False`. It has no trailing newline. Duplicate
keys, non-finite numbers, and negative floating-point zero are rejected.
Canonical reads also require byte equality with canonical re-encoding.

DSSE payloads and signatures require RFC 4648 canonical Base64:
decode with `validate=True`, then require an exact encoding roundtrip.

`LP(x) = u64(len(x)) || x`. Integers use unsigned eight-byte big-endian
encoding.

```text
C = SHA256(
    b"eutropos-seed-commit-v0.2"
    || LP(S)
    || LP(nonce)
)

R = SHA256(
    b"eutropos-run-seed-v0.2"
    || LP(S)
    || LP(N)
    || LP(B)
)

eval_seed = int.from_bytes(R[:4], "big") & 0x7fffffff

instance_seed = SHA256(
    b"eutropos-trial-seed-v0.2"
    || R
    || LP(NFC(family_id).encode("utf-8"))
    || u64(global_trial_index)
)
```

`S` contains 32 random bytes. The nonce contains 16 random bytes.
The actual framework trial seed remains
`inspect_robots.rollout.derive_seed(eval_seed, scene.init_seed, epoch)`.

The stub beacon retains its explicit local rule:

```text
B = SHA256(b"eutropos-stub-beacon-v0" || u64(round_number))
```

`DrandHttpBeacon` implements the requested HTTP round interface and
checks the randomness/signature digest relationship. BLS signature
authentication remains an external verification step.
`RFC3161Client` constructs a DER TimeStampReq and submits it through an
injectable transport. Returned TSA responses retain
`externally_verified=False`. The proof commands use local stubs.

## Instrument contract

Inspect Robots 1.0.0 supplies `CameraSpec`, `StateField`, `StateSpec`,
and `ActionSemantics`. The embodiment uses those interfaces.

The athlete receives two 32 by 32 RGB images and fourteen joint
positions. Its action space has fourteen joint-delta dimensions.
Every Scene has `target=None` and empty metadata.

The embodiment is a deterministic state-machine mock. Positive movement
of its transfer joint moves one quarter of the visible E1 source
contents or one copper E3 bead. A second joint moves a decoy. Other
joints model pan pressure and shaking. The policy sees joint state and
synthetic stereo views. The hidden session holds mass and overhead
measurements.

This mock establishes software wiring and evidence rules. Physical
dynamics, manipulation ability, and sensor accuracy require separate
tests.

Scale evidence contains consecutive byte-exact 21-byte CBCP-01 SI
frames. The overhead document carries an explicit timestamp entry for
each scale sample, a SHA-256 of the scale bytes, and its own timestamped
frames. Both streams use episode-relative simulated seconds.

The terminal window is two seconds. Samples must cover the complete
window, including both endpoints, with gaps at most 0.100001 seconds.
The bundle verifier anchors both streams to `record.steps / 10`.
A stale trace therefore fails evidence validation.

Mass scoring requires stable gram readings, adjacent settled changes
at most 0.03 g, and settled median net mass within the target interval.
Geometry scoring checks drift, hands home, zero pan contact, intact
objects, exact identities/classes/counts, and occupancy inside the pan.

Targets are generated from the sealed per-trial seed. E3 decoy masses
are chosen in integer centigrams. Every quantity from zero through
eight decoys differs from the requested target mass by more than 0.8 g.

The preregistration commits to each hidden assignment by hash.
`referee_targets.json` is written at evaluation close. Each scorer
flushes its trial files before the referee sink hashes them. A fallback
flush runs at trial end.

## Evidence and native logs

The genesis is `SHA256(preregistration.json)`. Trial manifests form an
ordered chain. Session close seals the EvalLog, seed reveal, and, for
A2, the hidden target disclosure. The DSSE certificate signs the final
chain hash and recomputable results.

The verifier parses every frame, action line, and chunk line. It checks
record identity, explicit seed paths, counts, frame coverage, task and
space declarations, sample scores, aggregate metrics, and Wilson
intervals. All files must be referenced. Empty directories, links,
junctions, unsafe paths, and case aliases fail verification.

The plugin adds a documented referee extension to native records:
`configuration.spaces`, `configuration.scene.target`,
`referee.inference_latencies_s`, and `referee.athlete_views`.
At close it adds `EvalLog.configuration`. These fields capture bound
runtime declarations and public observations. Native fields retain
their values. The resulting bytes are sealed after these additions.

The native action/chunk layouts and evaluator ordering were reviewed
against the public
[v1.0.0 evaluator](https://raw.githubusercontent.com/robocurve/inspect-robots/v1.0.0/src/inspect_robots/eval.py)
and
[v1.0.0 rollout](https://raw.githubusercontent.com/robocurve/inspect-robots/v1.0.0/src/inspect_robots/rollout.py).

## Protocol v1.0 Anchoring, Dual Disclosure, and Hardware Drivers

- **v1.0 seed domain & pre/post beacon separation (`seed.py`, `protocol_v1.py`):**
  Uses `eutropos-seed-commit-v1.0`, `eutropos-run-seed-v1.0`, and
  `eutropos-trial-seed-v1.0`. `pre_beacon_registration.json` commits `C`,
  `submitter_N_hex`, `planned_slots`, `task_spec` & `body_configuration`
  hashes, and future `drand-quicknet` `target_round` before RFC 3161
  timestamping (`tsa/commitment.tsr`) and beacon retrieval.
- **External cryptography (`beacon.py`):** Verifies pinned
  `drand-quicknet` BLS12-381 signatures (`chain_hash` + `G2` pubkey) and
  strict RFC 3161 CMS/X.509 responses (`critical TIME_STAMPING EKU`,
  CA `key_cert_sign`, mandatory unique `content_type` & `message_digest`,
  ESS `SigningCertificate`/`SigningCertificateV2`, request `nonce`, and
  pinned `FREETSA_ROOT_SHA256` when `trusted_tsa_pem` is omitted).
- **Slot ledger & dual disclosure (`protocol_v1.py`, `disclosure.py`):**
  Append-only `manifests/slot_ledger.jsonl` enforces a monotonic slot
  state machine (`MAX_RETRIES_PER_SLOT = 2`, zero post-terminal attempts)
  and binds every completed attempt 1-to-1 to chained trial manifests and
  recomputed raw scores. `hazard-escrowed` moves `referee_targets.json`,
  `seed_reveal.json`, and surrogate traces outside the public bundle into
  symlink-checked `escrow_dir` while redacting secrets in `certificate.json`.
- **Day-1 bench CLI (`hardware_drivers.py`, `calibration.py`, `cli.py`):**
  `calibrate` computes px-to-mm planar homography from 4 corner cyan
  fiducials (`opencv-python-headless`), and `bench-check` audits
  `RadwagCBCP01Driver` (`5` valid zero-tare frames, zero timeouts,
  strict monotonic clocks) alongside live or mock overhead cameras.
- **Offline viewer (`report_html.py`):** `render-report` builds a single
  CSP-hardened HTML report (`default-src 'none'; img-src data:; style-src 'unsafe-inline'`)
  distinguishing `VERIFIED PASS (LIVE CRYPTO)` from `VERIFIED PASS (LOCAL STUB DEMO)`
  and `VERIFICATION FAILED`.

Incomplete runs retain a failure record and receive no completed-run
certificate. Physical `Radwag`/`Basler` bench purchase and `240`-trial
physical `A4` execution remain gated on vendor RFQs and T sign-off.
