# Eutropos Pareto-Frontier Architecture: Candidate v1

Status: Prepared by Carbon on 2026-11-18 under project directives to hold hardware purchases, unblock OpenAI (`gpt-6-astra`) and Anthropic (`claude-opus-5-5`) via local Ultra subscriptions, unblock outreach drafts, and build a Pareto-frontier engineering solution without waiting on undecided hardware or partner calls.

## 1. Decisions and Unblocked Scope (2026-11-18)

| Decision / Boundary | Status | Effect | Source |
|---|---|---|---|
| Hardware purchases | Decision (Founder, 2026-11-18) | Hold purchases now; run outreach RFQs for missing vendor specs first | project directive (`open vendor RFQs`) |
| Anthropic & OpenAI APIs | Decision (Founder, 2026-11-18) | Unblocked via local Ultra subscriptions (`claude-opus-5-5`, `gpt-6-astra`) with zero personal/folder identity leaked in prompts or temp paths | `project rules` privacy boundary preserved |
| External outreach | Decision (Founder, 2026-11-18) | Draft complete pack in `external inquiries`; maintainers review and send (`project rules`) | `vendor inquiry index` |
| Software & simulation queue | Decision (Founder, 2026-11-18) | Unblocked: build subprocess isolation, pixel-to-object extractors, 5 missing predicates, crypto drand/RFC 3161 verifiers, 15-family generators, `A4` harness, bimanual MuJoCo bench, and live 24-trial `A4` pilot | `referee/` `0.3.0`; `spec/JUDGE-EXPERIMENT-v0.md` |
| Strategy & hardware selection | Pareto-frontier solution | Support non-dominated profiles `P0`/`P1`/`P2` cleanly via explicit runtime capabilities (`mask_tactile`, dual plugin + isolated CLI) | This spec |

## 2. Dominance Elimination and the Pareto Frontier

Fact (`research/hardware.md`): Among evaluated hands and arms, candidates drop below the Pareto frontier along verified engineering, licensing, or duty axes:

- **Excluded / non-v1 reference:** `Wuji Hand 2.2 (Beta)` (`$29,200` pair, non-tactile Beta manual warns against continuous high-load tests, earlier throttling `~40 min`); `Allegro V5 Sense` (`$28,600` pair, 4 fingers miss 5-finger opposable human baseline, total BOM B `~$59,786` dominated by `P2`); `Aero Hand Open` (`CC BY-NC-SA 4.0`, `shop.tetheria.ai` closed, quote-only); standard `YAM 6-DoF` (`2.0 kg` nominal leaves tight margin for `~1.2 kg` hands); parallel grippers (fail T's dexterous thumb rule).

What survives on the cost / open-licence / physical-precision frontier are three non-dominated profiles (`P0`, `P1`, `P2`):

| Profile ID | Role & configuration | Listed subtotal (arms + hands) | Total rig basis (`research/hardware.md`) | Licence boundary | Divisions supported | Open vendor gate (`open vendor RFQs`) |
|---|---|---|---|---|---|---|
| `P0` (`sim-bimanual-nero`) | Local 3D MuJoCo digital twin (`2 × AgileX NERO 7-DoF + 2 × 6-DoF 5-finger hands = 26D`) + stereo head + hidden overhead RGB + simulated `CBCP-01` | `$0` | `$0` (existing workstation) | `MIT` (`inspect-robots-agilex-nero`, `eutropos-referee`) | `blind-stereo-nontactile` | Software simulation parity only; zero physical dynamics proof |
| `P1` (`open-commercial-c1`) | `2 × I2RT YAM Ultra 2` (`$8,798`) + `2 × ORCA v2.1 Base` (`from $7,000` listed) + BOM C peripherals (`~$10,688`) | `from $15,798` | `from ~$26,486` (`-$1,198` w/ `OAK-D Long Range`, `-$1,478` w/ `ZED 2i`) | `ORCA` CAD `CC BY 4.0` + `orca_core` `MIT`; closed arm controller; zero proprietary tactile module | `blind-stereo-nontactile` | I2RT RFQ B (repeatability, full-reach payload, flange) + ORCA RFQ A (`v2.1` hand mass) |
| `P2` (`precision-tactile-c2`) | `2 × UFACTORY 850` (`$17,998`, `±0.02 mm`, `5 kg`, `DIN ISO 9409-1-50-4-M6`) + `2 × ORCA v2.1 Touch` (`from $12,200`) + BOM C peripherals (`~$10,688`) | `from $30,198` | `from ~$40,886` (`-$1,198` w/ `OAK-D Long Range`, `-$1,478` w/ `ZED 2i`) | `ORCA` mechanical CAD `CC BY 4.0` + `MIT` core; proprietary `Touch` tactile module; closed arm | **`blind-stereo-tactile` AND `blind-stereo-nontactile` (via `mask_tactile=True`)** | ORCA RFQ A (`Touch` SDK/licence, `v2.1` mass, ISO adapter) + UFactory RFQ D1 (dual sync Hz) |

Inference (`mask_tactile` dominance insight): Selecting `P2` later lets one physical rig evaluate BOTH tactile-enabled models AND blind-stereo non-tactile ablations (`mask_tactile=True` zeroes/removes tactile state channels prior to compatibility checks and `verify_athlete_blindness`), eliminating the need to maintain two separate benches. Selecting `P1` remains cheaper by `$14,400` if T rules proprietary tactile sensors out of scope and I2RT answers RFQ B cleanly. If T later unblocks sensor spending before full arm/hand orders, the minimal physical step remains the `$1,291` referee bench pair (`Radwag WTC 2000` `$466` + `Basler ace 2` & lens `$825`, plus existing/chosen head stereo) used for human-hand `A4` trials.

## 3. Dual-Mode Partner & Protocol Architecture

To prevent Robocurve's strategic decision (`landscape review`, `ecosystem technical inquiry`) from blocking implementation:

1. **Upstream-ready `inspect-robots==1.0.0` plugin surface:** `eutropos-referee` exposes zero-patch `inspect_robots` entry points (`referee`, `eutropos-mass`, `eutropos-geometry`, `eutropos-bench`, `eutropos-e1-mock`, `eutropos-e3-mock`) alongside an explicit `validate_dexterous_semantics` adapter check closing the `14D` gripper-vs-finger blind spot (`A3`).
2. **Standalone isolated runner & verifier (`eutropos-referee` `1.0.0`):** Wraps policies in an OS-isolated worker subprocess (`isolation.py`) with sanitized workspace/environment and verifies bundles offline (`verifier.py`), with verified `py-ecc` BLS12-381 `drand` and `asn1crypto` + `cryptography` RFC 3161 TSA verification paths (`beacon.py`). Neither path depends on upstream changes to `inspect-robots`.
