"""GET /explain/{number_id}: the formula, inputs and contribution behind any figure in a run.

A number's id is `{owner}:{doc}:{pointer}`: `owner` is the run id (docs `rec`, `roadmap.<profile>`) or the analysis id (doc `analysis`),
`pointer` is the RFC 6901 JSON pointer of the number inside that stored document. Ids are stable for identical inputs because the
run id is a hash of its inputs. The resolver walks the Pydantic schema to learn which model and field the number belongs to, then
looks the field up in SPECS. Fields without a specific formula still resolve, with a generic "recorded value" explanation that lists
the figures next to them, so every number in a run is explainable.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from analyzer.schema import AnalysisResult
from api.app.assumptions import LABEL
from api.app.errors import ApiError
from engine.roadmap.schema import Roadmap
from engine.schema import Recommendation

ROOT_MODELS: dict[str, type[BaseModel]] = {"rec": Recommendation, "roadmap": Roadmap, "analysis": AnalysisResult}


@dataclass(frozen=True)
class Spec:
    label: str
    formula: str
    plain: str = ""
    inputs: tuple[str, ...] = ()  # sibling fields; "a.b" = nested path; "sum:list.field" = sum over a list in the same object
    assumptions: tuple[str, ...] = ()  # dotted keys of the engine config (or roadmap.<key>)
    kind: str = "calculated"  # calculated | measured | input | configuration


def _s(label: str, formula: str, plain: str = "", inputs: tuple[str, ...] = (), assumptions: tuple[str, ...] = (), kind: str = "calculated") -> Spec:
    return Spec(label, formula, plain, inputs, assumptions, kind)


SPECS: dict[tuple[str, str], Spec] = {
    # --- technical health ---
    ("HealthComponent", "raw"): _s("Measured value", "the measured quantity for this component", "{raw} {raw_unit}; see 'how': {how}", kind="measured"),
    ("HealthComponent", "normalized"): _s("Normalized badness", "scaled to 0 (good) .. 1 (bad)", "{how}", ("raw",)),
    ("HealthComponent", "weight"): _s("Component weight", "from config health.weights", "How much this component counts in the 0-100 health score.",
                                      assumptions=("health.weights",), kind="configuration"),
    ("HealthComponent", "contribution_points"): _s("Points lost", "100 x weight x normalized", "{weight} x {normalized} x 100 points taken off 100.",
                                                   ("weight", "normalized")),
    ("ModuleHealth", "score"): _s("Technical health", "100 - sum of points lost", "100 minus the points lost across all components.",
                                  ("sum:components.contribution_points",)),
    ("Hotspot", "score"): _s("Hotspot score", "sum of weight x value over the components", "Weighted blend of the class's percentile ranks.",
                             ("sum:components.contribution",)),
    ("HotspotComponent", "contribution"): _s("Hotspot contribution", "weight x value", "", ("weight", "value")),
    # --- criticality ---
    ("CriticalityInputs", "inbound_share"): _s("Share of estate inbound references", "module inbound / estate inbound", "", ("inbound_total",)),
    ("CriticalityInputs", "write_share"): _s("Share of estate data writes", "module writes / estate writes", "", ("data_writes",)),
    ("CriticalityInputs", "score"): _s("Criticality score", "inbound_weight x inbound_share + write_weight x write_share",
                                       "score >= 0.30 gives 3, >= 0.12 gives 2, else 1.", ("inbound_share", "write_share"),
                                       ("criticality.inbound_weight", "criticality.write_weight")),
    ("Criticality", "value"): _s("Business criticality (1-3)", "the client override if given, else the heuristic",
                                 "A proposal the client confirms; overrides carry a written reason.", ("heuristic_value",)),
    # --- effort, cost, duration, risk, value ---
    ("EffortLine", "days"): _s("Effort line", "see the line's formula", "{formula}"),
    ("StrategyOption", "effort_days"): _s("Effort", "sum of the effort lines", "Core work plus any safety-net and parallel-run lines.", ("sum:effort_lines.days",)),
    ("StrategyOption", "migration_cost_jpy"): _s("Migration cost", "round(effort_days x daily_rate)", "Effort priced at the day rate, in whole yen.",
                                                 ("effort_days",), ("daily_rate_jpy",)),
    ("StrategyOption", "duration_months"): _s("Duration", "effort_days / (team_size x working_days_per_month)", "", ("effort_days", "team_size"),
                                              ("working_days_per_month",)),
    ("StrategyOption", "team_size"): _s("People needed", "from config team_size[strategy]", "", assumptions=("team_size",), kind="configuration"),
    ("StrategyOption", "risk_score"): _s("Delivery risk (0-100)", "min(100, base_risk x (1 + exposure_gain x exposure)); retain: retain_scale x 100 x exposure",
                                         "Exposure is the sum of the risk components.", ("base_risk", "sum:risk_components.contribution"),
                                         ("risk.exposure_gain", "retain.risk_scale")),
    ("StrategyOption", "base_risk"): _s("Inherent risk of the strategy", "from config risk.base[strategy]", "", assumptions=("risk.base",), kind="configuration"),
    ("StrategyOption", "cutover_events"): _s("Cutover events", "big bang: 1; incremental: ceil(KLOC / slice size)", "", assumptions=("cutover",)),
    ("StrategyOption", "cutover_hours_per_event"): _s("Downtime per cutover event",
                                                      "big bang: base hours + hours per KLOC x KLOC; incremental: hours per slice", "", assumptions=("cutover",)),
    ("StrategyOption", "cutover_total_hours"): _s("Total cutover downtime", "events x hours per event", "", ("cutover_events", "cutover_hours_per_event")),
    ("Component", "contribution"): _s("Risk factor contribution", "weight x measure", "", ("weight", "measure")),
    ("ValueBreakdown", "value"): _s("Long-term value (0-100)", "min(100, debt_reduction x burden x criticality_weight x objective_fit)", "",
                                    ("uncapped",)),
    ("ValueBreakdown", "uncapped"): _s("Value before the cap", "debt_reduction x burden x criticality_weight x objective_fit", "",
                                       ("debt_reduction", "burden", "criticality_weight", "objective_fit")),
    ("ValueBreakdown", "burden"): _s("Debt and maintenance burden", "0.6 x (100 - health) + 0.4 x min(100, 100 x KLOC / 30)", "",
                                     assumptions=("long_term_value.debt_weight", "long_term_value.maintenance_kloc_cap")),
    ("ValueBreakdown", "objective_fit"): _s("Objective fit", "sum of counted objective contributions", "How much of what the client cares about the strategy can move.",
                                            ("sum:objectives.contribution",)),
    ("ValueBreakdown", "debt_reduction"): _s("Debt reduction", "from config long_term_value.debt_reduction[strategy]", "",
                                             assumptions=("long_term_value.debt_reduction",), kind="configuration"),
    ("ValueBreakdown", "criticality_weight"): _s("Criticality weight", "from config long_term_value.criticality_weight[criticality]", "",
                                                 assumptions=("long_term_value.criticality_weight",), kind="configuration"),
    ("ObjectiveContribution", "contribution"): _s("Objective contribution", "weight x effect / sum of counted weights (0 if monetised in TCO)", "",
                                                  ("weight", "effect")),
    # --- TCO ---
    ("Tco", "tco_jpy"): _s("Total cost of ownership", "migration + sum over years (run + maintenance + change)", "", ("migration_total_jpy", "run_total_jpy",
                                                                                                                      "maintenance_total_jpy", "change_total_jpy")),
    ("Tco", "migration_total_jpy"): _s("Migration spend", "equals the option's migration cost, spread over its months", ""),
    ("Tco", "npv_cost_jpy"): _s("Present value of all outflows", "sum of year totals / (1 + discount rate)^year", "", ("tco_jpy",), ("tco.discount_rate",)),
    ("Tco", "savings_vs_retain_jpy"): _s("Saving against doing nothing", "retain TCO - this TCO", "", ("tco_jpy",)),
    ("Tco", "npv_vs_retain_jpy"): _s("NPV against doing nothing", "retain present value - this present value", "", ("npv_cost_jpy",), ("tco.discount_rate",)),
    ("Tco", "payback_year"): _s("Payback year", "first year the cumulative cost is no higher than retain's", "Absent if it never pays back within the horizon."),
    ("Tco", "change_savings_vs_retain_jpy"): _s("Change-cost benefit", "retain change cost - this change cost (separate benefit line)", "", ("change_total_jpy",),
                                                ("change_cost.base_days_per_change", "change_cost.health_penalty")),
    ("CashFlowYear", "total_jpy"): _s("Year total", "migration + run + maintenance + change", "", ("migration_jpy", "run_jpy", "maintenance_jpy", "change_jpy")),
    ("CashFlowYear", "maintenance_jpy"): _s("Yearly maintenance", "baseline x (1 - debt_reduction x share of the year after migration)", "",
                                            assumptions=("tco.maintenance_days_per_kloc_year", "tco.debt_maintenance_penalty", "daily_rate_jpy")),
    ("CashFlowYear", "run_jpy"): _s("Yearly run cost", "baseline x (1 - (1 - residual_run_cost) x share of the year after migration)", "",
                                    assumptions=("tco.run_cost_jpy_per_kloc_year", "tco.residual_run_cost")),
    ("CashFlowYear", "change_jpy"): _s("Yearly change cost", "baseline x (1 - (1 - change_factor) x share after migration)", "",
                                       assumptions=("change_cost.base_days_per_change", "change_cost.health_penalty")),
    # --- priorities and choice ---
    ("CriterionScore", "goodness"): _s("Goodness 0-1", "cost: 1 - tco/(3 x retain tco); speed: 1 - months/24; risk: 1 - risk/100; value: value/100", "",
                                       ("raw",), ("scoring.cost_ratio_ceiling", "scoring.duration_ceiling_months")),
    ("CriterionScore", "contribution"): _s("Score contribution", "100 x weight x goodness", "", ("weight", "goodness")),
    ("ScoredStrategy", "score"): _s("Strategy score", "sum of the criterion contributions", "", ("sum:criteria.contribution",)),
    ("StrategyChoice", "score"): _s("Winning score", "the best strategy's score", ""),
    ("StrategyChoice", "runner_up_score"): _s("Runner-up score", "the second-best strategy's score", ""),
    ("StrategyChoice", "margin"): _s("Margin over the runner-up", "winning score - runner-up score", "Below the close-call margin it is flagged.",
                                     ("score", "runner_up_score"), ("close_call_margin",)),
    ("Flip", "flip_value"): _s("Flip point", "nearest value of this assumption that changes the recommendation", "Found by search and bisection.", ("current_value",)),
    ("Flip", "change_pct"): _s("Size of the change", "|flip - current| / current x 100", "", ("current_value", "flip_value")),
    ("Overtake", "breakeven_jpy_per_year"): _s("Breakeven maintenance spend", "yearly maintenance at which this strategy overtakes the chosen one",
                                               "Searched between baseline/100 and baseline x 100."),
    ("Overtake", "multiple_of_baseline"): _s("Multiple of the baseline", "breakeven / baseline", "", ("breakeven_jpy_per_year",)),
    ("Breakeven", "baseline_jpy_per_year"): _s("Modelled yearly maintenance", "KLOC x days x (1 + penalty x (1 - health/100)) x day rate, or the client's figure", "",
                                               assumptions=("tco.maintenance_days_per_kloc_year", "daily_rate_jpy")),
    # --- packages, modules, estate ---
    ("WorkPackageReport", "loc"): _s("Code lines", "sum of the package's class LOC", "Code lines as counted by the analyzer (comments and blanks excluded).", kind="measured"),
    ("WorkPackageReport", "maintenance_baseline_jpy_per_year"): _s("Baseline maintenance", "KLOC x days x (1 + penalty x (1 - health/100)) x day rate",
                                                                   "Replaced by the client's own figure when one is supplied.", ("kloc",),
                                                                   ("tco.maintenance_days_per_kloc_year", "daily_rate_jpy")),
    ("WorkPackageReport", "change_requests_per_year"): _s("Change requests per year", "the module's figure x the package's LOC share", "", ("loc",), kind="input"),
    ("ModuleRollup", "tco_jpy"): _s("Module TCO", "sum of the chosen options' TCO over its packages", ""),
    ("ModuleRollup", "migration_cost_jpy"): _s("Module migration cost", "sum over its packages", ""),
    ("ProfileTotals", "total_tco_jpy"): _s("Estate TCO", "sum over packages of the chosen option's TCO", ""),
    ("ProfileTotals", "tco_savings_vs_retain_jpy"): _s("Estate saving", "retain TCO - chosen TCO", "", ("retain_tco_jpy", "total_tco_jpy")),
    ("ProfileTotals", "total_migration_cost_jpy"): _s("Estate migration cost", "sum over packages", ""),
    ("MaintenanceCalibration", "gap_pct"): _s("Model vs client gap", "gap / client figure x 100", "", ("gap_jpy", "client_reported_jpy"), ("calibration.gap_flag_pct",)),
    ("KpiReconciliation", "kpi_current_in_analysed_scope"): _s("KPI in the analysed scope", "whole-ERP KPI x analysed_scope_share", "", ("kpi_current", "analysed_scope_share"),
                                                                 kind="calculated"),
    # --- roadmap ---
    ("Item", "cost_jpy"): _s("Item cost", "the package's migration cost (foundations: effort x day rate)", "", ("effort_days",), ("daily_rate_jpy",)),
    ("Item", "start_month"): _s("Start month", "earliest month with dependencies done, capacity free and the yearly cap respected", "See the item's reason codes."),
    ("Item", "end_month"): _s("End month", "start + whole months needed - 1", "", ("start_month",)),
    ("Item", "people"): _s("People", "people the strategy needs, capped at the programme capacity", "", assumptions=("roadmap.teams", "roadmap.team_size_people")),
    ("PortfolioChoice", "weight"): _s("Value at stake (weight)", "package five-year do-nothing TCO / estate do-nothing TCO",
                                      "The portfolio objective weights each package's score by this share."),
    ("Portfolio", "total_score"): _s("Weighted portfolio score", "sum of weight x score over packages", "", ("total_unweighted_score",)),
    ("Downgrade", "weighted_score_lost"): _s("Objective lost to the budget", "package share x score lost", "", ("score_lost",)),
    ("Economics", "npv_vs_retain_jpy"): _s("Programme NPV against doing nothing", "present value of monthly (retain - roadmap - spend)", "", assumptions=("tco.discount_rate",)),
    ("Economics", "payback_quarter"): _s("Payback quarter", "first quarter-end where cumulative cost <= retain's after being behind", ""),
    ("Economics", "peak_investment_jpy"): _s("Peak investment", "largest cumulative shortfall against doing nothing", ""),
    ("Economics", "total_programme_cost_jpy"): _s("Programme cost", "migration and foundation spend inside the horizon", ""),
    ("QuarterPoint", "net_cumulative_jpy"): _s("Net position", "retain cumulative cost - roadmap cumulative cost", "", ("retain_cumulative_cost_jpy", "roadmap_cumulative_cost_jpy")),
    ("Wave", "cost_jpy"): _s("Wave cost", "sum of the item costs in the wave", ""),
    ("Opportunity", "available_from_month"): _s("Available from month", "month after the last prerequisite package is cut over", ""),
    # --- analysis facts ---
    ("ClassMetrics", "loc"): _s("Lines of code", "lines containing code (comments and blanks excluded)", "Same definition as cloc.", kind="measured"),
    ("ClassMetrics", "fan_in"): _s("Fan-in", "distinct analysed classes that reference this class", "", kind="measured"),
    ("ClassMetrics", "fan_out"): _s("Fan-out", "distinct analysed classes this class references", "", kind="measured"),
    ("ClassMetrics", "complexity"): _s("Complexity", "method bodies + decision points (if, for, while, case, catch, ?:, &&, ||)", "", kind="measured"),
    ("ClassMetrics", "service_fan_in"): _s("Service fan-in", "services.xml entries pointing at this class", "", kind="measured"),
    ("ClassMetrics", "controller_fan_in"): _s("Controller fan-in", "controller.xml events pointing at this class", "", kind="measured"),
}

GENERIC_NOTE = "A value recorded in the output; the figures next to it show what it was computed from."


def _unwrap(ann: Any) -> Any:
    origin = get_origin(ann)
    if origin in (typing.Union, types.UnionType):
        rest = [a for a in get_args(ann) if a is not type(None)]
        return _unwrap(rest[0]) if rest else Any
    if origin is typing.Literal:
        return Any
    if origin is list:
        return ("list", _unwrap(get_args(ann)[0]))
    if origin is dict:
        return ("dict", _unwrap(get_args(ann)[1]))
    return ann


def locate(root: type[BaseModel], parts: list[str]) -> tuple[str, str, int]:
    """(owner model, field, parts the leaf sits below its owning object). Walks the schema along the pointer."""
    node: Any = root
    owner, field, in_collection = root.__name__, "", 0
    for part in parts:
        if isinstance(node, type) and issubclass(node, BaseModel):
            if part not in node.model_fields:
                break
            owner, field, in_collection = node.__name__, part, 0
            node = _unwrap(node.model_fields[part].annotation)
        elif isinstance(node, tuple):
            node, in_collection = node[1], in_collection + 1
        else:
            in_collection += 1
    return owner, field, in_collection


def _unescape(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def parse_id(number_id: str) -> tuple[str, str, list[str]]:
    try:
        owner, doc, pointer = number_id.split(":", 2)
    except ValueError as exc:
        raise ApiError(422, "bad_number_id", "a number id looks like '<run>:<doc>:<json pointer>'") from exc
    if not pointer.startswith("/"):
        raise ApiError(422, "bad_number_id", "the pointer must start with '/'")
    return owner, doc, [_unescape(p) for p in pointer[1:].split("/")]


def make_id(owner: str, doc: str, parts: Sequence[str | int]) -> str:
    return f"{owner}:{doc}:/" + "/".join(_escape(str(p)) for p in parts)


def _get(doc: Any, parts: list[str]) -> Any:
    for p in parts:
        try:
            doc = doc[int(p)] if isinstance(doc, list) else doc[p]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ApiError(404, "not_found", "no number at that pointer") from exc
    return doc


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _resolve_input(container: dict[str, Any], expr: str) -> tuple[Any, str | None]:
    if expr.startswith("sum:"):
        path = expr[4:].split(".")
        items = container.get(path[0], [])
        return sum(i.get(path[1], 0) for i in items if isinstance(i, dict)), path[0]
    cur: Any = container
    for p in expr.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None, None
        cur = cur[p]
    return cur, expr


def _assumption(rec_doc: dict[str, Any] | None, roadmap_doc: dict[str, Any] | None, key: str) -> Any:
    if key.startswith("roadmap.") and roadmap_doc is not None:
        cur: Any = roadmap_doc.get("assumptions", {}).get("roadmap", {})
        key = key[len("roadmap."):]
    elif rec_doc is not None:
        cur = rec_doc.get("assumptions", {}).get("config", {})
    else:
        return None
    for p in key.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def explain(number_id: str, docs: dict[str, dict[str, Any]], rec_doc: dict[str, Any] | None) -> dict[str, Any]:
    """`docs` maps doc name -> stored document; `rec_doc` supplies the assumptions echo."""
    owner, doc_name, parts = parse_id(number_id)
    base = doc_name.split(".", 1)[0]
    if base not in ROOT_MODELS or doc_name not in docs:
        raise ApiError(404, "not_found", f"unknown document '{doc_name}'")
    document = docs[doc_name]
    value = _get(document, parts)
    if not _num(value):
        raise ApiError(422, "not_a_number", "that pointer does not hold a number")
    model_owner, field, below = locate(ROOT_MODELS[base], parts)
    cont_parts = parts[: len(parts) - (1 + below)] if below == 0 else parts[: len(parts) - below]
    container = _get(document, cont_parts) if cont_parts else document
    if not isinstance(container, dict):
        container = {}
    spec = SPECS.get((model_owner, field))
    siblings = {k: v for k, v in container.items() if _num(v) and k != field}
    inputs: list[dict[str, Any]] = []
    if spec is not None:
        for expr in spec.inputs:
            val, _ = _resolve_input(container, expr)
            if val is not None:
                inputs.append({"name": expr, "value": val, "id": make_id(owner, doc_name, [*cont_parts, *expr.split(".")]) if not expr.startswith("sum:") and _num(val) else None})
    else:
        inputs = [{"name": k, "value": v, "id": make_id(owner, doc_name, [*cont_parts, k])} for k, v in sorted(siblings.items())[:8]]
    context = {k: v for k, v in container.items() if not isinstance(v, (dict, list))}
    try:
        plain = (spec.plain if spec and spec.plain else GENERIC_NOTE).format_map(_Safe(context))
    except (ValueError, IndexError, KeyError):
        plain = spec.plain if spec else GENERIC_NOTE
    assumptions = [{"key": k, "value": _assumption(rec_doc, document if base == "roadmap" else None, k), "label": LABEL}
                   for k in (spec.assumptions if spec else ())]
    contribution = None
    if field in ("contribution_points", "contribution") and below == 0 and cont_parts:
        parent = _get(document, cont_parts[:-1]) if len(cont_parts) > 1 else None
        if isinstance(parent, list):
            total = sum(i.get(field, 0) for i in parent if isinstance(i, dict))
            contribution = {"of": field, "share_of_total": round(value / total, 6) if total else None, "total": total}
    return {"id": number_id, "value": value, "doc": doc_name, "pointer": "/" + "/".join(_escape(p) for p in parts), "owner_model": model_owner,
            "field": field, "label": spec.label if spec else f"{model_owner}.{field}", "kind": spec.kind if spec else "recorded",
            "formula": spec.formula if spec else f"recorded value of {model_owner}.{field}", "plain_english": plain, "inputs": inputs,
            "assumptions": assumptions, "contribution": contribution, "specific": spec is not None}


class _Safe(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def numeric_leaves(doc: Any, path: list[str] | None = None) -> list[list[str]]:
    """Every pointer (as parts) in a stored document that holds a number."""
    path = path or []
    if _num(doc):
        return [path]
    out: list[list[str]] = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            out += numeric_leaves(v, [*path, str(k)])
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out += numeric_leaves(v, [*path, str(i)])
    return out
