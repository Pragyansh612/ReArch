# Methodology

How every number in ReArch is produced, in plain English. Updated after each phase.
Rule zero: Python computes every fact and every number; an LLM may only explain facts it is given.
All thresholds, rates and weights live in `config/assumptions.yaml`; the code contains none.

> **Illustrative assumptions.** Everything in Phase 3 (day rates, days per KLOC, multipliers, risk and value
> parameters, weights, ceilings) is ILLUSTRATIVE: chosen to make the model behave sensibly and be explainable, not
> taken from market data or a client. Each is labelled in the config with what a real engagement would calibrate it
> against. Every yen figure must be shown with these assumptions next to it.

## Phase 0 — Target selection
Figures in `docs/target.md` were counted directly from the cloned repositories (file counts, line counts,
`@Test` occurrences). Nothing is estimated.

---

## Phase 2 / 2.5 — The analyzer (facts only)

**What it does.** Reads a repository (optionally only some directories, the "scope") and writes one JSON document
(`out/<name>.json`; contract in `analyzer/schema.py`, JSON Schema in `docs/analysis-schema.json`). It parses Java with
tree-sitter, so comments, string literals and Javadoc are never mistaken for code. It never runs or compiles the code.

**What is analysed.** `src/main/java` under the scope. Tests, Groovy and XML are inventoried only. A *module* is the
first package segment after a configured root (`org.apache.ofbiz.order.order.X` → module `order`). A *class* is the
first top-level type of a `.java` file.

### Lines of code (`loc`)
- **Measures:** size. **How:** lines of a file that contain at least one code token. Blank and comment-only lines
  (line, block, Javadoc) are excluded; `package` and `import` lines are included. This is the definition `cloc` uses,
  so it can be checked independently.
- **Limits:** size, not quality. Long license headers distort raw file length (OFBiz `OrderServices.java`: 7,516
  physical lines, 6,212 code lines).

### Fan-out, fan-in (Java)
- **Measures:** coupling. Fan-out = distinct *other analysed* classes a class references; fan-in = how many analysed
  classes reference it.
- **How:** a class is referenced when its name appears as an identifier in code (not in a comment, string or import
  line) and resolves through an explicit import, the same package, or a wildcard import. Self-references are ignored; a
  class counts once however often it is used.
- **Limits:** only classes inside the analysed scope count, so references to framework classes (OFBiz `framework/`, JDK,
  libraries) add nothing. Reflection and string-based wiring are invisible.

### Service fan-in, controller fan-in and `used`
- **Measures:** inbound use that Java code cannot show. OFBiz invokes business logic by name: through
  `servicedef/*.xml` (`OrderServices` has Java fan-in 0 but 77 service definitions point at it) and through web
  `controller.xml` request maps (`ShoppingCartEvents` has 37 controller events).
- **How:** `service_fan_in` = `<service engine="java" location="…" invoke="…">` entries naming the class.
  `controller_fan_in` = `<event type="java" path="…" invoke="…">` entries naming the class. A reference counts toward its
  class even if the method is missing. Service-type and Groovy events are counted by type but add nothing to a class.
  A class is **used** when `fan_in + service_fan_in + controller_fan_in > 0`.
- **Limits:** other inbound paths (scheduled jobs, ECA rules, reflection, Groovy callers) are not counted, so
  `used=false` means "no inbound reference found", not "dead code".

### Complexity and band
- **Measures:** how many decisions a class contains (an approximation of cyclomatic complexity).
- **How:** method/constructor bodies plus decision points: `if` (an `else if` is another `if`), `for`, enhanced `for`,
  `while`, `do`, `case`, `catch`, `?:`, `&&`, `||`; `else` and `default` do not count. Summed over the whole class.
  Band: low ≤ 15, medium 16–50, high > 50 (config).
- **Limits:** a class-level sum, not per method, so many trivial methods score like a few tangled ones.

### God-class tiers
- **Large:** `loc ≥ 400` and `complexity > 50`. **Extreme:** `loc ≥ 1500` and `complexity > 200` (also large). Thresholds
  are config. On OFBiz: 36 large and 10 extreme of 132 classes. The original single tier flagged 46 (35%) and did not
  separate "big" from "worst"; the extreme tier does.
- Boundary tests on the fixture: `StatementFormatter` (399 LOC, complexity 50) is not flagged, `LedgerReconciler`
  (400, 51) is large only, `OrderServices` (1,592, 467) is extreme.

### Percentiles within the analysed estate
- For LOC, complexity, fan-in and fan-out each class gets a percentile: the share (0–100) of analysed classes with a
  **strictly lower** value. The biggest class is near 100; a class with value 0 stays at 0 (ties do not inflate it).
- **Limit:** relative to the analysed scope only; a different scope changes every percentile.

