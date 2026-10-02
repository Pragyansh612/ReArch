"""The assumptions a client may edit, with bounds and plain-English descriptions. Everything here is ILLUSTRATIVE.

Keys are dotted paths into config/assumptions.yaml (`engine`-level keys) or `roadmap.*`. Anything not listed is not editable
through the API (the model's structure and its formulas are fixed).
"""

from __future__ import annotations

from dataclasses import dataclass

STRATEGIES = ("rehost", "replatform", "refactor", "rearchitect", "retire")
LABEL = "ILLUSTRATIVE: not market data; calibrate against the client's own records"


@dataclass(frozen=True)
class Editable:
    key: str
    scope: str  # engine | roadmap
    path: tuple[str, ...]
    label: str
    unit: str
    minimum: float
    maximum: float
    description: str
    group: str
    nullable: bool = False


def _table() -> dict[str, Editable]:
    rows: list[Editable] = [
        Editable("daily_rate_jpy", "engine", ("daily_rate_jpy",), "Blended day rate", "JPY per day", 10_000, 500_000,
                 "What one person-day of delivery work costs the client. Prices every migration and all maintenance.", "rates"),
        Editable("tco.discount_rate", "engine", ("tco", "discount_rate"), "Discount rate", "per year", 0.0, 0.3,
                 "The client's cost of capital, used to bring future cash flows back to today.", "economics"),
        Editable("tco.maintenance_days_per_kloc_year", "engine", ("tco", "maintenance_days_per_kloc_year"), "Maintenance effort",
                 "days per KLOC per year", 0.0, 60.0, "Yearly maintenance effort per thousand code lines before the health penalty.",
                 "economics"),
        Editable("tco.run_cost_jpy_per_kloc_year", "engine", ("tco", "run_cost_jpy_per_kloc_year"), "Hosting and run cost",
                 "JPY per KLOC per year", 0.0, 2_000_000.0, "Yearly infrastructure cost per thousand code lines.", "economics"),
        Editable("change_cost.base_days_per_change", "engine", ("change_cost", "base_days_per_change"), "Effort per change request",
                 "days", 0.0, 30.0, "Effort of one change request in perfectly healthy code; worse health multiplies it.", "economics"),
        Editable("close_call_margin", "engine", ("close_call_margin",), "Close-call margin", "score points", 0.0, 50.0,
                 "A recommendation whose lead over the runner-up is below this is flagged as a close call.", "scoring"),
        Editable("cutover.big_bang.hours_per_kloc", "engine", ("cutover", "big_bang", "hours_per_kloc"), "Big-bang cutover time per KLOC",
                 "hours per KLOC", 0.0, 5.0, "How much longer a big-bang cutover window grows with each thousand lines.", "cutover"),
        Editable("cutover.incremental.slice_kloc", "engine", ("cutover", "incremental", "slice_kloc"), "Incremental slice size", "KLOC",
                 0.5, 50.0, "Size of one slice when a package is cut over incrementally (strangler).", "cutover"),
        Editable("cutover.incremental.hours_per_slice", "engine", ("cutover", "incremental", "hours_per_slice"), "Downtime per slice",
                 "hours", 0.0, 8.0, "Downtime of each incremental cutover event.", "cutover"),
        Editable("roadmap.teams", "roadmap", ("teams",), "Delivery teams", "teams", 1, 20, "Number of teams working in parallel.", "capacity"),
        Editable("roadmap.team_size_people", "roadmap", ("team_size_people",), "People per team", "people", 1, 50,
                 "Team size; capacity is teams x people.", "capacity"),
        Editable("roadmap.yearly_budget_cap_jpy", "roadmap", ("yearly_budget_cap_jpy",), "Yearly spend cap", "JPY per programme year",
                 1_000_000, 10**12, "Optional cap on programme spend per year; null means no cap.", "capacity", nullable=True),
    ]
    for s in STRATEGIES:
        rows.append(Editable(f"base_days_per_kloc.{s}", "engine", ("base_days_per_kloc", s), f"Effort per KLOC: {s}", "days per KLOC", 0.1,
                             300.0, f"Delivery effort per thousand code lines for {s}, before multipliers.", "effort"))
        rows.append(Editable(f"team_size.{s}", "engine", ("team_size", s), f"People needed: {s}", "people", 1, 50,
                             f"People a {s} package occupies; sets its duration.", "capacity"))
    for c in ("high", "medium", "low"):
        rows.append(Editable(f"coverage_uncertainty_buffer.{c}", "engine", ("coverage_uncertainty_buffer", c),
                             f"Effort buffer, {c} confidence", "multiplier", 1.0, 3.0,
                             "Extra effort planned when the analyzer can see little of the logic.", "effort"))
    return {r.key: r for r in rows}


EDITABLE: dict[str, Editable] = _table()

PRESET_DESCRIPTIONS = {
    "minimize_cost": "Weighs cost most heavily: prefers the option with the lowest total cost of ownership.",
    "minimize_risk": "Weighs delivery risk most heavily: prefers the safest change.",
    "speed_to_market": "Weighs duration most heavily: prefers the option that finishes soonest.",
    "long_term_value": "Weighs long-term value most heavily: prefers the option that removes the most debt for the client's objectives.",
    "balanced": "Weighs all four criteria equally.",
    "client_scenario": "The client's own priorities from the scenario (editable).",
}
