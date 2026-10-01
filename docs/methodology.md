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
- A module has test evidence when a class exists under `src/test/java` in the matching package, or a Groovy script under
  `src/test/groovy` declares a matching package. Reported separately: `test_classes`, `test_method_count` (`@Test`),
  `groovy_test_files`. **Limits:** presence, not coverage or quality; OFBiz `testdef/*.xml` suites are not counted.

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
- **How:** `java_share` = Java service definitions ÷ implemented service definitions. Engines that implement nothing
  (`interface`, `group`) are excluded from the denominator; `groovy`, `simple` (XML minilang) and `entity-auto` count as
  not analysed. Confidence: **high** ≥ 0.60, **medium** ≥ 0.30, otherwise **low** (config). With no service definitions,
  confidence is high if there is no Groovy logic, medium if there is. The Groovy file count (outside tests) is reported.
- **Limits:** a module inherits its component's figure (OFBiz `shipment` lives in the product component and gets
  product's). `entity-auto` is generated CRUD with little hidden logic; counting it as "not analysed" pushes every OFBiz
  module to *low* (Java share 0.11–0.54 → 0.24–0.54 if it were excluded). Change `non_implementing_engines` to try it.

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

## Phase 3 — Scoring and strategies (`engine/`)

Input: the analyzer JSON. Output: `out/<name>.recommendation.json` (contract `engine/schema.py`). Every number is stored with
the breakdown that reconstructs it, and the tests rebuild each one exactly (e.g. `health = round(100 − Σ contributions, 4)`).

### Technical health (0–100, higher is healthier), per module
`health = 100 − Σ over 8 components of (100 × weight × normalized)`, each component normalized to 0 (good) … 1 (bad).
Weights (config, sum to 1): size 0.10, complexity 0.20, coupling 0.15, cycles 0.10, test evidence 0.20, database
coupling 0.10, legacy namespaces 0.05, outdated dependencies 0.10. For each component the output lists the raw value,
normalized value, weight and points lost; the three biggest are the module's *top drivers*.
- **size / complexity / coupling:** the LOC-weighted mean of each class's percentile (size: LOC percentile; complexity:
  complexity percentile; coupling: average of fan-in and fan-out percentiles). Percentile-based, so they are relative to
  the analysed estate.
- **cycles:** 0.5 if the module is in a module-level cycle + 0.5 × share of its classes in class-level cycles.
- **test evidence:** `1 − min(1, tests per KLOC ÷ 5)`, tests = Java `@Test` methods + Groovy test scripts.
- **database coupling:** `min(1, database calls per KLOC ÷ 15)`.
- **legacy namespaces:** javax/legacy-framework imports ÷ (those + jakarta imports).
- **outdated dependencies:** outdated ÷ checked dependencies, estate-wide (cannot be attributed to a module, so equal for all).
- **Limits:** the 5 and 15 per-KLOC anchors are illustrative. On OFBiz the database component is saturated (1.0) in every
  module (15.5–30 calls/KLOC), so it does not discriminate; the outdated-dependency component is identical across modules.
  Health scores cluster (30–45) and the same three drivers lead everywhere.

### Hotspots (class level)
`score = Σ weight × value` over complexity percentile 0.30, LOC percentile 0.25, fan-out percentile 0.15, fan-in
percentile 0.10, database density 0.10 (calls per KLOC ÷ 15, capped), and in-a-class-cycle 0.10 (0 or 100). The top 15 are
listed with their components and flags (god-class tier, in cycle, module without tests, unused).

### Business criticality (1–3) — the tool proposes, the consultant confirms
- **Heuristic:** `score = 0.6 × (module's share of the estate's inbound references) + 0.4 × (module's share of the
  estate's data writes)`. Inbound = cross-module Java fan-in + service fan-in + controller fan-in. Writes = entity-engine
  calls that change data (`makeValue`, `create`, `store`, `removeValue`, `removeByAnd`, `getNextSeqId`) plus JDBC calls
  (SQL is not parsed, so JDBC is conservatively treated as writing). `score ≥ 0.30` → 3, `≥ 0.12` → 2, else 1.
- **Overrides:** `config/criticality_overrides.yaml`, per analysis, each with a written reason (rejected if missing).
  The output records `source` (heuristic or override), the heuristic value even when overridden, and the reason.
