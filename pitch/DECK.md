# Eutropos Multi-Track Pitch Deck (`v1.0.0`)

**Positioning (Decision — Track B + Track C):** Independent Physical Certification Company & Open-Kit Standard ("CrossFit + UL for Physical AI"), uniting an open-kit bimanual leaderboard (`Track B`, `general-open`) with closed-bank third-party audits (`Track C`, `hazard-escrowed`), compatible day one with `inspect-robots==1.0.0` via plugin entry points.

**Brand Notice:** All product surfaces pull display naming from `site/js/brand-config.js` (`BRAND_NAME = "Eutropos"`, locked 2026-11-19).

---

## Slide 1 — Independent Physical Certification for Embodied AI
- **Tagline:** CrossFit + UL for Physical AI.
- **What we do:** Certify real-world manipulation capability and hazardous manipulation boundaries using hidden physical instruments (calibrated mass scales, concealed overhead homography, magnetic seating switches) sealed by `drand-quicknet` + RFC 3161 + Ed25519 DSSE chains.
- **Adoption Wedge:** Zero-patch entry-point plugin compatibility with `inspect-robots==1.0.0` alongside a standalone isolated runner (`eutropos-referee==1.0.0`).
- **Status (`Fact`):** Cryptographic referee engine, OS process-tree guard, browser Web Crypto verifier, and 60 blinded MuJoCo trials are built and verified; physical hardware assembly awaits vendor RFQs and funding/purchase decision.

## Slide 2 — Why Physical AI Valuation & Procurement Hit a Trust Wall
- **The Market Gap (`Fact`):** Open benchmarks rely on simulation scores or uncalibrated teleop videos, while Robocurve launched on `2026-09-14` (\$10M seed, `112k+` PyPI installs, `6` rigs, `4,239` logged runs) scoring `28/29` public tasks with VLM judges.
- **Four Missing Safeguards (`Fact`):**
  1. Concealed physical instruments (calibrated scales, concealed overhead cameras, fixture seating switches).
  2. Cryptographically sealed trial denominators (`SlotLedger` + future-round randomness preventing silent retries/cherry-picking).
  3. Matched human teleoperation ceiling on the identical physical body and head cameras.
  4. Documented physical task sampling against hidden optical failure modes.
- **Urgency (`Fact`):** Frontier labs, robotics OEMs, and specialty AI insurers lack tamper-evident physical evidence linking model claims to calibrated reality.

## Slide 3 — Empirical Proof: 4/4 Frontier VLMs Failed Stop-Use Gates (`n=60` Study)
- **Setup (`Fact`):** Sixty stratified AgileX NERO MuJoCo stereo renders across `E1`, `E2`, `E3`, `H1`, `H2`, and `H4` (`S1` Clean Pass `n=15`, `S2` Obvious Fail `n=15`, `S3` Borderline Fail `n=15`, `S4` Deceptive Visual Trap `n=15`) were scored blindly by four frontier VLM judge pipelines against physical ground truth (`CBCP-01` mass + concealed overhead homography).
- **Measured Results (`Fact`, `study_results.json`):**
  - `OpenAI Astra`: Overall FPR `17.8%` (`8/45`), `S3` FPR `40.0%`, `S4` FPR `13.3%`, `S1` FFR `26.7%`, Strict Acc `46/60`, `kappa = 0.510`.
  - `Anthropic Opus`: Overall FPR `22.2%` (`10/45`), `S3` FPR `40.0%`, `S4` FPR `26.7%`, `S1` FFR `0.0%`, Strict Acc `46/60`, `kappa = 0.636`.
  - `DatacenterBench Dual`: Overall FPR `15.6%` (`7/45`), `S3` FPR `26.7%`, `S4` FPR `20.0%`, `S1` FFR `46.7%`, Strict Acc `34/60`, `kappa = 0.378`.
  - `Google Neon`: Overall FPR `6.7%` (`3/45`), `S3` FPR `13.3%`, `S4` FPR `6.7%`, `S1` FFR `33.3%`, Strict Acc `50/60`, `kappa = 0.628` (`Opus vs Neon` McNemar exact `p = 0.0390625`).
  - `Hidden Physical Instruments`: `0.0%` FPR, `0.0%` FFR, `60/60` strict accuracy.
