# ReArch — Progress

Living log. Newest entries at the top of each section. Update after every task or phase.
Plan reference: `BUILD_PLAN.md`. Rules: `CLAUDE.md`.

## Status overview

| Phase | Name | Status |
|---|---|---|
| 0 | Setup and target choice | Done — target confirmed, committed |
| 1 | Fixture with known answers | Done — awaiting user review of expected.json; commit pending (user runs git) |
| 2 | Analyzer | Not started |
| 3 | Scoring and strategies | Not started |
| 4 | Roadmap | Not started |
| 5 | API | Not started |
| 6 | Web UI | Not started |
| 7 | LLM layer | Not started |
| 8 | Polish and deploy | Not started |

## Log

### 2026-10-01 — Phase 1
- Built `fixtures/legacy-sample/`: 18 main classes, 4 modules (order, billing, party, common), 3 test classes,
  `services.xml` (5 services), 1 Groovy script, `pom.xml` and `gradle/libs.versions.toml` with outdated versions.
- Wrote `fixtures/expected.json` (the Phase 2 oracle) and `docs/fixture.md` (each smell and its OFBiz counterpart).
- Values derived by a throwaway script from written rules, then hand-checked. No analyzer code written.
- User asked that Claude run no further git commands; user commits. (Claude had already run `git init`/one commit for Phase 0.)

### 2026-10-01 — Target confirmed
- User confirmed OFBiz (order, product, party, accounting) as primary target; JPetStore kept as Maven smoke test.
- Recorded in `docs/target.md`. Git initialised; initial commit "Phase 0: scaffold and target choice".
- Convention from now on: one commit at the end of every phase.

### 2026-10-01 — Phase 0 verification
- `make dev` verified: API `/health` returns ok on :8000, web returns 200 on :3000.
- `pytest` (1 passed), `ruff`, `mypy --strict`, `tsc --noEmit`, `eslint` all clean.
- create-next-app added `web/AGENTS.md`, `web/CLAUDE.md`, `web/README.md` (Next.js boilerplate; AGENTS.md says to read `node_modules/next/dist/docs/` before writing web code). Removed the nested `web/.git` it created.

### 2026-09-30 — Phase 0
- Read all markdown docs in the repo (`CLAUDE.md`, `BUILD_PLAN.md`).
- Scaffolded monorepo: `analyzer/ api/ web/ llm/ config/ fixtures/ docs/ targets/ out/`, root `pyproject.toml`,
  `Makefile` (`setup dev test lint analyze`), `.gitignore`, `config/assumptions.yaml` (placeholders).
- Minimal FastAPI app (`/health`) with a pytest; `analyzer` CLI stub; Next.js app in `web/`.
- Cloned JPetStore and OFBiz into `targets/` and measured them. Findings in `docs/target.md`.
- **Recommendation:** OFBiz bounded to order + product + party + accounting; JPetStore as a secondary smoke test.

## Open decisions
- Review `fixtures/expected.json` rules and thresholds before Phase 2.

## Known gaps / risks
- OFBiz logic in XML services/Groovy is invisible to a Java-only analyzer.
- OFBiz uses Gradle; Phase 2 needs a Gradle/TOML dependency parser in addition to `pom.xml`.
- Project directory is not a git repository yet (not initialised).
