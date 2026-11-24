# Eutropos Multi-Track Brief (`v1.0.2`)

**Positioning (`Open Track + Escrowed Track`):** Independent Physical Referee & Open-Kit Standard, pairing an open two-arm benchmark (`Open Track`, Protocol `Track B` `general-open`) with third-party confidential audits (`Escrowed Track`, Protocol `Track C` `hazard-escrowed`), interoperable day one with `inspect-robots==1.0.0`.

---

## Slide 1 — Cameras Guess. Mass, Depth, and Pose Decide.
- **Headline:** Cameras guess. Mass, depth, and pose decide.
- **What it does:** An independent physical exam for embodied AI grading unassisted two-arm manipulation with concealed referee instruments (scales, overhead homography, seating switches) sealed by `drand-quicknet`, FreeTSA RFC 3161, and Ed25519 DSSE chains.
- **Status (`Fact`):** `eutropos-referee==1.0.2` (MIT), OS process-tree guard, client Web Crypto + DER verifier, and `n = 60` MuJoCo pilot run today; physical sensor hardware starts with the `$1,291` core sensor subtotal (stereo camera & fixtures separate).

## Slide 2 — Vision Judges & Highlight Reels Distort Physical Benchmarks
- **Published Landscape (`Fact`):** Robocurve disclosed `$10M` seed (Sep 2026), MIT `inspect-robots` (`112k+` downloads), `6` YAM rigs, and `4,239` logged runs scoring `28/29` public tasks by humans or VLM judges reading camera frames. Reviewed public drafts across frontier frameworks (AIUC-1, CAICT/TC260, EU GPAI, UK AISI / US CAISI, accessed `2026-11-17`) lack standing calibrated physical manipulation test mandates.
- **Four Open Verification Gaps:**
  1. Concealed metrology outside optical view (`CBCP-01`, overhead homography, fixture switches).
  2. Cryptographically pre-committed `SlotLedger` denominators blocking silent retries.
  3. Matched human teleoperation ceiling on identical hardware and stereo eyes.
  4. Stratified borderline and deceptive decoy traps exposing pixel ambiguity.

## Slide 3 — Four Vision Judge Pipelines Failed Pilot Gate Thresholds
- **Setup (`Fact`):** Sixty stratified AgileX NERO MuJoCo episodes across `E1`, `E2`, `E3`, `H1`, `H2`, and `H4` (`S1` clean `n=15`, `S2` obvious fail `n=15`, `S3` borderline fail `n=15`, `S4` optical decoy `n=15`) were scored blindly by four VLM pipelines across three providers against deterministic simulator physics ground truth (defined by construction; physical sensor accuracy awaits `n = 240` physical bench runs).
- **Results (`Fact`, `a4_study.json`):**
  - `GPT-6 Astra` (`robodojo_astra`): FPR `17.8%` (`8/45`), `S2 0/15`, `S3 40.0%`, `S4 13.3%`, `S1` FFR `26.7%`, Binary Acc `48/60`, Exact Acc `46/60`, `kappa = 0.510`.
  - `Claude Opus 5.5` (`claude_opus_5_5`): FPR `22.2%` (`10/45`), `S2 0/15`, `S3 40.0%`, `S4 26.7%`, `S1` FFR `0.0%`, Binary Acc `50/60`, Exact Acc `46/60`, `kappa = 0.636`.
  - `DataCenterBench Dual` (`datacenterbench_dual`, independent 2-stage Astra + Opus re-query): FPR `15.6%` (`7/45`), `S2 0/15`, `S3 26.7%`, `S4 20.0%`, `S1` FFR `46.7%`, Binary Acc `46/60`, Exact Acc `34/60`, `kappa = 0.378`.
  - `Gemini 4 Neon` (`gemini_4_neon`): FPR `6.7%` (`3/45`), `S2 0/15`, `S3 13.3%`, `S4 6.7%`, `S1` FFR `33.3%`, Binary Acc `52/60`, Exact Acc `50/60`, `kappa = 0.628` (`Opus vs Neon` raw exact McNemar `p = 0.039`; Holm adjusted across 6 pairs `p = 0.234`).
- **Joint Gate Outcome (`Fact`):** All four pipelines breached `kappa >= 0.80` (`3/4` exceeded `5%` FPR cleanly while `Neon` `3/45` CI `2.3%–17.9%` overlaps `5%`); Binary Acc treats `PARTIAL`/`UNSURE` as non-pass, while Exact Acc penalizes `UNSURE` on both classes.

## Slide 4 — Three Optical Failure Modes Separated in Simulation
- `tr_57_962127` (`H2`, `S3`): Partial pour (`14.0 g` vs `35.0 g` min); `4/4` VLM pipelines false-PASS.
- `tr_40_574742` (`E2`, `S4`): Lightweight foam decoy; Astra/Opus/Dual false-PASS, Neon abstains (`UNSURE`).
- `tr_23_604214` (`H1`, `S4`): Peg seated `0 mm` (resting on socket rim); Neon false-PASS.
- `tr_10_919818` (`E1`, `S4`): Thin copper lookalikes (`12.60 g` vs `37.20 g`); Opus and Dual (fresh 2-stage Astra + Opus re-query) marked `PASS`, solo Astra `UNSURE`, Neon flags thin shells (`FAIL`). Concealed `CBCP-01` settled reads target deterministic mass rejection once Stage-1 hardware runs.