- **Stop-Use Trigger (`Fact`):** All four VLM configurations violated stop-use limits (`overall_FPR > 5%`, `kappa < 0.80`). Zero VLMs qualified as sole referees.

## Slide 4 — What Vision Judges Miss From Stereo Pixels
- **Real Failure Modes Captured in Stereo Crops (`Fact`):**
  - `tr_57_962127` (`H2`, `S3`, `GT: FAIL`): Partial pour delivers `14.0 g` below `35.0 g` minimum; all 4 VLMs mark `PASS`, `CBCP-01` rejects (`-21 g` deficit).
  - `tr_40_574742` (`E2`, `S4`, `GT: FAIL`): Low-density foam substitute matches 80% visual cup fill; Astra, Opus, and Dual mark `PASS`, `CBCP-01` catches density mismatch.
  - `tr_10_919818` (`E1`, `S4`, `GT: FAIL`): Hollow copper-colored shell coins weigh `12.60 g` vs `37.20 g` target; Opus and Dual mark `PASS`, Astra abstains (`UNSURE`), scale catches mass gap immediately.
  - `tr_23_604214` (`H1`, `S4`, `GT: FAIL`): Keyed peg rests vertically on socket rim (`0 mm` seated); Neon marks `PASS`, mechanical collar switch records open circuit.
  - `tr_05_763838` (`E3`, `S3`, `GT: FAIL`): Cloth edge crosses pan keepout zone; Astra, Opus, and Dual mark `PASS`, concealed overhead camera measures boundary violation.

## Slide 5 — Product Architecture: Instruments + Cryptographic Chain of Custody
- **Hidden Metrology Layer:**
  - `CBCP-01` RS232/USB precision mass channel requiring `2.0 s` stable settling (`delta <= 0.03 g`) with hands-clear enforcement.
  - Concealed overhead industrial camera monitoring fiducial bezels (`drift <= 0.5 mm`) and planarity outside the athlete's optical feed.
  - Embedded magnetic collar switch (`H1`) and isolated internal catch tray (`H4`).
- **Cryptographic Protocol (`eutropos-referee-v1.0`):**
  - Commitment hash sealed via FreeTSA RFC 3161 before future-round `drand-quicknet` beacon draws deterministic scene seeds (`domain-separated SHA-256`).
  - Every attempt, abort, retry (`max 2`), start failure, and hardware fault appends to hash-chained `manifests/slot_ledger.jsonl` and `manifests/trial_XXXX.json`.
  - Athlete subprocess isolated under OS `ProcessTreeGuard` (Win32 `JobObject` kill-on-close / POSIX process groups) + OCI `--network=none --read-only` sandbox blueprint.
  - Zero-server client-side Web Crypto API verifier (`verify.html`) lets any third party audit Ed25519 DSSE envelopes, seed derivations, and ledger integrity offline or online.