### Database coupling
- **Measures:** business logic that talks to the database itself. **How:** one instance per method call matching a
  configured pattern, with file and line. `jdbc`: `DriverManager.getConnection`, `.prepareStatement`, `.createStatement`.
  `entity_engine`: `EntityQuery.use` and `delegator.<makeValue|create|store|findOne|findList|findByAnd|findAll|
  removeValue|removeByAnd|getNextSeqId>`. The entity-engine API classes themselves are ignored.
- **Limits:** call sites, not tables or transactions. Name-based: a delegator held under another variable name is missed;
  MyBatis/Hibernate mappers and SQL in XML are not seen (JPetStore shows 0). `getNextSeqId` counts as database access.

### Legacy markers and namespace mix
- **How:** import statements. `javax.<family>` for families that moved to Jakarta EE (list in config; JDK packages like
  `javax.sql` are not markers), `jakarta.*`, and legacy frameworks (Struts). A module with both javax and jakarta imports
  is `namespace_mix`. **Limit:** imports only.

### Test presence
- Three kinds of evidence, reported separately per module: **Java** (`test_classes`, `test_method_count` = `@Test` methods
  under `src/test/java` in the matching package), **Groovy** (`groovy_test_files`: scripts under `src/test/groovy` whose
  `package` line matches) and **testdef** (`testdef_suite_files`, `testdef_test_cases`: OFBiz `testdef/*.xml` suites).
  A testdef `<test-case>` counts only if it runs something: a case holding only `entity-xml` data loads is not a test.
  A case is attributed to the module of its `class-name` package; a case without one goes to every module of the file's
  component. `has_tests` is true when any kind is present.
- **Limits:** presence, not coverage or quality. Groovy tests and testdef cases overlap (a testdef case often runs a Groovy
  test class), so the engine takes the larger of the two, never their sum.

### Dependencies (pom.xml and gradle/libs.versions.toml)
- **How:** declared coordinates and versions are read (Maven `${property}` resolved; Gradle `version.ref`). Each is
  compared with `config/dependency_snapshot.yaml`: the latest **stable** version per coordinate on Maven Central,
  fetched once by `scripts/snapshot_deps.py` and committed with its date (`as_of`). The analyzer never uses the network.
  A dependency is **outdated** when its declared major is lower than the snapshot's latest major, or when the coordinate
  has been renamed (javax.* → jakarta.*, listed by hand in `config/dependency_renames.yaml`).
- **Stable** = not alpha/beta/rc/milestone/snapshot/preview/dev/ea/cr; **latest** = highest by numeric version parts.
- **Limits:** "major behind" is coarse (a library can be badly outdated within one major). Calendar versions
  (e.g. `20240325.1`) are not majors and are reported unchecked. Coordinates missing from the snapshot or without stable
  versions are unchecked (OFBiz: 95 of 99 checked, 26 outdated). Results are as of the snapshot date; re-run the script
  to refresh. Transitive dependencies are not read.

### Service and controller mappings, broken references
- Each `<service>` (in a `<services>` file) and each `<event type="java">` (in a `<site-conf>` controller) is listed with
  its file and line. Java ones are checked against the parsed classes: `ok`, `method_missing` (class exists, method does
  not), `class_missing` (class not found although its module was analysed) or `out_of_scope` (its module was not
  analysed, so nothing can be said). `method_missing` and `class_missing` become `broken_reference` findings with the
  file and line as evidence. OFBiz: 2 dangling service definitions and 1 dangling controller request
  (`addseperator` → a non-existent `addSeparator`).
- **Limit:** only the Java engine/handler is checked; Groovy, minilang and `entity-auto` definitions are not.

### Analysis coverage and confidence (per module)
- **Measures:** how much of a module's logic the analyzer can see. A module belongs to the component directory holding
  most of its classes; coverage is computed from that component's `servicedef/*.xml`.
- **How:** `java_share` = Java service definitions ÷ implemented service definitions. Engines that implement no custom
  logic are excluded from the denominator: `interface`, `group` and `entity-auto`. `groovy` and `simple` (XML minilang)
  count as not analysed. Confidence: **high** ≥ 0.60, **medium** ≥ 0.30, otherwise **low** (config). With no service
  definitions, confidence is high if there is no Groovy logic, medium if there is. The Groovy file count (outside tests)
  and the `entity-auto` count are still reported.
- **Why `entity-auto` is excluded (Phase 3.5):** it is generated create/update/delete for an entity, declarative and
  without hidden business logic. Counting it as "not analysed" made every OFBiz module look equally opaque (all *low*), so
  confidence carried no information. Excluded, OFBiz gives Java shares of 0.54 (order), 0.38 (accounting), 0.27 (party),
  0.24 (product, shipment): confidence now discriminates.
- **Limits:** a module inherits its component's figure (OFBiz `shipment` lives in the product component and gets
  product's).

