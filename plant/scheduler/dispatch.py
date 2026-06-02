"""
Dispatching-baseline scheduler (M2).

A transparent priority list-scheduler. At each step it picks the highest-priority
ready operation (by the chosen rule) and places it at the earliest time a slot on
its resource is free and the job's previous op has finished. This guarantees:

  * routing precedence — a job's op N+1 never starts before op N ends;
  * resource capacity — a resource runs at most `capacity` operations at once.

It does NOT claim optimality and does not assign workers — that is the CP-SAT
solver's job (M3), where hard-constraint enforcement lives. The baseline exists to
keep the solver honest and to give an explainable plan to compare against.
"""

from __future__ import annotations

import enum
import heapq
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from plant.model.models import Job, Operation, Schedule, ScheduledOp


class Rule(enum.Enum):
    EDD = "edd"  # earliest due date
    SPT = "spt"  # shortest processing time
    CR = "cr"  # critical ratio


@dataclass
class _JobState:
    job: Job
    ops: list[Operation]
    due_ts: float
    next_idx: int = 0
    ready_minute: int = 0  # earliest minute the next op may start

    @property
    def done(self) -> bool:
        return self.next_idx >= len(self.ops)

    @property
    def current(self) -> Operation:
        return self.ops[self.next_idx]

    @property
    def remaining_minutes(self) -> int:
        return sum(o.duration_minutes for o in self.ops[self.next_idx :])


@dataclass(order=True)
class _Candidate:
    key: tuple
    state: _JobState = field(compare=False)


def _priority_key(state: _JobState, rule: Rule, horizon_ts: float) -> tuple:
    """Lower sorts first (higher priority). Job pk is the deterministic tie-break."""
    op = state.current
    if rule is Rule.EDD:
        primary: float = state.due_ts
    elif rule is Rule.SPT:
        primary = op.duration_minutes
    else:  # Rule.CR — critical ratio: time-until-due over remaining work; less = more urgent
        time_to_due = state.due_ts - horizon_ts
        primary = time_to_due / max(state.remaining_minutes, 1)
    return (primary, state.job.pk)


@transaction.atomic
def run_baseline(rule: Rule = Rule.EDD) -> Schedule:
    """Build and persist a feasible baseline Schedule over every Job in the database."""
    now = timezone.now()
    horizon_ts = now.timestamp()
    schedule = Schedule.objects.create(
        kind=Schedule.Kind.BASELINE, feasible=True, objective_value=0, horizon_start=now
    )

    states = [
        _JobState(
            job=job,
            ops=list(job.routing.operations.select_related("resource")),
            due_ts=job.due_date.timestamp(),
        )
        for job in Job.objects.select_related("routing")
    ]
    states = [s for s in states if s.ops]  # ignore empty routings

    # Each resource has `capacity` parallel slots; the heap holds their free-times.
    resource_slots: dict[int, list[int]] = {}
    for state in states:
        for op in state.ops:
            resource_slots.setdefault(op.resource_id, [0] * op.resource.capacity)

    rows = []
    remaining = sum(1 for s in states for _ in s.ops)
    while remaining:
        # Pick the highest-priority operation among all jobs that still have work.
        candidates = [
            _Candidate(key=_priority_key(s, rule, horizon_ts), state=s)
            for s in states
            if not s.done
        ]
        chosen = min(candidates).state
        op = chosen.current

        slots = resource_slots[op.resource_id]
        slot_free = slots[0]
        start = max(chosen.ready_minute, slot_free)
        end = start + op.duration_minutes
        heapq.heapreplace(slots, end)  # this slot is now busy until `end`

        rows.append(
            ScheduledOp(
                schedule=schedule,
                job=chosen.job,
                operation=op,
                resource=op.resource,
                worker=None,
                start_minute=start,
                end_minute=end,
            )
        )
        chosen.ready_minute = end
        chosen.next_idx += 1
        remaining -= 1

    ScheduledOp.objects.bulk_create(rows)
    return schedule
