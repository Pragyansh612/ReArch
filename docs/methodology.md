# Methodology

How every number in ReArch is produced, in plain English. Updated after each phase.
Rule zero: Python computes every fact; an LLM may only explain facts it is given.
All thresholds and rates live in `config/assumptions.yaml`; the analyzer contains none.

## Phase 0 — Target selection
Figures in `docs/target.md` were counted directly from the cloned repositories (file counts, line counts,
`@Test` occurrences). Nothing is estimated.

## Phase 2 — The analyzer

**What it does.** Reads a repository (optionally only some directories, the "scope") and writes one JSON
document (`out/<name>.json`, contract in `analyzer/schema.py`, JSON Schema in `docs/analysis-schema.json`).
It parses Java with tree-sitter, so comments, string literals and Javadoc are never mistaken for code.
It never runs or compiles the code.

**What is analysed.** `src/main/java` under the scope. Tests (`src/test/java`, `src/test/groovy`), Groovy and XML
are inventoried only. A *module* is the first package segment after a configured root
(`org.apache.ofbiz.order.order.X` → module `order`). A *class* is the first top-level type of a `.java` file.

### Lines of code (`loc`)
- **Measures:** size. **How:** lines of a file containing at least one code token; blank lines and comment-only
  lines (line, block, Javadoc) are excluded; `package` and `import` lines are included.
- **Why this definition:** it is the same definition `cloc` uses, so it can be checked independently.
- **Limits:** measures size, not quality. Generated code and long license headers distort raw file length
  (OFBiz `OrderServices.java`: 7,516 physical lines, 6,212 code lines).

### Fan-out, fan-in (Java)
- **Measures:** coupling. Fan-out = distinct *other analysed* classes a class references; fan-in = how many
  analysed classes reference it.
- **How:** a class is referenced when its name appears as an identifier in code (not in a comment, string or
  import line) and resolves through an explicit import, the same package, or a wildcard import.
  Self-references are ignored; a class is counted once however often it is used.
- **Limits:** only classes inside the analysed scope are counted, so references to framework classes
  (OFBiz `framework/`, JDK, libraries) do not add to fan-out. Reflection, dependency injection by name and
  string-based wiring are invisible. A second top-level type in a file counts as its file's class.

### Service fan-in (`service_fan_in`) and `used`
- **Measures:** inbound use that Java code cannot show. In OFBiz most business logic is invoked by name through
  `servicedef/*.xml`; `OrderServices` has Java fan-in 0 but 77 service definitions point at it.
- **How:** number of `<service engine="java" location="…" invoke="…">` entries whose `location` is the class.
  A class is `used` when `fan_in + service_fan_in > 0`. Phase 3 business criticality uses both numbers.
- **Limits:** other inbound paths are not yet counted — notably web event handlers declared in `controller.xml`
  (on OFBiz, `CheckOutEvents`, `ProductEvents` show as "unused" for this reason). `used=false` therefore means
  "no inbound reference found", not "dead code".

### Complexity and band
- **Measures:** how many decisions a class contains (an approximation of cyclomatic complexity).
- **How:** number of method/constructor bodies plus decision points: `if` (an `else if` is another `if`), `for`,
  enhanced `for`, `while`, `do`, `case`, `catch`, `?:`, `&&`, `||`. `else` and `default` do not count.
  Summed over the whole class. Band: low ≤ 15, medium 16–50, high > 50 (config).
- **Limits:** class-level sum, not per method, so a class of many trivial methods scores like one with a few
  tangled ones; lambdas are counted only through the decisions inside them; `switch` arrow rules count as
  `case`. It is a relative indicator, not a precise cyclomatic figure.

### God class and highly coupled (findings)
- God class: `loc ≥ 400` AND `complexity > 50`. Highly coupled: `fan_in ≥ 5` AND `fan_out ≥ 8` (Java fan-in/out).
- **Limits:** thresholds were set on the small fixture. On OFBiz they flag 46 of 132 classes (35%), so they
  separate "big" from "small" but not "worst" from "bad". Needs re-calibration (see progress.md).
- Boundary tests: `StatementFormatter` (399 LOC, complexity 50) must not be flagged; `LedgerReconciler`
  (400, 51) must.

### Database coupling
- **Measures:** business logic that talks to the database itself. **How:** one instance per method call matching a
  configured pattern, with file and line. `jdbc`: `DriverManager.getConnection`, `.prepareStatement`,
  `.createStatement`. `entity_engine`: `EntityQuery.use` and `delegator.<makeValue|create|store|findOne|findList|
  findByAnd|findAll|removeValue|removeByAnd|getNextSeqId>`. The entity-engine API classes themselves are ignored.