- **Limits:** shares are relative to the estate, so a module is "critical" compared with its siblings. A module that
  mostly *calls* others (OFBiz `accounting`) scores lower than one that is *called*, which a business owner would dispute.

### Strategy options per module
Strategies: rehost, replatform, refactor, rearchitect, retire.
- **Eligibility:** *retire* is allowed only when nothing points into the module on any inbound type (cross-module Java,
  services, controller events); otherwise it is shown as ineligible with the counts as the reason. *Rearchitect* needs test
  evidence; without it the effort gains a separate line "Build safety-net tests first".
- **Effort:** `effort_days = KLOC × base_days_per_kloc[strategy] × complexity_multiplier × (1 + test_overhead) ×
  uncertainty_buffer`, plus the safety-net line `KLOC × 4 × buffer` where applicable.
  `complexity_multiplier = 1 + 0.6 × module complexity percentile × strategy sensitivity` (rehost 0.1 … rearchitect 1.0);
  `test_overhead = base[strategy] × (1 + test gap)`; `uncertainty_buffer` = 1.00 / 1.15 / 1.35 for high / medium / low
  confidence (the analyzer sees less of the logic, so we plan for more work).
- **Cost and duration:** `cost_jpy = round(effort_days × daily_rate_jpy)` (integer yen);
  `duration_months = effort_days ÷ (team_size[strategy] × 20 working days)`.
- **Risk (0–100):** `risk = min(100, base_risk[strategy] × (1 + exposure))`, where exposure is the weighted mean (weights
  sum to 1) of: poor health 0.30, criticality 0.25, test gap 0.20, cycles 0.10, low confidence 0.15. So a strategy's
  inherent riskiness (rehost 8 … rearchitect 48) is up to doubled when the module is fragile, critical, untested,
  tangled and poorly understood.
- **Long-term value (0–100):** `value = debt_reduction[strategy] × burden`, `burden = 0.6 × (100 − health) + 0.4 ×
  min(100, 100 × KLOC ÷ 30)` (debt, plus a maintenance proxy that grows with size). Reduction: rehost 0.05, replatform
  0.25, refactor 0.55, rearchitect 0.85, retire 1.0.
- **Limits:** effort is linear in size (a god class costs no more per line than a small one); the buffer is a blunt
  instrument; rehost excludes infrastructure and licence costs; one strategy per module (real work happens at hotspot level).

### Priorities and the choice
Weights over cost, risk, speed and long-term value, summing to 1 (rejected otherwise). Presets: *minimize_cost*
(0.60/0.15/0.15/0.10), *minimize_risk* (0.10/0.60/0.10/0.20), *speed_to_market* (0.20/0.10/0.60/0.10), *long_term_value*
(0.10/0.15/0.05/0.70), *balanced* (0.25 each; the default), or custom weights `cost=…,risk=…,speed=…,long_term_value=…`.
Each criterion becomes a 0–1 goodness on an **absolute** scale: cost `max(0, 1 − cost ÷ ¥200M)`, speed `max(0,
1 − months ÷ 24)`, risk `1 − risk ÷ 100`, value `value ÷ 100` (ceilings are illustrative). `score = 100 × Σ weight ×
goodness`. The best eligible strategy wins; the runner-up and the margin are reported; a **close call** is flagged when the
margin is under 5 points. Ties go to the cheaper strategy.
- **Why absolute scales:** the first version scaled each criterion min–max across the module's own options. That erased
  differences between modules (identical answers and margins everywhere) and made the daily rate unable to change any
  ranking. Absolute scales keep module size and health visible.
- **Limit:** cost, risk and speed all favour the least ambitious option, so only the long-term-value weight separates the
  presets (see "Where this looks unconvincing" in the Phase 3 report in progress.md).

### Sensitivity
For the selected profile, for each module, the engine searches one assumption at a time (daily rate, each strategy's base
days, each priority weight with the others rescaled to keep the sum at 1) for the nearest value that flips the
recommendation, refined by bisection. The output gives the value at which it flips, the change in percent, and the new
winner, or says no flip exists in the searched range (×0.1 to ×10; weights 0 to 1). Tests re-run the model just before and
just after every reported flip point to prove it flips.

### Estate totals
Per profile: total effort, total cost, total duration (sum over modules: one shared programme team working in sequence;
Phase 4 arranges waves and parallelism) and the list of close calls.
