# ReArch API

FastAPI + SQLite (SQLModel). Run it with `make serve` (or `make dev` for API + web). `DEMO_MODE=1 make serve` serves the preloaded analyses
and refuses to clone anything. The contract is `docs/openapi.json`; `make types` regenerates `web/src/lib/api-types.ts` from it, and the web app
uses only those types. Interactive docs: `/docs`.

All money is whole JPY. **Every assumption is ILLUSTRATIVE and the client scenario is fictional**; responses carry that label wherever an
assumption appears.

## Running and configuration

| Setting (env) | Default | Meaning |
|---|---|---|
| `DEMO_MODE` | off | disables `POST /analyses`; on start-up an empty database is seeded from `data/demo/*.json.gz` |
| `DATA_DIR` | `data/` | database (`rearch.db`) and stored analyses (git-ignored except `data/demo/`) |
| `DATABASE_URL` | sqlite file in `DATA_DIR` | any SQLAlchemy URL |
| `CORS_ORIGIN` | – | extra allowed origin(s), comma separated; `http://localhost:3000` is always allowed |
| `PATH_ROOTS` | `targets/:fixtures/` | roots (colon separated) under which a server path may be analysed |

`make seed` loads the committed demo analyses into the database; `make demo-data` rebuilds them from `out/`; `make openapi` / `make types` export
the contract and the TypeScript types.

## Data model
- **Analysis**: immutable analyzer output (stored compressed under `DATA_DIR/analyses/`), with status.
- **ScenarioVersion**: versioned scenario for an analysis: priorities, objective weights, budget, planning horizon, downtime limits, criticality
  overrides (each with a written reason), client-reported maintenance per module, change requests per module, analysed-scope share, and the editable
  assumptions. A `PUT` that changes nothing creates no version.
- **Run**: the recommendation for (analysis x effective inputs), cached by a hash of those inputs; its id is the first 16 hex characters of the hash.
- **RunArtifact**: roadmaps per profile and the sensitivity result.

## Endpoints

| Method and path | What it does |
|---|---|
| `POST /analyses` | `{repo, scope, name}`: a background job (202). `repo` is an https git URL or an absolute server path under a configured root. Disabled in demo mode (403). |
| `GET /analyses/{id}/status` | poll: `queued`, `cloning`, `analyzing`, `done`, `failed` (with a message and elapsed seconds) |
| `GET /analyses` | all analyses |
| `GET /analyses/{id}` | summary: totals, per-module coverage and confidence, findings by kind, broken references, cycles, god classes, dependency counts, scenario version and run id |
| `GET /analyses/{id}/modules` | filter `min_loc`, `confidence`, `has_tests`; sort `name|loc|health|class_count`; `limit`, `offset` |
| `GET /analyses/{id}/packages` | work packages; filter `module`, `kind`; sort `id|loc|health|class_count` |
| `GET /analyses/{id}/classes` | filter `q`, `module`, `package`, `tier`, `used`, `min_loc`; sort `hotspot|loc|complexity|fan_in|fan_out|name`; paging |
| `GET /analyses/{id}/classes/{name}` | metrics, findings with file and line evidence, database-coupling instances, legacy markers, service and controller references, edges; `name` is a fully qualified or unique simple name (409 if ambiguous) |
| `GET /analyses/{id}/graph?level=module|package|class&limit=` | React Flow shaped `nodes` (`id`, `type`, `position`, `data` with a health band) and `edges`; capped at `limit` nodes (highest weight kept), `truncated` says if it was cut |
| `GET /analyses/{id}/scenario?version=` | the scenario state and the version list |
| `PUT /analyses/{id}/scenario` | partial edit (merged; maps merge by key and `null` removes a key). Validates; a change creates a new version and **recomputes synchronously** without re-analysing |
| `GET /analyses/{id}/recommendation?profile=&version=` | the full recommendation with every breakdown, one profile's choices (estate totals for all profiles stay) |
| `GET /analyses/{id}/roadmap?profile=&version=` | portfolio (unconstrained and constrained, downgrades), waves, Gantt-ready items, economics, unlocks and headline findings |
| `GET /analyses/{id}/sensitivity` | flip points and breakevens per package; computed on first request if the background job has not finished |
| `POST /analyses/{id}/whatif` | same body as the scenario `PUT` (+ optional `profile`): computes without persisting anything and returns the result summary, a diff against the current scenario (changed picks, change in migration cost, TCO saving, NPV, peak investment, finish month, payback) and `cache_hit` |
| `GET /explain/{number_id}` | formula, inputs, assumptions and contribution for any number in a run or analysis |
| `GET /presets` | the scoring profiles with descriptions and weights |
| `GET /assumptions?analysis_id=` | the editable assumptions with description, unit, bounds, default and (with `analysis_id`) current value |
| `GET /health` | `{status, mode}` |