- **Limits:** counts call sites, not distinct tables or transactions. Patterns are name-based: a delegator held in a
  variable with another name is missed; MyBatis/Hibernate/Spring mappers and SQL in XML are not seen (JPetStore
  shows 0). `getNextSeqId` (sequence fetch) is counted as database access by design.

### Legacy markers and namespace mix
- **How:** import statements. `javax.<family>` for families that moved to Jakarta EE (servlet, mail, ejb, persistence,
  jms, transaction, …; the list is config), `jakarta.*`, and legacy frameworks (Struts). JDK packages such as
  `javax.sql` are not markers. A module with both javax and jakarta imports is `namespace_mix`.
- **Limits:** imports only; fully-qualified names in code and reflection-loaded classes are missed.

### Test presence
- **How:** a module has tests when a class exists under `src/test/java` in the matching package, or a Groovy
  script under `src/test/groovy` declares a matching package. Reported separately: `test_classes`,
  `test_method_count` (`@Test`), `groovy_test_files`.
- **Limits:** presence, not coverage or quality. OFBiz also defines tests in `testdef/*.xml`, not counted.

### Dependencies (pom.xml and gradle/libs.versions.toml)
- **How:** declared coordinates and versions are read (Maven `${property}` references resolved; Gradle
  `version.ref`). A dependency is **outdated** when its declared major version is lower than
  `min_current_major` in the bundled table (`config/assumptions.yaml`, dated `as_of`). `javax.*` → `jakarta.*`
  renames count as a major upgrade.
- **Limits:** the table is small and every value is a conservative *lower bound*; coordinates not in the table are
  `checked=false` and never reported as outdated. The output states how many were checked (OFBiz: 4 of 99), so
  "0 outdated" is never presented without its coverage. Re-verify the table before quoting dependency findings.
  Transitive dependencies and Gradle `dependencies.gradle` blocks are not read.

### Service mappings and unanalyzed files
- Each `<service>` in a `servicedef` XML whose root is `<services>` is listed. `engine="java"` → `Class#method`,
  analysed, and checked against the parsed classes (`class_found`, `method_found`). All other engines
  (`groovy`, `simple`, `entity-auto`, `group`, `interface`, …) are `analyzed=false`.
- Groovy files are **counted and listed, never parsed** (`report_status: not_analyzed`).
- **Limits:** this is the main blind spot on OFBiz. In the four analysed components only 360 of 2,271 service
  definitions are Java; 444 are Groovy, 215 are XML minilang, 1,194 are generated by `entity-auto`. The Java numbers
  describe the Java part of the system only. The service mapping is a partial mitigation: it shows which Java
  classes the non-Java world calls into, but not what the Groovy/XML logic itself contains.

### Cycles
- Strongly connected components (Tarjan) of the class graph and of the module graph (module edge = at least one
  class-level reference). Only components with more than one member are reported.

### Cross-check (independent of the analyzer code)
`scripts/crosscheck.py` compares the analyzer output with `cloc` (LOC, per file) and plain `grep` (database
calls), sharing no parsing code. `make crosscheck REPO=… NAME=…`.

| Target | LOC: analyzer vs cloc | DB calls: analyzer vs grep |
|---|---|---|
| Fixture (20 files) | 2,026 vs 2,026, 0 files differ | JDBC 5 vs 6; entity 55 vs 59 |
| OFBiz subset (132 files) | 71,940 vs 71,940, 0 files differ | JDBC 0 vs 0; entity 1,392 vs 1,392 lines |

Every difference is explained:
- Fixture, grep-only: one string literal and one Javadoc line in `PaymentCalculator.java` (deliberate traps), and two
  calls inside the ignored stub class `EntityQuery.java`.
- OFBiz, grep-only: `InvoiceServices.java:261`, a `//` comment containing `delegator.create(`. Analyzer-only:
  `ImportProductServices.java:144`, a call split across lines (`delegator` on the previous line) that a line-based
  grep cannot see. Both differences show why parsing is used instead of text search.
- Hand checks on OFBiz: services pointing at `OrderServices` by grep = 77 = analyzer; files mentioning
  `ProductWorker` by grep = 22 = analyzer fan-in; `OrderServices` has 12 explicit in-scope imports plus the
  same-package `OrderReadHelper` = fan-out 13.