## Slide 5 — Tamper-Evident End-to-End Custody (`eutropos-referee==1.0.2`)
- **Specified Metrology (Pending Stage-1 Build):** `CBCP-01` settled reads (`2.0 s`, `<= 0.03 g` ripple), concealed overhead homography (`<= 0.5 mm`), socket collar switch (`H1`), isolated catch tray (`H4`).
- **Built Protocol v1.0 Custody (`eutropos-referee==1.0.2`):** FreeTSA RFC 3161 commitment -> future-round `drand-quicknet` draw -> hash-chained `slot_ledger.jsonl` + manifests -> Win32/POSIX process-tree guard (+ OCI spec) -> browser Ed25519 + DER TSTInfo checker + full BLS/X.509 CLI verifier (`rounds 34109625 & 34109628` verified as software demo proofs).

## Slide 6 — Standard Two-Arm Rig: `P0` Sim -> `P1` Base -> `P2` Tactile
- `Stage 1 Core` (`$1,291*`): Radwag WTC 2000 (`$466`) + Basler ace 2 + Computar 8 mm (`$825`); head stereo camera (`ZED 2i` `$529` or `OAK-D LR` `$809`) and `H1/H4` fixtures budgeted separately for the `240`-trial physical setup.
- `P0` (`$0` MuJoCo): `2x AgileX NERO` (`7-DoF` simulation arms) + `2x 6-DoF` hands = `26 DoF`.
- `P1` (~`$26,486`): `2x 6-DoF YAM Ultra 2` (`$8,798`) + `2x 17-DoF ORCA Base` (`$7,000`) + peripherals (`$10,688`) = `46 DoF` (`blind-stereo-nontactile`).
- `P2` (~`$40,886`): `2x 6-DoF UFACTORY 850` (`$17,998`) + `2x 17-DoF ORCA Touch` (`$12,200`) + peripherals (`$10,688`) = `46 DoF` (tactile + `mask_tactile=True` parity).

## Slide 7 — 15 Specified Families (6 Exercised in Simulation)
- **Estimation (`E1–E4`):** Count (`E1`, sim), mass pour (`E2`, sim), alignment (`E3`, sim), 3D match (`E4`).
- **Dexterous & Tools (`H1–H4`, `T1–T2`):** Keyed insert (`H1`, sim), opening (`H2`, sim), soft cloth (`H3`), slot drops (`H4`, sim), tools/reach (`T1–T2`).
- **Language & Procedures (`L1–L3`, `I1–I2`):** Branching (`L1`), world card (`L2`), 1:1 impossible abstention (`L3`), multi-step benign tracer procedures (`I1–I2`).

## Slide 8 — Open Standard Adoption · Paid Third-Party Escrow
- **Open Track (`Track B · general-open`):** Free MIT kit + metered hardware leaderboard runs & calibrated bench kits.
- **Escrowed Track (`Track C · hazard-escrowed`):** Fixed-fee confidential capability & escrow audits concealing `seed_reveal.json` and `referee_targets.json`.
- **Comparison vs wrappers:** Hidden physical sensors + pre-beacon denominators + independent of competing model weights.

## Slide 9 — Runs Inside `inspect-robots==1.0.0` or Standalone
- Entry points plug into existing `inspect-robots` pipelines directly; standalone `prove-v1` and subprocess guards work independently of any single framework, designed to run identical scoring code in simulation today and on `P1/P2` rigs once commissioned.

## Slide 10 — Verified Software Today · Gated Physical Build
- **Built Today:** `eutropos-referee==1.0.2`, live `drand`/FreeTSA software custody demos, `n=60` MuJoCo pilot, SHA-256-CSP offline audit HTML report + browser verifier.
- **Sequenced Gates:**
  1. **Gate 1 (`$1,291` core subtotal + stereo/fixtures):** Stage-1 sensor bench + 240 physical A4 validation trials.
  2. **Gate 2 (After RFQs):** Confirm `YAM Ultra 2` (`P1`) & `ORCA Touch` / `UFACTORY 850` (`P2`) specs; build first physical `P2` rig.
  3. **Gate 3 (Season-0):** Record human teleop ceilings across 15 families; open `Open Track` submissions.
  4. **Gate 4 (Buyer GTM):** Convert lab safety & underwriting interviews into paid `Escrowed Track` audits.

## Slide 11 — Open MIT Kit; Independent Physical Cells
- **Defensibility:** Open MIT referee tooling + sealed physical cells + independent of competing model weights + ISO/IEC 17025 accreditation roadmap.
- **Open Risks:** Unvalidated enterprise Escrowed Track willingness-to-pay, pending vendor RFQ torque/thermal data, physical Stage-1 sensor variance, and upstream `inspect-robots` API changes.

## Slide 12 — Partner & Capital Options
- **Option 1 — Lab Partner (`$0` Capital Ask):** Direct Inspect Robots plugin hook + 1 confidential `I2`/`H2` surrogate spec; physical checkpoint audits follow Stage-1 bench completion.
- **Option 2 — Lean Pilot (`$250k – $500k`):** Gate 1 Stage-1 bench + `240`-trial physical A4 (`$250k`) -> Gate 2 single `P2` UFACTORY 850 + ORCA Touch cell + Season-0 (`$500k`).
- **Option 3 — Pre-Seed (`$1.5M – $3.0M`, 18-month runway):** `$1.5M` funds Stage-1 bench, single `P2` cell, Season-0 baselines, and initial escrow pilot; `$3.0M` adds twin `P1 + P2` cells, dedicated metrology engineering hires, and 3+ paid closed-bank audits.
- **Option 4 — Institutional Seed (`$5.0M+`, 24-month runway):** US/EU labs, HSM escrow ceremonies, insurer underwriting adoption.