### Cycles
- Strongly connected components (Tarjan) of the class graph and of the module graph (a module edge = at least one
  class-level reference). Only components with more than one member are reported.

### Cross-check (independent of the analyzer code)
`scripts/crosscheck.py` (`make crosscheck`) compares output with `cloc` (LOC per file) and plain `grep` (database calls).

| Target | LOC: analyzer vs cloc | DB calls: analyzer vs grep |
|---|---|---|
| Fixture (20 files) | 2,825 vs 2,825, 0 files differ | JDBC 5 vs 6; entity 106 vs 110 |
| OFBiz subset (132 files) | 71,940 vs 71,940, 0 files differ | JDBC 0 vs 0; entity 1,392 vs 1,392 lines |

Every difference is explained. Fixture grep-only: a string literal and a Javadoc line in `PaymentCalculator.java`
(deliberate traps) and two calls inside the ignored stub class `EntityQuery.java`. OFBiz grep-only: `InvoiceServices.java:261`,
a `//` comment containing `delegator.create(`; analyzer-only: `ImportProductServices.java:144`, a call split across lines
that line-based grep cannot see. Hand checks on OFBiz: services pointing at `OrderServices` by grep = 77 = analyzer;
files mentioning `ProductWorker` = 22 = analyzer fan-in; `<event type="java">` lines = 97 = analyzer; `ShoppingCartEvents`
references = 37; Groovy files in accounting = 53; service definitions in accounting = 705.

The fixture's expected values are produced by `fixtures/generate_expected.py`, which shares no code with the analyzer.

---

## Phase 3 / 3.5 / 3.6 — Scoring and strategies (`engine/`)

Input: the analyzer JSON and the client scenario. Output: `out/<name>.recommendation.json` (contract `engine/schema.py`,
JSON Schema `docs/recommendation-schema.json`). Every number is stored with the breakdown that reconstructs it, and the
tests rebuild each one exactly (for example `health = round(100 − Σ contributions, 4)`, `tco = migration + Σ run +
Σ maintenance`).

### What changed in Phase 3.5, and why (the modelling justification for each change)

| Change | Justification |
|---|---|
| Client scenario file (`config/client_scenario.yaml`) | A strategy is only "right" relative to a client's goals and limits. Constraints decide what is feasible; objectives decide what counts as value; the client's own priorities become a scoring profile; criticality is a client judgment, so overrides live here with a written reason. The client is fictional and every number illustrative. |
| TCO over the planning horizon, with `retain` as the baseline | Migration cost alone ignores what the client keeps paying. "Is it worth it?" can only be answered against doing nothing, so `retain` is always an option and the baseline for savings, payback and NPV. |
| Cost criterion = TCO scored against the retain TCO (`1 − tco ÷ (3 × retain tco)`) | Compares each option with its own do-nothing alternative, so a small package and a huge one are judged on the same footing (the earlier fixed ¥200M ceiling made every small package look free). |
| Value = debt reduction × criticality weight × objective fit | Reducing debt matters more in a critical unit, and only counts to the extent the strategy moves what the client wants moved (rehost changes where the system runs, not how fast it changes). |
| Constraints make options infeasible | A cutover that breaks the client's downtime limit, or a project above the budget ceiling, is not a real option. It is shown with the reason, never silently dropped. |
| Work packages instead of whole modules | Debt is concentrated (a dependency cycle, a god class and its satellites), so one strategy per module is too coarse. Packages are the units that get a strategy; a module can mix. |
| `entity-auto` out of the coverage denominator | Generated CRUD hides no logic (see Analysis coverage above). |
| Outdated dependencies leave module health | The value is identical for every module (estate-wide), so it cannot tell units apart; it is an estate-level finding. Exception: a module with its own build file gets the component. |
| Database coupling on a log scale | The old cap (15 calls per KLOC) was exceeded by every OFBiz module (15.5–30), so the component was 1.0 everywhere. Call counts are heavy-tailed; `ln(1 + x)` keeps differences visible and the reference is deliberately high. |
| testdef suites count as test evidence | OFBiz keeps many tests in `testdef/*.xml`; ignoring them overstated untested code. Reported separately, never summed with Groovy. |
| Retain's risk is status-quo exposure | Doing nothing has no change risk, but leaving a fragile, critical, untested unit alone is not risk-free; without this term "minimise risk" would always mean "do nothing". |

None of the numbers below was tuned to produce varied recommendations. Where results are uniform or fragile, the Phase 3.5
report in progress.md says so.

