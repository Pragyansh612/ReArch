"""Deterministic resource-constrained scheduler: dependencies, team capacity, optional yearly budget, quick wins first."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine.roadmap.schema import ReasonCode


@dataclass
class Job:
    id: str
    kind: str  # foundation | package
    name: str
    people: int
    effort_days: float
    cost: int
    duration: int  # whole months, >= 1
    package_id: str | None = None
    module: str | None = None
    strategy: str | None = None
    deps: set[str] = field(default_factory=set)  # job ids that must END before this job starts
    group: str = ""
    quick: bool = False
    value_per_risk: float = 0.0
    codes: list[ReasonCode] = field(default_factory=list)
    cutover: tuple[str, int, float] = ("none", 0, 0.0)
    formula: str | None = None


@dataclass
class Placement:
    start: int
    end: int
    extra_codes: list[ReasonCode]


def duration_months(effort_days: float, people: int, working_days: float) -> int:
    return max(1, math.ceil(effort_days / (people * working_days) - 1e-9))


def monthly_spend(cost: int, months: int) -> list[int]:
    base = cost // months
    out = [base] * months
    out[-1] += cost - base * months
    return out


class Ledger:
    def __init__(self, capacity: int, yearly_cap: int | None) -> None:
        self.capacity, self.cap = capacity, yearly_cap
        self.people: dict[int, int] = {}
        self.year_spend: dict[int, int] = {}

    def blocker(self, start: int, jobs: list[Job]) -> str | None:
        """None if every job fits when started at `start`; else 'capacity' or 'budget'."""
        add_people: dict[int, int] = {}
        add_year: dict[int, int] = {}
        for j in jobs:
            for k, spend in enumerate(monthly_spend(j.cost, j.duration)):
                m = start + k
                add_people[m] = add_people.get(m, 0) + j.people
                y = (m - 1) // 12
                add_year[y] = add_year.get(y, 0) + spend
        if any(self.people.get(m, 0) + p > self.capacity for m, p in add_people.items()):
            return "capacity"
        if self.cap is not None and any(self.year_spend.get(y, 0) + s > self.cap for y, s in add_year.items()):
            return "budget"
        return None

    def add(self, start: int, job: Job) -> None:
        for k, spend in enumerate(monthly_spend(job.cost, job.duration)):
            m = start + k
            self.people[m] = self.people.get(m, 0) + job.people
            self.year_spend[(m - 1) // 12] = self.year_spend.get((m - 1) // 12, 0) + spend


def _place(ledger: Ledger, jobs: list[Job], ready: int, horizon: int) -> tuple[int, str | None] | None:
    """Earliest start >= ready where all jobs fit together. Returns (start, why it could not start at `ready`)."""
    first_block: str | None = None
    for s in range(ready, horizon + 1):
        block = ledger.blocker(s, jobs)
        if block is None:
            return s, first_block
        first_block = first_block or block
    return None


def schedule(jobs: list[Job], groups: list[list[str]], capacity: int, yearly_cap: int | None,
             horizon: int) -> tuple[dict[str, Placement], dict[str, list[ReasonCode]]]:
    """Quick wins first, then foundations, then the remaining package groups by value per risk."""
    by_id = {j.id: j for j in jobs}
    ledger = Ledger(capacity, yearly_cap)
    placed: dict[str, Placement] = {}
    failed: dict[str, list[ReasonCode]] = {}
    pending = [g for g in groups]
    while pending:
        ready_groups = [g for g in pending if all(d in placed or d in failed for jid in g for d in by_id[jid].deps)]
        if not ready_groups:  # cannot happen for a DAG of groups; never drop jobs silently
            for g in pending:
                for jid in g:
                    failed[jid] = [ReasonCode(code="CIRCULAR_DEPENDENCY", detail="dependencies of this group never resolve")]
            break
        def key(g: list[str]) -> tuple[int, float, str]:
            members = [by_id[m] for m in g]
            # quick wins first (they need no foundations and build confidence), then foundations, then the rest by value per risk
            return (1 if by_id[g[0]].kind == "foundation" else 0 if any(x.quick for x in members) else 2,
                    -max(x.value_per_risk for x in members), g[0])
        group = min(ready_groups, key=key)
        pending.remove(group)
        members = [by_id[jid] for jid in sorted(group)]
        blocked_deps = [d for j in members for d in j.deps if d in failed]
        if blocked_deps:
            for j in members:
                failed[j.id] = [ReasonCode(code="DEPENDS_ON_UNSCHEDULED", detail=", ".join(sorted(set(blocked_deps))))]
            continue
        ready = max([1] + [placed[d].end + 1 for j in members for d in j.deps])
        atomic = len(members) == 1 or sum(j.people for j in members) <= capacity
        if atomic:
            hit = _place(ledger, members, ready, horizon)
            if hit is None:
                for j in members:
                    failed[j.id] = [ReasonCode(code="NO_SLOT_WITHIN_HORIZON", detail=f"no month up to {horizon} fits capacity and budget")]
                continue
            start, why = hit
            for j in members:
                code = [] if start == ready else [ReasonCode(code="BUDGET_CAP" if why == "budget" else "CAPACITY",
                                                             detail=f"could not start at month {ready}; started at month {start}")]
                ledger.add(start, j)
                placed[j.id] = Placement(start, start + j.duration - 1, code)
        else:  # entangled group too big to run at once: stagger members, flag it
            for j in sorted(members, key=lambda x: (not x.quick, -x.value_per_risk, x.id)):
                hit = _place(ledger, [j], ready, horizon)
                if hit is None:
                    failed[j.id] = [ReasonCode(code="NO_SLOT_WITHIN_HORIZON", detail=f"no month up to {horizon} fits")]
                    continue
                start, _why = hit
                ledger.add(start, j)
                placed[j.id] = Placement(start, start + j.duration - 1, [ReasonCode(
                    code="ENTANGLED_STAGGERED", detail="entangled packages need more people than the capacity allows at once; "
                                                      "staggered, with cutover held until the whole group is built")])
    return placed, failed