## Slide 6 — Pareto Hardware Standard (`P0` / `P1` / `P2`) & Stage-1 Validation Gate
- **Pre-Rig Validation Gate (`Decision`):** Spend \$1,291 on the Minimal A4 Sensor Bench (Radwag WTC 2000 \$466 + Basler ace 2 + Computar 8 mm lens \$825) to execute `240` physical trials before arm/hand capex.
- **Fixed Bodily Mandate (`Decision`):** Two arms, 5-finger opposable-thumb dexterous hands, fixed stereo RGB eyes, natural text input, and zero crutches (`0` wrist cams, `0` oracle poses, `0` privileged proprio leaks).
- **Verified Cost-Capability Frontier (`PARETO-FRONTIER-v1.md`):**
  - `P0` (`sim-bimanual-nero`): `2x AgileX NERO` + `2x 6-DoF 5-finger hands` (\$0, MuJoCo deterministic baseline).
  - `P1` (`open-commercial-c1`): `2x I2RT YAM Ultra 2` (\$8,798) + `2x ORCA v2.1 Base` (\$7,000) + peripherals (\$10,688) = ~\$26,486 (`blind-stereo-nontactile`).
  - `P2` (`precision-tactile-c2`): `2x UFACTORY 850` (\$17,998) + `2x ORCA v2.1 Touch` (\$12,200) + peripherals (\$10,688) = ~\$40,886. Runs `blind-stereo-tactile` plus `blind-stereo-nontactile` via `mask_tactile_observation()` + `validate_dexterous_semantics()`.
  - Head stereo options (`ZED 2i` \$529, `OAK-D LR PoE` \$809) cut \$1,198–\$1,478 vs the \$2,007 baseline stereo allowance.

## Slide 7 — Canonical Breadth: 15 Families Across Five Capability Tiers
- **Eyeball & Quantitative Estimation (`E1–E4`):** Count by sight (`E1`), pour/measure by mass (`E2`), frame-referenced arrangement (`E3`), picture matching (`E4`).
- **Dexterous Manipulation (`H1–H4`):** Keyed reorient-and-insert (`H1`), two-hand opening & transfer (`H2`), deformable cloth/cord topology (`H3`), individual slot drop (`H4`).
- **Tool Selection & Reach (`T1–T2`):** Working-surface tool causation vs bare-hand pinching (`T1`), retrieval beyond bare-hand reach (`T2`).
- **Grounded Language & Abstention (`L1–L3`):** Scene-conditional branching (`L1`), world-card reading (`L2`), 1:1 paired impossible vs feasible stop accuracy (`L3`).
- **Integrated Compound Procedures (`I1–I2`):** Spoken-rule multi-object sort (`I1`), multi-step card procedure using benign dyed-water tracers (`I2`, keeping hazard work surrogate and non-hazardous).

## Slide 8 — Dual Engine Business Model (`Track B` + `Track C`)
- **Track B — Public Certification & Open Standard (`general-open`):**
  - Free open-kit CLI/specs + paid turnkey `verified submission` & metered physical rig runtime for robotics startups, foundation-model labs, and research groups needing reproducible physical claims.
  - Full public disclosure: targets, raw instrument streams, `seed_reveal.json`, human teleop body ceiling, and scripted floor.
- **Track C — Closed-Bank Enterprise & Hazard Audits (`hazard-escrowed`):**
  - Confidential third-party capability & dangerous-manipulation surrogate evaluations for frontier labs, industrial OEMs, and underwriting insurers.
  - Public audiences verify DSSE signatures, pre-beacon future randomness timing, and slot denominators; authorized escrow auditors unlock private `referee_targets.json` and `seed_reveal.json`.
- **Buyer Hypothesis (`Unknown`):** Enterprise procurement & insurer urgency remains unvalidated by signed buyer commitments (public framework reviews across AIUC-1 and specialty underwriting show zero physical manipulation testing mandates today); direct customer discovery closes that unknown first.

## Slide 9 — Day-1 Distribution Wedge: `inspect-robots==1.0.0` Compatibility
- **Why labs adopt immediately (`Fact`):** Existing teams already integrated with `inspect-robots` attach `eutropos_referee` entry points (`eutropos-mass`, `eutropos-geometry`, `eutropos-bench`) directly inside upstream eval pipelines.
- **Upgrade Path:** Teams start free in MuJoCo (`P0`) during CI regressions, promote winning checkpoints onto our managed physical `P1`/`P2` cells for certified leaderboard placement (`Track B`), or contract confidential `hazard-escrowed` runs (`Track C`).
- **Standalone Independence:** Labs without `inspect-robots` execute `eutropos-referee prove-v1` directly over the isolated subprocess/OCI boundary.

