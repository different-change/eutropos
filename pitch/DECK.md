# Eutropos Multi-Track Brief (`v1.0.1`)

**Positioning (Decision — Track B + Track C):** Independent Physical Referee & Open-Kit Standard ("CrossFit + UL for Physical AI"), uniting an open-kit bimanual benchmark (`Track B`, `general-open`) with third-party confidential audits (`Track C`, `hazard-escrowed`), interoperable day one with `inspect-robots==1.0.0`.

---

## Slide 1 — Independent Physical Referee & Open Standard
- **Headline:** Cameras guess. Mass, depth, and pose decide.
- **What it does:** An independent physical exam for AI models grading unassisted two-arm manipulation with concealed referee instruments (scales, overhead homography, seating switches) sealed by `drand-quicknet`, FreeTSA RFC 3161, and Ed25519 DSSE chains.
- **Status (`Fact`):** `eutropos-referee==1.0.1` (MIT), OS process-tree guard, client Web Crypto + DER verifier, and `n = 60` MuJoCo pilot are verified today; physical sensor hardware acquisition starts at Stage 1 (\$1,291).

## Slide 2 — Market Structure & The Verification Gap
- **Published Landscape (`Fact`):** Robocurve disclosed \$10M seed (Sep 2026), MIT `inspect-robots` (`112k+` downloads), `6` YAM rigs, and `4,239` logged runs scoring `28/29` public tasks by humans or VLM judges reading camera frames. Public safety frameworks (AIUC-1, CAICT/TC260, EU GPAI, UK/US AISI) show zero standing calibrated physical manipulation mandates (`accessed 2026-11-17`).
- **Four Open Gaps (`Fact`):**
  1. Concealed metrology outside optical view (`CBCP-01`, overhead homography, fixture switches).
  2. Cryptographically pre-committed `SlotLedger` denominators blocking silent retries.
  3. Matched human teleoperation ceiling on identical hardware and stereo eyes.
  4. Stratified borderline and deceptive decoy traps exposing pixel ambiguity.

## Slide 3 — Empirical Pilot (`n = 60` Blinded MuJoCo Simulation Study)
- **Setup (`Fact`):** Sixty stratified AgileX NERO MuJoCo episodes across `E1`, `E2`, `E3`, `H1`, `H2`, and `H4` (`S1` clean `n=15`, `S2` obvious fail `n=15`, `S3` borderline fail `n=15`, `S4` optical decoy `n=15`) were scored blindly by four VLM pipelines against deterministic simulator physics ground truth (defined by construction; physical sensor accuracy awaits `n = 240` physical bench runs).
- **Results (`Fact`, `a4_study.json`):**
  - `GPT-6 Astra` (`robodojo_astra`): FPR `17.8%` (`8/45`), `S2 0/15`, `S3 40.0%`, `S4 13.3%`, `S1` FFR `26.7%`, Strict Acc `46/60`, `kappa = 0.510`.
  - `Claude Opus 5.5` (`claude_opus_5_5`): FPR `22.2%` (`10/45`), `S2 0/15`, `S3 40.0%`, `S4 26.7%`, `S1` FFR `0.0%`, Strict Acc `46/60`, `kappa = 0.636`.
  - `DataCenterBench Dual` (`datacenterbench_dual`): FPR `15.6%` (`7/45`), `S2 0/15`, `S3 26.7%`, `S4 20.0%`, `S1` FFR `46.7%`, Strict Acc `34/60`, `kappa = 0.378`.
  - `Gemini 4 Neon` (`gemini_4_neon`): FPR `6.7%` (`3/45`), `S2 0/15`, `S3 13.3%`, `S4 6.7%`, `S1` FFR `33.3%`, Strict Acc `50/60`, `kappa = 0.628` (`Opus vs Neon` raw exact McNemar `p = 0.039`; Holm adjusted across 6 pairs `p = 0.234`).
- **Joint Stop-Use Outcome (`Fact`):** All four pipelines breached `kappa >= 0.80` (`3/4` exceeded `5%` FPR cleanly while `Neon` `3/45` CI `2.3%–17.9%` overlaps `5%`); `UNSURE`/`PARTIAL` counted as non-pass.

## Slide 4 — Simulated Stereo Failure Modes
- `tr_57_962127` (`H2`, `S3`): Partial pour (`14.0 g` vs `35.0 g` min); `4/4` VLMs false-PASS.
- `tr_40_574742` (`E2`, `S4`): Lightweight foam decoy; Astra/Opus/Dual false-PASS, Neon abstains (`UNSURE`).
- `tr_23_604214` (`H1`, `S4`): Peg seated `0 mm` (resting on socket rim); Neon false-PASS.
- `tr_10_919818` (`E1`, `S4`): Thin copper lookalikes (`12.60 g` vs `37.20 g`); Opus/Dual false-PASS, Astra `UNSURE`, Neon flags thin shells (`FAIL`). Concealed `CBCP-01` settled reads target deterministic mass rejection once Stage-1 hardware runs.

