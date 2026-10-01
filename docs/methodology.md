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

## Phase 3 / 3.5 — Scoring and strategies (`engine/`)

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
descriptive: the model uses the objective weights, not the KPI numbers. Note the scenario's ¥180M/yr maintenance KPI is for
the whole ERP; the analysed four components are only part of it.

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
- **Feasibility against the scenario:** infeasible if the migration cost exceeds the budget ceiling, or if the strategy's cutover
  downtime exceeds the client's maximum for that module. Cutover hours per strategy are illustrative (rehost 6, replatform 10,
  refactor 1, rearchitect 2, retire 0.5, retain 0): big-bang strategies move the whole application in one window; incremental
  (strangler) ones cut over route by route. Infeasible options keep all their numbers and a written reason, and are excluded
  from the ranking. A portfolio whose total migration cost exceeds the ceiling is flagged (`within_budget`), not altered.
- **Delivery risk (0–100):** `risk = min(100, base_risk[strategy] × (1 + exposure))`, exposure = weighted mean of poor health 0.30,
  criticality 0.25, test gap 0.20, cycles 0.10, low confidence 0.15. Retain: `0.5 × 100 × exposure` (status-quo exposure).
- **Long-term value (0–100):** `value = min(100, debt_reduction × burden × criticality_weight × objective_fit)`.
  `burden = 0.6 × (100 − health) + 0.4 × min(100, 100 × KLOC ÷ 30)`; `debt_reduction`: rehost 0.05, replatform 0.25, refactor 0.55,
  rearchitect 0.85, retire 1.0, retain 0; `criticality_weight`: 0.6 / 1.0 / 1.4 for criticality 1 / 2 / 3.
  `objective_fit = Σ objective weight × effect[strategy][objective]`, where `effect` (config) is the share of an objective's gap a
  strategy can close in principle: for example rehost moves run cost (0.6) and barely maintenance (0.05) and not lead time
  or expert dependency (0); refactor moves maintenance, lead time and expert dependency (≈0.5–0.6) but little run cost (0.1);
  rearchitect moves most things (0.5–0.9). Debt reduction measures how much debt a strategy removes; objective fit measures how
  much of what *this client* cares about it can move. Multiplying them is deliberately conservative: a strategy must do both.

### Total cost of ownership and the do-nothing baseline
For every option over the client's planning horizon (5 years): `tco = migration + Σ over years (run + maintenance)`, whole yen.
- **Baseline maintenance per year** = `KLOC × 6 days × (1 + 1.5 × (1 − health ÷ 100)) × daily_rate`: more code and worse health
  cost more to maintain. **Baseline run cost per year** = `KLOC × ¥150,000`.
- **After migration**, maintenance = baseline × `(1 − debt_reduction[strategy])` (the same factor that drives value: residual
  debt stays and keeps costing) and run cost = baseline × `residual_run_cost[strategy]` (rehost 0.85, replatform 0.70,
  refactor 0.95, rearchitect 0.60, retire 0). Savings start when the migration ends; migration spend is spread evenly over its
  months. Year-by-year cash flows are in the output (migration, run, maintenance, total).
- **Reported per option:** TCO, savings against retain, **payback year** (first year the cumulative cost is no higher than
  retain's; none if never within the horizon), and **NPV** at 4% (`npv_cost` = present value of all outflows, year-end
  discounting; `npv_vs_retain` = retain's minus the option's, positive = better than doing nothing).
- **Limits:** the maintenance and run baselines are the weakest numbers in the model and the economics depend on them (see
  progress.md): the model's baseline for the four analysed components is ¥67M a year, against the scenario's whole-ERP KPI of
  ¥180M. A maintenance baseline 2.5× higher makes refactor attractive; the configured value is left as is.

### Priorities and the choice
Weights over cost, risk, speed and long-term value, summing to 1 (rejected otherwise). Profiles: the five presets, the client's
own `client_scenario` (the default), or custom `cost=…,risk=…,speed=…,long_term_value=…`. Each criterion becomes a 0–1 goodness on an
absolute scale: cost `max(0, 1 − tco ÷ (3 × retain_tco))`, speed `max(0, 1 − months ÷ 24)`, risk `1 − risk ÷ 100`, value
`value ÷ 100`. `score = 100 × Σ weight × goodness`. The best selectable (eligible and feasible) strategy wins; the runner-up and
margin are reported; a **close call** is a margin under 5 points; ties go to the earlier strategy in the config (retain first).
- **Limit:** cost, risk and speed all favour the least ambitious option, so unless the value weight is large the result is
  retain or rehost; see progress.md for what this does on OFBiz.

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
