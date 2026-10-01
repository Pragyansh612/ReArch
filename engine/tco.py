"""Total cost of ownership over the client's planning horizon, with the do-nothing (retain) baseline."""

from __future__ import annotations

from engine.schema import CashFlowYear, Tco


def migration_by_year(cost: int, duration_months: float, horizon: int) -> list[int]:
    """Migration spend spread evenly over the migration months; the last active year takes the rounding remainder."""
    if cost == 0:
        return [0] * horizon
    if duration_months <= 0:
        return [cost] + [0] * (horizon - 1)
    shares = [max(0.0, min(12.0 * t, duration_months) - 12.0 * (t - 1)) / duration_months for t in range(1, horizon + 1)]
    out = [round(cost * s) for s in shares]
    last = max(i for i, s in enumerate(shares) if s > 0)
    out[last] += cost - sum(out)
    return out


def post_migration_fraction(year: int, duration_months: float) -> float:
    """Share of the year (1-based) that falls after the migration has finished (savings only start then)."""
    return min(1.0, max(0.0, (12.0 * year - duration_months) / 12.0))


Row = tuple[int, int, int, int]  # (year, migration, run, maintenance) in whole yen


def tco_rows(*, maintenance_year: float, run_year: float, migration_cost: int, duration_months: float,
             reduction: float, run_factor: float, horizon: int) -> list[Row]:
    """Yearly cash flows. maintenance after migration = baseline x (1 - reduction); run = baseline x run_factor."""
    mig = migration_by_year(migration_cost, duration_months, horizon)
    rows: list[Row] = []
    for t in range(1, horizon + 1):
        f = post_migration_fraction(t, duration_months)
        rows.append((t, mig[t - 1], round(run_year * (1.0 - (1.0 - run_factor) * f)),
                     round(maintenance_year * (1.0 - reduction * f))))
    return rows


def total(row: Row) -> int:
    return row[1] + row[2] + row[3]


def tco_of(rows: list[Row]) -> int:
    return sum(total(r) for r in rows)


def npv_of(rows: list[Row], discount_rate: float) -> int:
    return round(sum(total(r) / (1.0 + discount_rate) ** r[0] for r in rows))


def payback_year(rows: list[Row], retain_rows: list[Row]) -> int | None:
    """First year in which the option's cumulative cost is no higher than doing nothing."""
    cumulative = 0
    for mine, base in zip(rows, retain_rows, strict=True):
        cumulative += total(base) - total(mine)
        if cumulative >= 0:
            return mine[0]
    return None


def to_model(rows: list[Row], *, maintenance_year: float, run_year: float, discount_rate: float,
             retain_rows: list[Row] | None) -> Tco:
    tco, npv = tco_of(rows), npv_of(rows, discount_rate)
    base_tco, base_npv = (tco_of(retain_rows), npv_of(retain_rows, discount_rate)) if retain_rows else (tco, npv)
    return Tco(
        horizon_years=len(rows), discount_rate=discount_rate, baseline_maintenance_jpy_per_year=maintenance_year,
        baseline_run_jpy_per_year=run_year,
        yearly=[CashFlowYear(year=r[0], migration_jpy=r[1], run_jpy=r[2], maintenance_jpy=r[3], total_jpy=total(r))
                for r in rows],
        migration_total_jpy=sum(r[1] for r in rows), run_total_jpy=sum(r[2] for r in rows),
        maintenance_total_jpy=sum(r[3] for r in rows), tco_jpy=tco, npv_cost_jpy=npv,
        savings_vs_retain_jpy=base_tco - tco, npv_vs_retain_jpy=base_npv - npv,
        payback_year=payback_year(rows, retain_rows) if retain_rows else None)