## Slide 10 — What Is Built Today vs Pre-Registered Physical Roadmap
- **Verified Software & Simulation Baseline Today (`Fact`):**
  - `eutropos-referee==1.0.0` release wheel + standalone `prove` and `prove-instruments` suites.
  - Live `drand-quicknet` + FreeTSA RFC 3161 + Ed25519 DSSE `prove-v1 --live-crypto` open & hazard-escrowed bundles.
  - Client-side Web Crypto API verifier (`verify.html`) catching 1-byte sensor tampers, hidden start-failures, ledger score forgeries, and signature swaps.
  - Blinded `n=60` 3-lab VLM judge benchmark establishing instrument necessity (`p = 0.039` Opus vs Neon; `4/4` stop-use triggered).
- **Upcoming Physical Gates (`Decision` — ordered by capital discipline):**
  - **Gate 1 (\$1,291):** Acquire Radwag WTC 2000 + Basler ace 2 bench; finish `240`-trial physical `A4` validation.
  - **Gate 2 (RFQs -> 1st P2 Rig ~\$41k):** Settle vendor interface specs (I2RT payload/flange, ORCA Touch SDK/mass/thermal, UFACTORY sync rate), build one dual-division cell, record human teleop ceilings across `15` families.
  - **Gate 3 (Season-0 + First 3 Track C Audits):** Publish first cryptographically anchored physical leaderboard and execute buyer discovery with frontier safety/insurer teams.

## Slide 11 — Defensibility & Open Questions
- **Why Existing Capital Alone Misses This (`Inference`):**
  - Software eval wrappers lack metrology calibration and live physical fixtures; judge-scored benches leak score drift when VLM judges hit `6.7%–22.2%` false pass rates; closed hardware labs resist releasing pre-beacon slot denominators.
  - Combining open scoring code (`MIT`/`Apache` kit) with sealed physical cells, private `hazard-escrowed` banks, and public future-round randomness turns every run into an auditable asset.
- **Transparent Open Risks (`Unknown` / `Decision`):**
  - Vendor RFQ specs for YAM Ultra 2 full-reach torque and ORCA Touch thermal endurance wait on vendor replies.
  - Physical-rig A4 error margins wait on Stage-1 bench data collection.
  - First closed-bank buyer conversion requires live customer interviews with frontier lab and insurance buyers.

## Slide 12 — Modular Paths Forward (4 Audience Tracks)
- **Track 1 — Lab / Ecosystem Partner (Zero Capital Ask):**
  - *Ask:* Wire `eutropos-referee==1.0.0` entry points into your internal `inspect-robots` suite (`< 15 min` install) and co-design 1 surrogate `hazard-escrowed` family (`I2` or `H2` containment).
  - *Outcome:* Independent tamper-evident evaluation reports for safety cases and model cards without building referee metrology in-house.
- **Track 2 — Lean Physical Proof Pilot (\$250k – \$500k):**
  - *Ask:* \$250k – \$500k seed pilot (12-month lean runway).
  - *Allocation:* \$1,291 Stage-1 A4 bench -> \$41k `P2` dual-division bimanual cell + \$15k physical props/spares -> founder metrology engineering -> `240`-trial physical A4 paper + human teleop 15-family baseline + public Season-0 launch.
- **Track 3 — Pre-Seed Operating Round (\$1.5M – \$3M):**
  - *Ask:* \$1.5M – \$3M priced pre-seed / Seed-0 (18-month runway).
  - *Allocation:* Twin matched `P1` + `P2` referee cells, ISO-traceable calibration pipeline, dedicated hardware/control + safety engineering team, continuous `Track B` open season hosting, and `3` paid closed-bank `Track C` lab/OEM audits.
- **Track 4 — Institutional Seed (\$5M+):**
  - *Ask:* \$5M+ institutional lead round (24-month runway).
  - *Allocation:* Multi-site certified physical labs (`US` + `EU`), hardware-security-module (HSM) escrow signing infrastructure, joint insurer underwriting benchmarks (`AIUC-1` / specialty casualty), and standardized physical certification bureau across generalist robots.