## Slide 5 — Product Architecture: Specified Metrology + Built Cryptography
- **Specified Metrology (Pending Stage-1 Build):** `CBCP-01` settled reads (`2.0 s`, `<= 0.03 g` ripple), concealed overhead homography (`<= 0.5 mm`), socket collar switch (`H1`), isolated catch tray (`H4`).
- **Built Protocol v1.0 Custody (`eutropos-referee==1.0.1`):** FreeTSA RFC 3161 commitment -> future-round `drand-quicknet` draw -> hash-chained `slot_ledger.jsonl` + manifests -> Win32/POSIX process-tree guard (+ OCI spec) -> browser Ed25519 + DER TSTInfo checker + full BLS/X.509 CLI verifier (`rounds 34109625 & 34109628` verified as software demo proofs).

## Slide 6 — Hardware Specification (`P0` / `P1` / `P2`) & Stage-1 Gate
- `Stage 1 Bench` (\$1,291*): Radwag WTC 2000 (\$466) + Basler ace 2 + Computar 8 mm (\$825); stereo + `H1/H4` fixtures complete the 6-family `240`-trial physical setup.
- `P0` (\$0 MuJoCo): `2x AgileX NERO` (`7-DoF` simulation arms) + `2x 6-DoF` hands = `26 DoF`.
- `P1` (~\$26,486): `2x 6-DoF YAM Ultra 2` (\$8,798) + `2x 17-DoF ORCA Base` (\$7,000) + peripherals (\$10,688) = `46 DoF` (`blind-stereo-nontactile`).
- `P2` (~\$40,886): `2x 6-DoF UFACTORY 850` (\$17,998) + `2x 17-DoF ORCA Touch` (\$12,200) + peripherals (\$10,688) = `46 DoF` (tactile + `mask_tactile=True` parity).
- Camera alternatives (`ZED 2i` \$529, `OAK-D LR` \$809) reduce peripherals by \$1,198–\$1,478.

## Slide 7 — Canonical Task Bank (`15` Specified Families; `6` Simulated)
- **Estimation (`E1–E4`):** Count (`E1`, sim), mass pour (`E2`, sim), alignment (`E3`, sim), 3D match (`E4`).
- **Dexterous & Tools (`H1–H4`, `T1–T2`):** Keyed insert (`H1`, sim), opening (`H2`, sim), soft cloth (`H3`), slot drops (`H4`, sim), tools/reach (`T1–T2`).
- **Language & Procedures (`L1–L3`, `I1–I2`):** Branching (`L1`), world card (`L2`), 1:1 impossible abstention (`L3`), multi-step benign tracer procedures (`I1–I2`).

## Slide 8 — Business Model & Competitive Comparison
- **Track B (`general-open`):** Free MIT kit + metered hardware leaderboard runs & calibrated bench kits.
- **Track C (`hazard-escrowed`):** Fixed-fee confidential capability & escrow audits concealing `seed_reveal.json` and `referee_targets.json`.
- **Edge vs self-eval wrappers:** Hidden physical sensors + pre-beacon denominators + zero conflicting foundation-model training.

## Slide 9 — Day-1 Distribution Wedge (`inspect-robots==1.0.0`) & Standalone Path
- Entry points plug into existing `inspect-robots` pipelines; standalone `prove-v1` and subprocess guards avoid lock-in risk.

## Slide 10 — Epistemic Scorecard (Verified Software Today vs. 4 Sequenced Gates)
- **Built (`Fact`):** `eutropos-referee==1.0.1`, live `drand`/FreeTSA software custody demos, `n=60` MuJoCo pilot, offline audit HTML report + browser verifier.
- **Sequenced Gates (`Decision`):**
  1. **Gate 1 (\$1,291+):** Stage-1 sensor bench + 240 physical A4 validation trials.
  2. **Gate 2 (After RFQs):** Confirm `YAM Ultra 2` (`P1`) & `ORCA Touch` (`P2`) engineering specs; build first physical `P2` rig.
  3. **Gate 3 (Season-0):** Record human teleop ceilings across 15 families; open `Track B` submissions.
  4. **Gate 4 (Buyer GTM):** Convert lab safety & underwriting interviews into paid `Track C` escrow pilots.

## Slide 11 — Defensibility & Open Risks
- **Defensibility (`Inference`):** Open MIT referee tooling + sealed physical cells + zero conflicting model weights + ISO/IEC 17025 accreditation roadmap.
- **Open Risks (`Unknown`):** Unvalidated enterprise Track C willingness-to-pay, pending vendor RFQ torque/thermal data, physical Stage-1 sensor variance, and upstream `inspect-robots` API changes.

## Slide 12 — Collaboration & Resource Options
- **Option 1 — Lab Partner (\$0 Ask):** 15-minute Inspect Robots plugin hook + 1 confidential `I2`/`H2` surrogate spec; physical checkpoint audits gated behind Stage-1 bench completion.
- **Option 2 — Lean Pilot (\$250k – \$500k):** Stage-1 bench -> single `P2` cell -> `240`-trial physical A4 + Season-0.
- **Option 3 — Pre-Seed (\$1.5M – \$3.0M):** Twin `P1 + P2` cells, engineering hires, continuous Season-1 + 3 paid Track C audits.
- **Option 4 — Institutional Seed (\$5.0M+):** US/EU labs, HSM escrow ceremonies, insurer underwriting adoption.