### The client scenario
`config/client_scenario.yaml` holds, for a fictional Tokyo distributor on a customised OFBiz ERP: the problem (high
maintenance cost, months to ship a feature, dependence on two engineers); four **objectives** as KPIs with current and target
values and a weight (maintenance cost, change lead time, expert dependency, run cost); **constraints** (5-year planning
horizon, ¥250M budget ceiling, maximum cutover downtime of 4 h for order and 2 h for accounting); the client's **priorities**
(cost 0.25, risk 0.35, speed 0.10, long-term value 0.30), used as the default profile `client_scenario`; and the
**criticality overrides** (accounting = 3, shipment = 2), each "from client interview". KPI current/target values are
descriptive: the model uses the objective weights, not the KPI numbers. **Scope (Phase 3.6):** the ¥180M a year maintenance KPI
and ¥36M run-cost KPI are labelled `scope: whole_erp`. `analysed_scope_share` (0.29, derived as 71,940 analysed Java code lines ÷
248,132 in the whole OFBiz codebase, by `cloc`) restates them for the analysed scope (¥52.2M and ¥10.4M), and the output's
`kpi_reconciliation` puts them next to the model's own baseline for that scope with the gap flagged. The scenario also holds
`change_requests_per_year` per module (illustrative) and an optional `client_reported_maintenance_jpy` per module (default null).

### Technical health (0–100, higher is healthier), per module and per work package
`health = 100 − Σ over 7 components of (100 × weight × normalized)`, each normalized 0 (good) … 1 (bad). Weights (config, sum
to 1): size 0.11, complexity 0.22, coupling 0.17, cycles 0.11, test evidence 0.22, database coupling 0.11, legacy namespaces
0.06 (the former weights ÷ 0.9, rounded, after removing outdated dependencies). Each component lists raw value, normalized
value, weight and points lost; the three biggest are the *top drivers*.
- **size / complexity / coupling:** LOC-weighted mean of the unit's class percentiles (LOC; complexity; average of fan-in and
  fan-out). Relative to the analysed estate.
- **cycles:** 0.5 if the module is in a module-level cycle + 0.5 × share of the unit's classes in class-level cycles.
- **test evidence:** `1 − min(1, tests per KLOC ÷ 5)`, tests = Java `@Test` + max(Groovy test files, testdef cases). A work
  package inherits its module's tests per KLOC (tests are mapped by package, not by class).
- **database coupling:** `ln(1 + calls per KLOC) ÷ ln(1 + 100)`, capped at 1: 15 calls/KLOC → 0.59, 30 → 0.74, 100 → 1.
- **legacy namespaces:** javax/legacy-framework imports ÷ (those + jakarta imports).
- **outdated dependencies (own build file only):** present only for a module whose build file lives inside its own component
  directory (weight 0.10, other weights scaled by 0.9). None of the analysed targets has one; elsewhere outdated
  dependencies are the estate-level finding in the output.
- **Limits:** the 5 tests/KLOC anchor and the 100 reference are illustrative; percentiles are relative to the scope.

### Hotspots (class level)
`score = Σ weight × value` over complexity percentile 0.30, LOC percentile 0.25, fan-out percentile 0.15, fan-in percentile
0.10, database density 0.10 (same log scale), in-a-class-cycle 0.10 (0 or 100). The top 15 are listed with components and flags.

### Business criticality (1–3): the tool proposes, the client confirms
- **Heuristic:** `score = 0.6 × (module's share of the estate's inbound references) + 0.4 × (module's share of the estate's data
  writes)`; ≥ 0.30 → 3, ≥ 0.12 → 2, else 1. Inbound = cross-module Java fan-in + service fan-in + controller fan-in; writes =
  data-changing entity-engine calls plus JDBC (SQL is not parsed, so JDBC counts as writing).
- **Overrides** come from the scenario file, per analysis, each with a written reason. The output records `source` (heuristic
  or override), the heuristic value even when overridden, and the reason. A work package inherits its module's criticality.
- **Limit:** a module that mostly calls others (OFBiz `accounting`) scores low on inbound references; the override exists for this.

### Work packages
Each class belongs to exactly one package, so package totals equal module totals. Built in this order:
1. **Dependency cycles:** each class-level strongly connected component. A cycle that spans modules is split into one package
   per module (so module totals still add up); the whole cycle's modules are recorded.
2. **God-class clusters:** each extreme-tier god class not already in a cycle, grown with its *satellites*: an unassigned class
   in the same module joins when at least 50% of its in-module neighbours (classes it references or that reference it) are
   already in the cluster. A widely used utility has many neighbours and stays out.
3. **Remainder:** the rest of each module, one package.
Packages are named from their dominant classes (largest by LOC). Each package gets its own health, options, choices,
sensitivity; the module report keeps the module's own health and criticality plus a **rollup** per profile (sums over its
packages: effort, migration cost, TCO, retain TCO, duration).
- **Limits:** a split cross-module cycle is scored fragment by fragment although it must change together; tests and confidence
  are inherited from the module; packages are a heuristic grouping, not a proven decomposition.

