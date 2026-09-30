# ReArch — Build Plan (Claude Code)

About 3 weeks, 8 phases. Each phase is one or two Claude Code sessions.
Start each session in **plan mode**, paste the prompt, review the plan, then let it build.

After each phase, ask Claude: *"Explain what you just built as if I'm defending it in an interview."*
You must be able to explain every number on screen. This is the part Claude Code can't do for you.

---

## Phase 0 — Setup and target choice (Day 1)
**Prompt:**
> Set up the monorepo described in CLAUDE.md: analyzer/, api/, web/, llm/, config/, fixtures/, docs/, Makefile.
> Then help me pick a real legacy Java monolith as the demo target. Evaluate candidates such as
> mybatis/jpetstore-6 and a bounded subset of Apache OFBiz: clone them, report size, Java version,
> build files, test count and framework age. Recommend one and explain why.

**Done when:** `make dev` runs empty apps; target chosen and noted in `docs/target.md`.

## Phase 1 — Fixture with known answers (Day 2)
**Prompt:**
> Create fixtures/legacy-sample: a small Java 8 Maven app (~15 classes) that deliberately has
> a god class, a highly-coupled service, direct JDBC calls in business logic, no tests for some
> modules, and old dependencies in pom.xml. Write fixtures/expected.json listing exactly what the
> analyzer should find.

**Done when:** `expected.json` exists and it is the test oracle for Phase 2.

## Phase 2 — Analyzer (Days 3–5)
**Prompt:**
> Build analyzer/ with tree-sitter-java. Per class and per package-module compute: LOC,
> fan-in, fan-out, approximate cyclomatic complexity, test presence, direct JDBC/SQL usage,
> legacy framework markers (javax.*, Struts, EJB, etc.), and pom.xml dependency versions
> vs a bundled table of current majors. Add optional git churn. Output one JSON per run.
> Every metric must match fixtures/expected.json in pytest.

**Done when:** tests are green on the fixture; `make analyze` runs on the real target.

## Phase 3 — Scoring and strategies (Days 6–7)
**Prompt:**
> Build technical_health (0–100) as a weighted formula over the metrics, with weights in
> config/assumptions.yaml. Default business_criticality from fan-in and entry points
> (controllers/servlets), user-overridable. For each module compute cost, risk, time and
> long-term value for each strategy using a transparent effort model:
> effort_days = KLOC × base_days_per_kloc[strategy] × complexity_multiplier × (1 + test_overhead).
> cost = effort_days × daily_rate_jpy. Given Priorities, pick a strategy and return the full
> scoring breakdown. Unit-test that changing priorities changes the recommendation.

## Phase 4 — Roadmap (Day 8)
**Prompt:**
> Order modules into Waves using the dependency graph: leaves and low-risk modules first,
> strangler-fig extraction, legacy retirement last. The final wave is "What modernization
> unlocks": data and AI opportunities that become feasible once modules are exposed via APIs.
> Justify each placement with facts.

## Phase 5 — API (Day 9)
**Prompt:**
> Expose FastAPI endpoints: POST /analyses (repo URL or upload), GET results, PUT priorities
> and assumptions (recompute instantly, no re-analysis), GET roadmap. Persist in SQLite.

## Phase 6 — Web UI (Days 10–13)
Screens, in this order (this is also the demo script):
1. **Client scenario** — a fictional Japanese client, the business problem, and which repo is analyzed
2. **Diagnosis** — estate summary numbers and the criticality × health heatmap
3. **Architecture** — React Flow dependency graph, colored by health
4. **Module detail** — findings with file/line evidence
5. **Strategies** — rehost/replatform/refactor/rearchitect table, plus priority sliders that change the recommendation live
6. **Business case** — every yen figure with "show calculation"; editable assumptions
7. **Roadmap** — waves on a timeline
8. **Executive brief** — generated summary with an EN/日本語 toggle and print-to-PDF

## Phase 7 — LLM layer (Days 14–15)
**Prompt:**
> Build llm/: module explanations and the executive brief, generated only from the facts JSON.
> Prompts live in llm/prompts. Add guard.py: extract every number from the output and reject
> it if any number is not present in the input. Generate a Japanese version of the brief.
> Cache outputs so the demo never waits on the API.

## Phase 8 — Polish and deploy (Days 16–18)
- README: problem → approach → screenshots → "How the numbers are calculated" → limitations
- `docs/methodology.md` finalized; one architecture diagram of ReArch itself
- Deploy: web on Vercel, API on Render/Railway/Fly; pre-load the demo analysis
- Record a 3-minute demo video following the Phase 6 screen order

---

## Interview prep checklist
Be ready to answer, with the screen open:
- Why this problem, and why for Japanese enterprises?
- How is technical health calculated? What are the weaknesses of the formula?
- Where does this yen figure come from?
- Why does the recommendation change when priorities change?
- What did the LLM do, and what did it NOT do? How do you prevent invented numbers?
- What would you do first for a real client, and how would you measure success in 6 months?
