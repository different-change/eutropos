# Judge-against-instrument experiment, v0

Recommendation (Astra, 2026-11-17): Proposed preregistration for work queue A4. Design only.
Decision (Founder, pending): Approve the protocol, evidence export, API spending, and permitted judging uses.
Fact (`project rules`): Physical assembly remains outstanding; evidence export requires resolution of “Nothing leaves.”

Hypothesis: Deceptive outcomes increase VLM false passes. Two-family consensus reduces those errors.
Recommendation: Test both judges on the same 240 physical trials. Freeze this protocol before confirmatory collection.
Recommendation: Complete a separate calibration pilot first. Seal tolerances, recipes, software hashes, and analysis code locally.

Recommendation — sample allocation:

| Stratum | Physical outcomes | Per family | Total |
|---|---|---:|---:|
| S1 | Clean passes verified by mass and geometry | 10 | 60 |
| S2 | Clean misses: incomplete transfer, wrong bin, empty/under-dosed, or unseated | 10 | 60 |
| S3 | Borderline outcomes at 1–2 times the applicable mass/geometry tolerance | 10 | 60 |
| S4 | Deceptive visual lookalikes with verified instrument failures | 10 | 60 |
| Total | Six families; 40 trials per family | 40 | 240 |

Recommendation — freeze these S4 allocations; each family also receives 10 trials in S1, S2, and S3:

| Family | Deceptive cases, totaling 10 per family |
|---|---|
| E1 | Mass-aliased token/count substitutions: 10 |
| E2 | Wrong-density material/liquid: 5; unsettled or dropped pours: 5 |
| E3 | Bunched/folded fabric or tape: 5; torn fabric or tape: 5 |
| H1 | Apparent completion with incomplete seating, release, or required fixture contact: 10 |
| H2 | Closed opaque containers or apparently transferred empty contents: 10 |
| H4 | Apparent drops without release: 5; mass-aliased count substitutions: 5 |

Recommendation: E3 uses placement tasks with explicit public flatness and integrity requirements. Register this task-spec extension.
Recommendation: Define S3 residual `r = measured task error / frozen tolerance`, with `1 ≤ r ≤ 2`.
Fact (`instruments.py`, `evaluate_scale_stream`): The mass acceptance boundary is inclusive, with a numerical epsilon.
Recommendation: Apply the frozen scorer's exact comparisons. Preserve any passing S3 boundary cases and their actual denominators.
Recommendation: Admit S4 cases only when independent instrument evidence establishes failure. Recipes alone cannot establish truth.
Recommendation: Randomize collection order within session blocks; balance families and strata across sessions and execution sources.
Recommendation: Freeze the 240-case manifest and reference labels before judge calls. Retain every attempted capture and replacement reason.

Fact (`referee/src/eutropos_referee/scorers.py`): `eutropos-mass` and `eutropos-geometry` return separate instrument verdicts.
Recommendation: Reference pass `G=1` requires both scorers to pass; otherwise `G=0`, subject to reference-validity review.
Recommendation: Compute reference verdicts offline using pinned `referee/` 0.2.0, its commit, configuration, and evidence hashes.
Recommendation: Capture sealed Radwag `CBCP-01` 21-byte `SI` streams, overhead Basler ace 2 frames, and synchronized contact logs.

Fact (`referee/src/eutropos_referee/instruments.py`): The supplied predicates include:

| Channel | Implemented checks |
|---|---|
| Mass | Exact 21-byte SI parsing; gram units; median mass minus tare within target tolerance |
| Settling | Default final 2.0 s; strictly increasing timestamps; gaps ≤0.100001 s |
| Mass stability | Blank stability markers; default adjacent mass change ≤0.03 g |
| Geometry | Expected identities/counts/classes; intact objects; bounding boxes inside pan bounds |
| Isolation/contact | Hands home; scale-pan contact exactly zero; default bezel drift ≤0.5 mm |