Profiles: `minimize_cost`, `minimize_risk`, `speed_to_market`, `long_term_value`, `balanced` and `client_scenario` (the default). Custom weights are
tried through `whatif` (`priorities`).

## Number ids and `/explain`
Every number is addressable as `<owner>:<doc>:<JSON pointer>` where the pointer (RFC 6901: `~1` for `/`) locates the number inside the stored document:
`<run id>:rec:/work_packages/order~1cycle-1/options/3/tco/tco_jpy`, `<run id>:roadmap.<profile>:/economics/npv_vs_retain_jpy`,
`<analysis id>:analysis:/classes/<fqn>/loc`. Responses carry `run.number_id_prefix` (or `number_id_prefix` on class detail and the analysis summary);
a number's id is that prefix plus its pointer without the leading slash. Ids are stable for identical inputs (the run id is an input hash) and unaffected
by the `profile` filter. `/explain` returns `label`, `kind` (`calculated`, `measured`, `input`, `configuration`, `recorded`), `formula`,
`plain_english`, `inputs` (with ids, so the UI can drill down), `assumptions` (value and ILLUSTRATIVE label) and `contribution` (share of the parent total).

## Scenario editing and validation
Bounds are enforced and reported in one error format. Weights must sum to 1 and each lie in 0..1; budget 1 million to 1 trillion JPY; horizon 1 to 10 years;
downtime limits 0 to 72 hours; criticality 1 to 3 with a written reason of at least 10 characters; module names must exist in the analysis; and only the
assumptions listed by `GET /assumptions` can be edited, each within its bounds. A rejected edit never creates a version.

## Errors
Every failure has the shape `{"error": {"code", "message", "details"}}` (codes such as `not_found`, `validation_error`, `demo_mode`, `invalid_repo`,
`path_not_allowed`, `analysis_not_ready`, `unknown_profile`, `bad_number_id`).

## Security and limits
`POST /analyses` accepts only plain `https://` git URLs (no credentials, no `file://`, no leading dashes) or server paths under `PATH_ROOTS`; the scope may not
contain `..` or absolute paths; names are restricted to `[A-Za-z0-9._-]`. Clones are shallow with a time limit (120 s) and a size limit (400 MB);
analysis runs in a subprocess with a time limit (300 s) and a class limit (25,000). **A public deployment should run with `DEMO_MODE=1`**: cloning
arbitrary repositories on a public server is a security risk.

## Performance (OFBiz demo data, real HTTP on a development laptop, `python scripts/measure_api.py`)

| Request | Median |
|---|---|
| `PUT /scenario` (new version, full recompute, default roadmap built and stored) | 108 ms (74-144 ms; server-side 101 ms) |
| `POST /whatif` | 50 ms |
| `GET /recommendation` (one profile, 361 KB) | 8 ms |
| `GET /roadmap` (cached) / first build for another profile | 4 ms / 34 ms |
| `GET /classes`, `GET /graph?level=class`, `GET /explain` | 2-4 ms |
| Flip points and breakevens (background, separate process) | ready about 9 s after start-up |

Where the time goes: the engine itself recomputes all 15 packages and 6 profiles in about 25 ms. The first API version took 170-210 ms because PyYAML parsed the
configuration files six times per request (about 70% of the time); parsing is now cached by file modification time. The remainder is serialising and compressing
the 1 MB recommendation, building and storing the default roadmap (about 30 ms) and the database writes. The flip/breakeven search is the slow part (about 4 s)
and is kept off the request path: it first ran in the web process, where it held the interpreter lock and slowed concurrent requests to several seconds, so it
now runs in a separate process, debounced to the latest run of an analysis.

## Demo data
`data/demo/ofbiz.json.gz` is 61 KB (the analysis is 1.5 MB uncompressed) and `legacy-sample.json.gz` is 5 KB, so deployment needs no OFBiz clone.
`manifest.json` records the repo, commit and scope. Refresh with `make analyze ...` then `make demo-data`.

## Tests
`api/tests/test_api.py`: end to end on the fixture, versioning, what-if persists nothing, cache hits (including a reverted scenario reusing its run), demo mode,
validation (one case per rule), unsafe repos, job limits, every number in a run explainable, listing/filtering/graph, presets/assumptions, CORS, the OpenAPI
contract, and the background sensitivity process (superseded runs are skipped).
