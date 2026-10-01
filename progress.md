# ReArch — Progress

Living log. Newest entries first. Update after every task or phase.
Plan reference: `BUILD_PLAN.md`. Rules: `CLAUDE.md`. Convention: the user runs all git commands; one commit per phase.

## Status overview

| Phase | Name | Status |
|---|---|---|
| 0 | Setup and target choice | Done, committed |
| 1 | Fixture with known answers | Done, committed |
| 2 | Analyzer | Done, committed |
| 2.5 | Review decisions (controller fan-in, tiers, coverage, broken refs, dependency snapshot) | Built and verified; awaiting commit |
| 3 | Scoring and strategies (`engine/`) | Built and verified; awaiting user review and commit |
| 4 | Roadmap | Not started |
| 5 | API | Not started |
| 6 | Web UI | Not started |
| 7 | LLM layer | Not started |
| 8 | Polish and deploy | Not started |

## Log

### 2026-10-01 — Phase 2.5 + Phase 3
**Phase 2.5 (analyzer)**
- `controller_fan_in`: parses `controller.xml` `<event type="java">`; `used = fan_in + service_fan_in + controller_fan_in > 0`.
  OFBiz: 97 Java events (hand-checked against grep), unused classes 31 → 22 of 132.
- God-class tiers: large (400 LOC / complexity > 50) and extreme (1500 / > 200), both in config. OFBiz: 36 large, 10 extreme.
  Per-class percentiles for LOC, complexity, fan-in, fan-out (share of classes strictly lower).
- Analysis coverage per module (Java share of implemented service definitions, Groovy file count) → confidence high/medium/low
  (thresholds in config). All five OFBiz modules come out *low* (Java share 0.11–0.28).
- Broken references (`method_missing`, `class_missing`; `out_of_scope` is not broken) as findings with file and line.
  OFBiz: `creditOrderPaymentPreference`, `updateProductQuickAdminShipping`, controller `addseperator`.
- Dependency snapshot: `scripts/snapshot_deps.py` resolved 125 of 128 coordinates from Maven Central into the committed
  `config/dependency_snapshot.yaml` (as of 2026-10-01); `config/dependency_renames.yaml` holds the hand-curated javax→jakarta
  renames. Analyzer is offline. OFBiz: 95 of 99 checked, 26 outdated. Calendar versions are treated as unchecked.
- Fixture grew: `controller.xml`, dangling service definitions (all three reference outcomes), non-Java engines, a 1,592-LOC
  extreme `OrderServices`. 20 classes, 2,825 LOC. The oracle generator is now committed: `fixtures/generate_expected.py`.
  (The earlier scratch copy was lost when the machine's temp directory was reset, which is why it is now in the repo.)

**Phase 3 (engine)**
- `engine/`: `config.py`, `schema.py`, `facts.py`, `health.py` (health + hotspots), `criticality.py`, `strategies.py`,
  `scoring.py`, `sensitivity.py`, `recommend.py`, CLI. `make recommend NAME=<analysis> [PROFILE=...] [OVERRIDES=...]`.
- Every number carries a breakdown; 27 engine tests rebuild each one exactly. Total 194 tests; `make test`, `make lint` pass.
  A test caught a real exactness bug (a contribution computed from unrounded goodness) — fixed.
- Two modelling mistakes found and fixed during the work: (1) risk was multiplicative and saturated at 100; now
  `base × (1 + exposure)` with exposure a 0–1 weighted mean. (2) Scoring min–max scaled each criterion within a module,
  which erased module differences and made the daily rate irrelevant; now absolute scales (cost and duration against
  ceilings, risk and value on 0–100).
- Hand check: OFBiz `order` / refactor recomputed from raw inputs = 2,080.71 days, ¥166.46M, 17.3 months (matches).

### Phase 3 result on OFBiz and where it looks unconvincing
Estate (selected profile `balanced`): rehost for every module, ¥19.3M, 241 days, 6.0 months (ILLUSTRATIVE assumptions).
The `long_term_value` preset rearchitects every module: ¥900M, 11,251 days, 70 months. The other three presets equal `balanced`.
1. **Presets collapse to two answers.** Cost, risk and speed all favour the least ambitious option, so rehost wins unless the
   long-term-value weight dominates (then rearchitect). Replatform and refactor never win; replatform is the runner-up in all
   cost-leaning cases (often a close call). Flip points: raising the long-term-value weight from 0.25 to ~0.49–0.53 flips
   `balanced` to replatform in 4 of 5 modules.
2. **Every module gets the same answer** under a given preset; module differences change margins, not choices.
3. **The database-coupling health component is saturated (1.0) in all five modules** (15.5–30 calls/KLOC vs a cap of 15), so it
   discriminates nothing. Health scores cluster at 30–45 with the same three drivers everywhere.
4. **Confidence is *low* everywhere**, so the 1.35 buffer is uniform and carries no information. Excluding `entity-auto`
   (generated CRUD) from the denominator would give Java shares of 0.54 order, 0.38 accounting, 0.27 party, 0.24 product.
5. **Criticality:** `accounting` is proposed as 2 because it is mostly a caller (Java cross-module fan-in 0); a finance owner
   would say 3. `shipment` is 1. Both are exactly what `criticality_overrides.yaml` is for.
6. **Granularity:** one strategy per module is too coarse; real work packages are the hotspot clusters (the shopping-cart
   classes occupy the top of the hotspot list). Rearchitecting a 30K-LOC module at ¥396M in one step is not a plan.
7. The daily rate never flips a recommendation within ×0.1–×10; it changes totals only.
8. `shipment` inherits `product`'s coverage because both live in one OFBiz component.
9. Test evidence undercounts OFBiz (`testdef/*.xml` suites are not counted), so test gaps are overstated.

## Open decisions (for the user)
1. **Presets and modelling (see list above).** Options: merge cost and speed into one criterion or add a minimum-value
   constraint; make value depend on criticality; score hotspot clusters instead of whole modules. Not changed without a decision.
2. **Coverage denominator:** exclude `entity-auto` so confidence discriminates between modules (config change only).
3. **Health calibration:** raise `db_calls_per_kloc_cap` for OFBiz-scale code or use a percentile across modules.
4. **Criticality overrides for OFBiz** (accounting 3?) need the client's confirmation; none are committed.

## Known gaps / risks
- **Logic outside Java** (main blind spot): in the four OFBiz components only 360 of 2,271 service definitions are Java;
  444 are Groovy, 215 XML minilang, 1,194 entity-auto. Mitigations: service/controller mappings give inbound counts; Groovy
  is counted and listed as `not_analyzed`; low coverage raises effort and risk through the buffer. Groovy/XML content itself is not analysed.
- Fan-in/out only count classes inside the analysed scope.
- Dependency "major behind" is coarse; 4 of 99 OFBiz coordinates are unchecked; results are as of the snapshot date.
- Everything in `engine:` is illustrative (labelled in config and echoed into every output). No market data is claimed.
- OFBiz `testdef/*.xml` tests are not counted; test presence is not coverage.
- `getNextSeqId` counts as entity-engine access by design (70 of 1,392 OFBiz instances).
