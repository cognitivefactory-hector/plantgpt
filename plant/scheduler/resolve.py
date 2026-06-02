"""
Disruption re-solve + diff (M4).

When the floor changes — a machine goes down, a hot job arrives — we re-solve with
CP-SAT and diff the new plan against the old one, so a planner sees what the change
costs (which jobs slip, by how much, the tardiness delta) *before* committing it.

The re-solve always goes through the constraint solver, so a disruption response can
never violate a hard constraint — the same safety core as everywhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from plant.model.models import Job, MaintenanceWindow, Resource, Schedule
from plant.scheduler.cpsat import run_cpsat


def completion_by_job(schedule: Schedule) -> dict[int, int]:
    """Each job's completion minute = the end of its last scheduled operation."""
    completions: dict[int, int] = {}
    for so in schedule.scheduled_ops.all():
        completions[so.job_id] = max(completions.get(so.job_id, 0), so.end_minute)
    return completions


@dataclass
class ScheduleDiff:
    """Per-job completion change between two schedules (same horizon origin assumed)."""

    completion_before: dict[int, int]
    completion_after: dict[int, int]

    @property
    def deltas(self) -> dict[int, int]:
        """job_id -> (after - before) completion minutes; positive means it slipped."""
        jobs = set(self.completion_before) | set(self.completion_after)
        return {j: self.completion_after.get(j, 0) - self.completion_before.get(j, 0) for j in jobs}

    @property
    def slipped_job_ids(self) -> list[int]:
        return [j for j, d in self.deltas.items() if d > 0]

    @property
    def improved_job_ids(self) -> list[int]:
        return [j for j, d in self.deltas.items() if d < 0]


def diff_schedules(before: Schedule, after: Schedule) -> ScheduleDiff:
    return ScheduleDiff(
        completion_before=completion_by_job(before),
        completion_after=completion_by_job(after),
    )


def weighted_tardiness(schedule: Schedule, origin: datetime) -> float:
    """Σ priority_weight · tardiness over the schedule, using current job due dates.

    Reads each job's due date and weight live, so capture this *before* a disruption
    mutates them (for the 'before' value) and *after* (for the 'after' value)."""
    completions = completion_by_job(schedule)
    total = 0.0
    for job in Job.objects.filter(id__in=completions):
        due_min = (job.due_date - origin).total_seconds() / 60
        total += job.priority_weight * max(0.0, completions[job.id] - due_min)
    return total


# --- Disruptions: each returns a zero-arg callable that mutates the plant. ---


def machine_down(resource: Resource, start: datetime, end: datetime) -> Callable[[], None]:
    """A resource goes down for [start, end) — added as a maintenance window."""

    def _apply() -> None:
        MaintenanceWindow.objects.create(resource=resource, start=start, end=end)

    return _apply


def expedite(job: Job, *, new_due: datetime | None = None) -> Callable[[], None]:
    """Pull a job forward: mark it AOG (high priority weight) and, optionally, move
    its due date in so the solver actually races it to the front."""

    def _apply() -> None:
        job.is_aog = True
        if new_due is not None:
            job.due_date = new_due
        job.save(update_fields=["is_aog", "due_date"])

    return _apply


@dataclass
class Resolution:
    before: Schedule
    after: Schedule
    diff: ScheduleDiff
    weighted_tardiness_before: float
    weighted_tardiness_after: float


def resolve(
    apply_disruption: Callable[[], None],
    *,
    time_limit_s: float = 10.0,
    horizon_start: datetime | None = None,
) -> Resolution:
    """Solve the current plant, apply the disruption, re-solve, and diff the two.

    Both solves share one horizon origin so completions are directly comparable. The
    re-solve always goes through CP-SAT, so the response can never break a hard
    constraint. (The disruption is applied to the plant; the M6 propose layer adds
    the approve/reject gate on top.)
    """
    origin = horizon_start or timezone.now()
    before = run_cpsat(time_limit_s=time_limit_s, horizon_start=origin)
    tardiness_before = weighted_tardiness(before, origin)

    apply_disruption()

    after = run_cpsat(time_limit_s=time_limit_s, horizon_start=origin)
    tardiness_after = weighted_tardiness(after, origin)

    return Resolution(
        before=before,
        after=after,
        diff=diff_schedules(before, after),
        weighted_tardiness_before=tardiness_before,
        weighted_tardiness_after=tardiness_after,
    )