### Strategy options per work package
Strategies: **retain** (do nothing, always present and selectable), rehost, replatform, refactor, rearchitect, retire.
- **Eligibility:** *retire* is allowed only when nothing points into the package from outside on any inbound type (Java from
  other classes, services, controller events); otherwise it is shown as ineligible with the counts as the reason. *Rearchitect*
  needs test evidence; without it the effort gains a separate line "Build safety-net tests first".
- **Effort (migration):** `effort_days = KLOC × base_days_per_kloc[strategy] × complexity_multiplier × (1 + test_overhead) ×
  uncertainty_buffer` (+ the safety-net line). `complexity_multiplier = 1 + 0.6 × complexity percentile × strategy
  sensitivity`; `test_overhead = base[strategy] × (1 + test gap)`; `uncertainty_buffer` = 1.00 / 1.15 / 1.35 for high / medium /
  low confidence.
- **Migration cost and duration:** `migration_cost = round(effort_days × daily_rate)` (whole yen); `duration_months =
  effort_days ÷ (team_size[strategy] × 20)`.
- **Cutover approach and feasibility (Phase 3.6):** downtime is modelled from HOW a strategy goes live, not from the strategy
  alone. *Big bang* (rehost, replatform, retire): the whole package moves in one window, so hours = a base per strategy (2, 4, 1)
  + 0.25 h per KLOC: one event, and a bigger package needs a longer window. *Incremental / strangler* (refactor, rearchitect):
  the package is cut over in slices, `ceil(KLOC ÷ 3)` of them, each a 0.5 h event; old and new run side by side while slices
  move, which adds a "Parallel run of old and new" effort line of 15% of the core work. The client's downtime limit applies
  PER CUTOVER EVENT, so a large package can still be done incrementally under a 1 h limit but cannot be done big-bang. The
  output reports the approach, the number of events, the hours per event and the total. An option is also infeasible if its
  migration cost exceeds the budget ceiling. Infeasible options keep all their numbers and a written reason and are excluded
  from the ranking. A portfolio over the ceiling is flagged (`within_budget`) by Phase 3 and repaired by Phase 4. All
  parameters are illustrative; the earlier flat per-strategy hours (6/10/1/2/0.5) are gone because they made the retain/rehost
  split an artefact of one assumption.
- **Delivery risk (0–100):** `risk = min(100, base_risk[strategy] × (1 + exposure))`, exposure = weighted mean of poor health 0.30,
  criticality 0.25, test gap 0.20, cycles 0.10, low confidence 0.15. Retain: `0.5 × 100 × exposure` (status-quo exposure).
- **Long-term value (0–100):** `value = min(100, debt_reduction × burden × criticality_weight × objective_fit)`.
  `burden = 0.6 × (100 − health) + 0.4 × min(100, 100 × KLOC ÷ 30)`; `debt_reduction`: rehost 0.05, replatform 0.25, refactor 0.55,
  rearchitect 0.85, retire 1.0, retain 0; `criticality_weight`: 0.6 / 1.0 / 1.4 for criticality 1 / 2 / 3.
  `objective_fit = Σ over the counted objectives of (weight × effect[strategy][objective]) ÷ (sum of the counted weights)`,
  where the objective monetised in TCO (`change_lead_time`) is NOT counted (Phase 3.6, see change cost below), and `effect` (config) is the share of an objective's gap a
  strategy can close in principle: for example rehost moves run cost (0.6) and barely maintenance (0.05) and not lead time
  or expert dependency (0); refactor moves maintenance, lead time and expert dependency (≈0.5–0.6) but little run cost (0.1);
  rearchitect moves most things (0.5–0.9). Debt reduction measures how much debt a strategy removes; objective fit measures how
  much of what *this client* cares about it can move. Multiplying them is deliberately conservative: a strategy must do both.

### Total cost of ownership and the do-nothing baseline
For every option over the client's planning horizon (5 years): `tco = migration + Σ over years (run + maintenance + change)`, whole yen.
- **Baseline maintenance per year** = `KLOC × 6 days × (1 + 1.5 × (1 − health ÷ 100)) × daily_rate`: more code and worse health
  cost more to maintain. **Baseline run cost per year** = `KLOC × ¥150,000`. The maintenance baseline is left unchanged by Phase
  3.6 (see Breakeven below); it can be replaced per module by the client's own figure.
- **Change cost (Phase 3.6):** the cost of a change request depends on how healthy the code is: `cost per change = base_days_per_change (1.0)
  × (1 + 2.0 × (1 − health ÷ 100)) × daily_rate`. Yearly change cost = the package's change requests per year (its module's, by
  LOC share) × that. After migration the multiplier uses the RESIDUAL debt: `1 + 2.0 × (1 − debt_reduction[strategy]) ×
  (1 − health ÷ 100)`. The saving is its own benefit line (`change_savings_vs_retain`), separate from maintenance and run cost.
