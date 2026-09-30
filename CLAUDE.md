# ReArch — AI-Assisted Legacy Modernization Advisor

## What this project is
ReArch takes a real legacy Java codebase and produces a consulting-grade modernization recommendation:
diagnosis → modernization options → transparent business case → phased roadmap → executive brief.

It is a portfolio project for a Digital Consultant role at Accenture Japan. The audience is a
Manager/Director interviewer. Every feature must connect to a client decision, a business outcome,
or a transformation activity. Do not add technology because it is interesting.

## The one rule that matters most
**Deterministic facts first, AI interpretation second.**

- Python code computes every fact and every number: LOC, fan-in/fan-out, complexity, test presence,
  database coupling, outdated frameworks, effort, cost, scores, roadmap order.
- The LLM only explains, summarizes and writes prose from a JSON of facts it is given.
- The LLM never invents a number. Every number in LLM output must exist in its input
  (enforced by `llm/guard.py`; outputs that fail the check are regenerated or rejected).
- Every score and cost must be traceable: the UI can show the formula and inputs behind it.

## Stack
- `analyzer/` — Python 3.11, tree-sitter + tree-sitter-java, pom.xml parsing, git history (optional)
- `api/` — FastAPI, SQLite (via SQLModel), Pydantic schemas shared as the contract
- `web/` — Next.js (App Router) + TypeScript + Tailwind + shadcn/ui, React Flow (dependency graph), Recharts
- `llm/` — Claude API client, prompts in `llm/prompts/*.md`, number guard
- `config/assumptions.yaml` — every tunable weight and rate lives here, never hard-coded
- `fixtures/legacy-sample/` — a small deliberately-bad Java app with KNOWN expected findings, used by tests

## Domain model (keep names consistent)
- `Module` — a group of classes (by package). Has metrics, `technical_health` (0–100), `business_criticality` (1–3).
- `Finding` — one concrete issue with evidence (file, line, metric value).
- `Strategy` — one of `rehost | replatform | refactor | rearchitect | retire`, with cost/risk/time/value.
- `Priorities` — client weights for cost, risk, speed, long_term_value (sum to 1).
- `Recommendation` — chosen strategy per module given Priorities, with the scoring breakdown.
- `Wave` — a roadmap phase; modules ordered by dependencies (leaves first, strangler pattern).
- `Brief` — executive summary, EN and JA.

## Conventions
- Type everything (mypy-clean Python, strict TypeScript).
- Every analyzer metric has a pytest asserting the expected value on `fixtures/legacy-sample/`.
- Money is JPY, integers. Show assumptions next to every money figure in the UI.
- Keep functions small; no module over ~300 lines.
- Before finishing any task: run `make test` and `make lint`; fix failures.
- After each phase, update `docs/methodology.md` explaining in plain English how the numbers are produced.

## Commands
- `make dev` — run api (port 8000) and web (port 3000)
- `make test` — pytest + web type-check
- `make analyze REPO=<git url or path>` — run analyzer CLI, write JSON to `out/`