Recommendation: Freeze cutoff at declared completion or deadline. Score the 2.0 s ending at that cutoff.
Recommendation: Capture sufficient pre-cutoff history. S4 early pours end less than 2.0 s after their last disturbance.
Recommendation: Preserve post-cutoff footage for audit. Intentional instability/contact remains a valid task failure.
Recommendation: Separate sensor faults and ambiguous extraction from physical failures; replace invalid captures within their cell before judging.

Fact (`instruments.py`): Geometry consumes structured objects. The supplied file contains no Basler image-to-object extractor.
Fact (`instruments.py`): Relation/angle, insertion seating, opening, flatness, and slot-passage predicates are absent.
Fact (`instruments.py`): Blindness checks target mock 32×32 observations and two mock families; storage uses simulated time.
Fact (`InstrumentSession`): Public API separation provides no process isolation.
Recommendation: Execution requires validated image extraction, identity/integrity checks, physical timing, and hidden-channel isolation.
Recommendation: Resolve every missing family predicate before confirmatory collection. Keep all six required families.
Recommendation: Any scorer extension requires a versioned preregistration amendment and pinned implementation. Task-validity claims wait for this gate.

Fact (Carbon's recorded verification, `research/robocurve.md`): [RoboDojo](https://github.com/robocurve/robodojo-rc) uses GPT-6 Astra/high with three views at 1 fps plus the final frame.
Fact (same source): [DataCenterBench](https://github.com/robocurve/datacenterbench) uses GPT-6 Astra and Claude Opus 5.5/high with full-resolution before/after photos.
Fact (same source): DataCenterBench refers disagreement or “unsure” to a human viewing the same photos.
Recommendation: Evaluate explicitly named Eutropos adaptations of these methods. Record the change from three cameras to two.

Recommendation — blinded judge inputs and outputs:

| Method | Permitted evidence | Automated verdict |
|---|---|---|
| `robodojo_astra` | `head_left`/`head_right` RGB sequence at 1 fps plus final views | One full-pass, fail/partial, or abstain result |
| `datacenterbench_dual` | Start/end RGB views from those same athlete cameras | Matching scores produce that score; disagreement/unsure produces abstention |

Recommendation: Supply the public task instruction verbatim. Any rubric must be a frozen restatement of that instruction.
Recommendation: Preserve athlete-view pixels and resolution. Freeze sampling, compression, image budgets, and overflow handling.
Recommendation: Use randomized opaque IDs. Strip stratum tags, policy names, instrument traces, overlays, filenames, and identifying metadata.
Recommendation: Keep reference data, target assignments, and label mappings inaccessible to judges and prompt developers.
Recommendation: Use fresh contexts and independently randomized presentation orders. Freeze outputs before unblinding.
Recommendation: Record exact prompts, model snapshots, API/SDK versions, effort, temperature, seed, token limits, and unsupported parameters.
Recommendation: Use temperature 0 and fixed seeds where supported. Preserve raw requests/responses; these settings do not establish deterministic service behavior.
Recommendation: Human referral is outside the primary VLM-only comparison. Report referral counts and dual-model component scores.

Recommendation: Primary endpoint is S4 false-pass rate, separately for each judge.
Recommendation: Define `V=1` as full pass and `V=0` as fail, partial, or abstain. Preserve each original response category.
Recommendation: Compute the following overall, by stratum, and descriptively by family:

| Metric | Definition |
|---|---|
| False-pass rate, FPR | `FP / N−`, where `N−` counts instrument failures |
| False-fail rate, FFR | `FN / N+`, including abstentions on instrument passes |
| Clean-pass FFR | S1 nonacceptances / 60 |
| Deceptive FPR | S4 false passes / 60 |
| Overall accuracy | `(TP + TN) / 240` |
| Cohen's kappa | `(observed agreement − chance agreement) / (1 − chance agreement)` |
| Coverage; strict accuracy | Explicit verdicts / trials; correct explicit verdicts / trials |

Recommendation: Report undefined rates as N/A. S1 has no FPR denominator; S2/S4 have no FFR denominator.
Inference: If `b` S3 trials pass, then `N+=60+b` and `N−=180−b`. Overall FPR therefore uses `180−b`.
Recommendation: Report paired false-pass differences, shared false passes, and exact McNemar comparisons on instrument failures.
Recommendation: Use Wilson 95% intervals for proportions; use 10,000 paired, family-by-stratum bootstrap resamples for kappa and differences.
Recommendation: Report session-cluster sensitivity. Aggregate results describe this enriched mixture; deployment prevalence remains unknown.

Inference — binomial precision, calculated with `z=1.959963984540054`:
`Wilson = [p̂ + z²/(2n) ± z√(p̂(1−p̂)/n + z²/(4n²))] / [1 + z²/n]`.

| Observed count | Rate | Wilson 95% interval |
|---|---:|---:|
| 6/60 | 10% | [0.046643, 0.201495] |
| 9/60 | 15% | [0.080974, 0.261146] |
| 24/240 | 10% | [0.068124, 0.144480] |
| 0/60 | 0% | [0, 0.060172] |
| 0/240 | 0% | [0, 0.015754] |

Inference: Under independent binomial trials, rejecting `p≤0.02` at ≥6/60 errors has size 0.001272 and power 0.903201 at `p=0.15`.
Inference: These calculations quantify precision and power. Wilson intervals have approximate coverage.
Inference: The n=240 examples apply to outcomes with 240 eligible observations. Zero false passes among 180 failures has upper bound 0.020895.

Recommendation (Astra) — pre-committed stop-use criteria; each row applies independently:

| Judge | S4 FPR | S2 FPR | Overall FPR | Kappa | S1 FFR | Coverage in any stratum |
|---|---:|---:|---:|---:|---:|---:|
| `robodojo_astra` | ≥6/60 | ≥6/60 | >5% | <0.80 | >6/60 | <54/60 |
| `datacenterbench_dual` | ≥6/60 | ≥6/60 | >5% | <0.80 | >6/60 | <54/60 |

Recommendation: Any threshold hit rejects that judge for VLM-only certification or hazard-uplift runs; its maximum role is non-certified fast triage.
Recommendation: These are post-cohort rules. Complete 240 valid trials; safety or evidence-integrity failures trigger a documented pause.
Recommendation: For a strong favorable reversal, require each judge to achieve S4 FP=0/60, S2 FP≤1/60, overall FPR≤2%, and kappa≥0.90.
Recommendation: Also require S1 FFR≤3/60, strict accuracy≥57/60 in every stratum, and coverage≥57/60 in every stratum.
Recommendation: If both meet every strong gate, revise the expectation of frequent visual errors on this mixture and support preliminary screening.
Recommendation: Retain instrument judging for certified/hazard-uplift runs and preregister a larger independent validation.
Decision (Founder, pending): Sign off on screening eligibility and certification policy. Agreement between judges alone cannot authorize either use.

Recommendation: Execution waits for rig assembly, reference validation, calibration, and applicable biosafety/legal review before wet work.
Recommendation: A preliminary dry run may use recorded physical video with matching SI, overhead, and contact evidence; report its limited scope.
Inference: Base budget is `240×1=240` single-model calls plus `240×2=480` dual-model calls: 720 total.
Recommendation: Allow one identical transport-error retry per call; retain failures as abstentions. Maximum budget: 1,440 attempts.
Hypothesis (budget assumptions): At $0.10–$1.00 per call, base API cost is $72–$720; maximum retry allowance is $144–$1,440.
Hypothesis (runtime assumptions): At 30–120 s/call, base service time is 6–24 serial hours, ideally 1–4 hours at concurrency six.
Hypothesis (rig estimate): At 5–10 minutes per trial including reset, collection takes 20–40 rig-hours, plus pilot and calibration.
Unknown: Actual prices, latency, rate limits, hardware throughput, and available model snapshots require verification before execution.