- **After migration**, maintenance = baseline × `(1 − debt_reduction[strategy])` (the same factor that drives value: residual
  debt stays and keeps costing), run cost = baseline × `residual_run_cost[strategy]` (rehost 0.85, replatform 0.70,
  refactor 0.95, rearchitect 0.60, retire 0) and change cost as above. Savings start when the migration ends; migration spend is
  spread evenly over its months. Year-by-year cash flows are in the output (migration, run, maintenance, change, total).
- **Reported per option:** TCO, savings against retain, **payback year** (first year the cumulative cost is no higher than
  retain's; none if never within the horizon), and **NPV** at 4% (`npv_cost` = present value of all outflows, year-end
  discounting; `npv_vs_retain` = retain's minus the option's, positive = better than doing nothing), plus the steady-state yearly
  figures after migration (used by the roadmap).
- **No double counting.** The change-cost saving is cash in TCO. The value score used to count the same effect through the
  "change lead time" objective, so that objective is now left out of `objective_fit` and the remaining objective weights are
  renormalised to sum to 1 (otherwise value would silently shrink). The value score stays; it keeps measuring debt removed and
  the non-cash objectives (maintenance burden, expert dependency, run cost).

### Breakeven instead of tuning (Phase 3.6)
The maintenance baseline is the weakest number in the model and the economics hinge on it, so it is not tuned. Instead, for
each package under the selected profile, the output reports `breakeven_jpy_per_year`: the yearly maintenance spend at which each
non-chosen selectable strategy would overtake the chosen one (searched between baseline ÷ 100 and × 100 in log space, refined by
bisection, with the direction), plus the spend at which retain stops being best and the spend at which retain loses to every
alternative. Only maintenance is varied (health, value and change cost are not), so each figure answers "how wrong would the
baseline have to be?". Tests re-run the model just before and just beyond each breakeven to prove it flips.
- **Client calibration:** if the client gives `client_reported_maintenance_jpy` for a module, it replaces the model's estimate
  as that module's baseline (spread over its packages in proportion to the model's estimates). Both figures, the gap in yen and
  percent, and a flag (gap above 25%) appear side by side in `maintenance_calibration`. With the default (null) nothing changes.
- **Scope:** `kpi_reconciliation` shows the whole-ERP KPI, the share, the scope-adjusted KPI and the model's baseline for the same
  scope (OFBiz: ¥52.2M adjusted vs ¥67.0M model, +28%, flagged).
- **Limit:** breakeven moves one number; it says nothing about the other assumptions.

### Priorities and the choice
Weights over cost, risk, speed and long-term value, summing to 1 (rejected otherwise). Profiles: the five presets, the client's
own `client_scenario` (the default), or custom `cost=…,risk=…,speed=…,long_term_value=…`. Each criterion becomes a 0–1 goodness on an
absolute scale: cost `max(0, 1 − tco ÷ (3 × retain_tco))`, speed `max(0, 1 − months ÷ 24)`, risk `1 − risk ÷ 100`, value
`value ÷ 100`. `score = 100 × Σ weight × goodness`. The best selectable (eligible and feasible) strategy wins; the runner-up and
margin are reported; a **close call** is a margin under 5 points; ties go to the earlier strategy in the config (retain first).
- **Known limitation (cost/speed collinearity):** cost and speed are both driven by effort, and risk grows with ambition too, so
  three of the four criteria favour the least ambitious option and only the long-term-value weight pushes the other way. The
  presets are left unchanged on purpose (Phase 3.6 decision); progress.md records what this does on OFBiz.

### Sensitivity
For the selected profile and each package, the engine searches one assumption at a time (daily rate, each strategy's base days,
each priority weight with the others rescaled to sum to 1) for the nearest value that flips the recommendation, refined by bisection:
the flip value, the change in percent and the new winner, or "no flip" in the searched range (×0.1 to ×10; weights 0 to 1). Tests
probe just before and just beyond every reported flip point. Other assumptions (cutover hours, maintenance baseline, criticality
weights, constraints) are not searched; progress.md reports what-ifs for the most influential of them.

### Estate totals
Per profile: strategy mix across packages, effort, total migration cost, total TCO against the total retain TCO, savings and NPV
against retain, total duration (sum over packages: one shared team in sequence; Phase 4 arranges waves), budget status and close
calls. Outdated dependencies appear as an estate-level finding with their coverage (checked of declared).

---

## Phase 4 — Portfolio and roadmap (`engine/roadmap/`)

Input: the recommendation (all profiles, all options), the analysis (class edges) and the scenario. Output:
`out/<name>.roadmap.json` (contract `engine/roadmap/schema.py`, JSON Schema `docs/roadmap-schema.json`). Deterministic: no
randomness, every iteration order is sorted, ties are broken by fixed rules (tested by running the pipeline twice).

