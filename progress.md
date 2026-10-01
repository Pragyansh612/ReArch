# ReArch — Progress

Living log. Newest entries first. Update after every task or phase.
Plan reference: `BUILD_PLAN.md`. Rules: `CLAUDE.md`. Convention: the user runs all git commands; one commit per phase.

## Status overview

| Phase | Name | Status |
|---|---|---|
| 0 | Setup and target choice | Done, committed |
| 1 | Fixture with known answers | Done, committed; review fixes applied in Phase 2 session |
| 2 | Analyzer | Built and verified; awaiting user review and commit |
| 3 | Scoring and strategies | Not started |
| 4 | Roadmap | Not started |
| 5 | API | Not started |
| 6 | Web UI | Not started |
| 7 | LLM layer | Not started |
| 8 | Polish and deploy | Not started |

## Log

### 2026-10-01 — Phase 2: analyzer
Fixture fixes (from Phase 1 review):
- Added `service_fan_in` per class and `used = fan_in + service_fan_in > 0` (`OrderServices`: Java fan-in 0, service fan-in 2).
- Added boundary classes `StatementFormatter` (LOC 399, complexity 50, not a god class) and `LedgerReconciler`
  (400, 51, god class). Fixture is now 20 classes, 2,026 LOC.
- Added cycles to `expected.json` (module cycle billing/order/party; class cycle of 4) and an `as_of` date on the dependency table.
- `expected.json` now holds outputs only; every threshold/rule moved to `config/assumptions.yaml`.

Analyzer (`analyzer/`): `config.py`, `schema.py` (Pydantic output contract; JSON Schema in `docs/analysis-schema.json`),
`java_parser.py` (tree-sitter), `sources.py`, `deps.py` (pom + version catalog), `services.py`, `graph.py`
(resolution, Tarjan cycles), `findings.py`, `analyze.py`, `__main__.py`. CLI: `make analyze REPO=<path|git url> [SCOPE=".."] [NAME=..]`.
Tests: 136 pytest (one per metric vs `expected.json`, traps, boundary, config-driven threshold, parser units).
`make test` and `make lint` pass. Independent cross-check `scripts/crosscheck.py` (`make crosscheck`), `cloc` in git-ignored `.tools/`.

Real-target runs (details in the Phase 2 report given to the user):
- OFBiz (order, product, party, accounting): 132 classes, 71,940 LOC, 5 modules (product component contains package `shipment`), 1.8 s. LOC equals `cloc` exactly.
- JPetStore: 25 classes, 1,368 LOC, 0.1 s; 0 DB-coupling calls (MyBatis), 1 outdated dependency (spring-web 5.3.39).

Discoveries that changed the design:
- OFBiz "no tests" was false: 60 Groovy test scripts exist. Groovy tests now count as test evidence (`groovy_test_files`).
- Dependency table covered 1 of 99 OFBiz coordinates; output now reports `dependencies_checked` next to the outdated count; 3 javax→jakarta coordinates added.
- Two service definitions in OFBiz point at methods that do not exist (`creditOrderPaymentPreference`, `updateProductQuickAdminShipping`).

### 2026-10-01 — Phase 1 + Phase 0 follow-ups
- Phase 1 fixture and oracle built (see `docs/fixture.md`). User reviewed; feedback applied above.
- Git was initialised (a "setting up base" commit exists from the user; "Phase 0: scaffold and target choice" on top).
- Target confirmed: OFBiz (order, product, party, accounting); JPetStore as Maven smoke test (`docs/target.md`).

### 2026-09-30 — Phase 0
- Scaffolded monorepo, Makefile, FastAPI `/health`, Next.js app, `config/assumptions.yaml` placeholders.
- Cloned and measured JPetStore and OFBiz; recommendation in `docs/target.md`.

## Open decisions (for the user)
1. **God-class thresholds** (400 LOC / complexity > 50) flag 46 of 132 OFBiz classes (35%). Options: keep as "large" and
   add an "extreme" tier (e.g. LOC ≥ 2000 flags 9), or rank by percentile in Phase 3. Fixture boundary tests depend on 400/50.
2. **Controller entry points.** OFBiz web event classes (`CheckOutEvents`, `ProductEvents`) show `used=false` because
   they are wired in `controller.xml`. Add a `controller_fan_in` (like `service_fan_in`) before Phase 3 criticality?

## Known gaps / risks
- **Logic outside Java** (main blind spot): in the four OFBiz components only 360 of 2,271 service definitions are Java;
  444 are Groovy, 215 XML minilang, 1,194 entity-auto. Partial mitigation: `services.xml` mappings give `service_fan_in`
  (which Java classes the non-Java world calls) and Groovy files are counted and listed as `not_analyzed`. The content of
  Groovy/XML logic is not analysed.
- Fan-in/out only count classes inside the analysed scope (framework and library references are invisible).
- Dependency table is small (4 of 99 OFBiz coordinates checked) and values are conservative lower bounds; re-verify before quoting.
- Tests in OFBiz `testdef/*.xml` are not counted; test presence is not coverage.
- `getNextSeqId` is counted as entity-engine DB access by design (70 of 1,392 OFBiz instances).