### Budget-constrained portfolio
- **What it decides:** one selectable (eligible and feasible) option per package, maximising the **value-at-stake-weighted** sum of
  the packages' priority-weighted scores, subject to total migration cost ≤ the budget ceiling. A package's weight is its five-year
  do-nothing (retain) TCO, i.e. its share of the estate's do-nothing cost. Objective = Σ over packages of
  (retain TCO ÷ estate retain TCO) × (the chosen option's 0–100 score); the reported `total_score` is that weighted mean.
- **Why weighted (Phase 4 review fix):** the first version summed the 0–100 scores directly, so a 1 KLOC package counted as much as a
  13 KLOC one. That is a flaw in the objective's design, not a tuning choice: the score of a package says how good the best option is
  *for that package*, and the money and risk riding on a decision grow with what the package costs the client to leave alone.
  Weighting by do-nothing cost uses a quantity the model already computes and that needs no new assumption: a decision on a package
  that accounts for 20% of the estate's future cost counts for 20% of the objective. Two otherwise identical packages of different size
  get weights in exactly the ratio of their do-nothing costs (tested). The weights are whole yen and scores integers, so the objective is
  an exact integer and the optimiser stays exact; the unconstrained portfolio (each package's own best) is unaffected by the weighting.
- **Method:** exact dynamic programming over the Pareto frontier of (cost, score) states: after each package, a state is dropped only
  if another is at least as cheap and at least as good. Scores are integers (four decimals × 10,000), so there is no floating-point
  noise. Ties go to the higher score, then the lower cost, then the lexicographically smallest strategy order. The tests compare it
  with brute force over every combination on the fixture, for eight budgets.
- **Output:** the unconstrained portfolio (each package's own best), the constrained one, and exactly which packages were
  downgraded because of the budget (from, to, score lost, migration cost saved). `budget_binding` says whether the unconstrained
  portfolio exceeded the budget; if not, the two portfolios are identical.
- **Effect on OFBiz:** under `long_term_value` the budget now goes to the shopping-cart cycle (20% of the estate's do-nothing cost) first
  and the small packages are downgraded, instead of the reverse (see progress.md).
- **Limit:** the weight is today's do-nothing cost, which depends on the maintenance baseline (breakeven covers that); and a package
  with large cost is not necessarily one with large benefit from change.

### Sequencing into waves
- **Jobs:** every package whose chosen strategy is not retain is a job (effort, migration cost, duration, people from its chosen option).
  Capacity = teams × team size (config: 2 × 6 = 12 people); a job occupies the people its strategy needs (capped at the capacity;
  a capped job takes proportionally longer) for its whole duration, in whole months.
- **Dependencies (strangler order):** class edges are lifted to package edges. A package depends on the packages it references,
  following paths through packages that are not changing (retained ones). It starts only after those finish: leaves first, so
  dependents can switch to the new APIs. Packages that depend on each other, even indirectly, are *entangled* (strongly connected):
  they start in the same month and are cut over together. If an entangled group needs more people than the capacity allows at once, its
  members are staggered and every member's cutover is held until the whole group is built (reason `ENTANGLED_STAGGERED`).
- **Wave 0, foundations,** estimated with transparent formulas (effort days × daily rate; duration = days ÷ (4 people × 20)):
  CI/CD = 40 + 5 × packages that change code; observability = 30 + 0.5 × KLOC of the packages that need it; API facade = 30 + 10 ×
  strangler packages; and a **safety-net test suite** for every refactored or rearchitected package whose test gap is ≥ 0.8:
  `KLOC × 4 days × uncertainty buffer`, the same formula as the "build safety-net tests first" line. When that line was already inside
  the package's cost (rearchitect without tests), it is moved to Wave 0, not added twice. Which strategies need which foundation is
  config (CI/CD: replatform, refactor, rearchitect; observability: replatform, rearchitect; facade: refactor, rearchitect).
  Foundations, and the safety net of a package, finish before the packages that need them start. An all-rehost programme needs none.
- **Order:** quick wins first (risk ≤ 20, ≤ 3 months, no foundations needed: they build the client's confidence), then foundations,
  then the rest by value per risk (`value ÷ max(risk, 1)`, highest first). A job starts at the earliest month when its
  dependencies are done, capacity is free for its whole duration and the optional yearly budget cap would not be exceeded.
- **Reason codes** on every placement (never empty): `DEPENDS_ON`, `ENTANGLED_WITH`, `ENTANGLED_STAGGERED`,
  `CUTOVER_AFTER_ENTANGLED_GROUP`, `NEEDS_SAFETY_NET`, `NEEDS_CICD`, `NEEDS_OBSERVABILITY`, `NEEDS_FACADE`, `CAPACITY`, `BUDGET_CAP`,
  `QUICK_WIN`, `VALUE_PER_RISK_ORDER`, and `FOUNDATION_FOR` on foundations. Anything that cannot be placed is listed as unscheduled
  with a code, never dropped silently.
- **Waves:** Wave 0 = foundations; wave 1 + dependency depth for package groups; the final wave, "What modernization unlocks", has no work.

### Headline findings (no LLM)
`headlines` is a list of deterministic sentences built from the numbers, each carrying the numbers it states (`numbers`), so the UI's
executive summary and, later, the LLM's input contain only facts the engine produced. They are: the recommended portfolio and its cost
against the budget; the NPV against doing nothing, the payback quarter and the peak investment; the package with the largest value at
stake and what happens to it; the most expensive option considered and rejected, with the reason (a constraint it breaks, the budget,
or the score gap to the chosen option); the assumption most worth validating with the client; the model-versus-client maintenance gap; the unlocked
opportunities; the broken references found; and the outdated dependencies. The "assumption most worth validating" is chosen
deterministically: among packages with a maintenance-spend breakeven within ten times the baseline, the one with the largest share of the
estate's do-nothing cost. Breakevens are measured against each package's own best option under the profile (before the budget limit)
and exist only for the run's selected profile, so the sentence says so when they have not been computed.

### What modernization unlocks (no LLM)
A deterministic config mapping from modernized packages to data and AI opportunities. An opportunity lists requirements such as
"order packages holding at least 60% of the module's code reach refactor or beyond"; when all hold it is `unlocked`, its
prerequisites are those packages and it is available from the month after the last of them is cut over. Otherwise it is
`not_unlocked` with the blocking packages, or `module_not_analysed`. Rehost does not expose APIs, so an all-rehost programme unlocks
nothing. The four opportunities (demand forecasting, automated reconciliation, single customer view, delivery-time prediction) and
their requirements are illustrative configuration.

### Programme economics
Monthly cash flows over the planning horizon, the roadmap against doing nothing. Each package pays today's baseline maintenance +
run + change cost until its last cutover month, and the option's steady-state cost afterwards; migration and foundation spend are
spread evenly over each job's months. Reported by quarter: programme spend, cumulative cost under the roadmap and under retain, the
net difference (positive = ahead), and the yearly run rate of both. **Payback quarter** = the first quarter-end at which the
cumulative cost is no higher than retain's after having been behind (quarter 1 if never behind; none if no money is spent or it
never catches up). **NPV** = present value of the monthly (retain − roadmap − spend) flows at 4%. **Peak investment** = the largest
cumulative shortfall against retain. **KPI trajectory:** where the model supports it (maintenance cost, run cost) the client's
whole-ERP KPI minus the model's saving in the analysed scope; change lead time and expert dependency are marked not modelled.
- **Limits:** the KPI trajectory mixes the client's whole-ERP figure with a model saving whose baseline differs from the scope-adjusted
  KPI (flagged in `kpi_reconciliation`); the horizon cuts off savings beyond it; spend is spread evenly; one shared team pool.

### Gantt-ready output
Every item carries: wave, package, kind, strategy, start and end month (1-based, inclusive), people, a display lane and team label
(lanes are rows, capacity is people), effort, cost, the monthly spend, the cutover events (month and hours each), dependencies and
reason codes. Tests check that lanes never overlap, monthly spend sums to the cost, and capacity is never exceeded.

---

## Phase 5 — The API computes nothing new

`api/` exposes the analyzer, the engine and the roadmap over HTTP; every number still comes from those packages. What it adds:
- **Versioned scenarios and a hash cache.** A scenario edit creates a new version; the recommendation for (analysis, effective inputs) is cached
  under a hash of the analysis content, the client scenario, the effective engine and roadmap configuration and the engine version.
  Identical inputs, even from a different scenario version, reuse the stored run (and so keep the same ids).
- **Number ids.** Every number in a run is addressable as `<run id>:<doc>:<JSON pointer>` and `GET /explain/{id}` returns its formula,
  inputs (themselves addressable), the assumptions it used (labelled ILLUSTRATIVE) and its share of the parent total. The explanation is
  derived from the stored document and a registry keyed by (model, field); fields without a specific formula still resolve with a generic
  "recorded value" explanation, so every number is explainable, and a test walks every number in the fixture's run.
- **Slow work is separated.** Flip points and breakevens (about 4 s on OFBiz) run in a separate process after the response, debounced so only the
  latest run of an analysis is computed. A first measurement showed why: in the same process that job held the interpreter lock and slowed
  every concurrent request from about 100 ms to several seconds.
- **Health colour bands** for the graph (good at 60 or more, fair at 40 or more, otherwise poor) are an illustrative display convention. Classes have
  no health score of their own, so a class node shows 100 minus its hotspot score as a proxy.
