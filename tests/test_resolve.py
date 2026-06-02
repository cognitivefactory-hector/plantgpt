"""
M4 disruption re-solve + diff (TDD).

A disruption (machine down, hot job / expedite) is applied, the plant is re-solved
by CP-SAT, and the result is diffed against the prior schedule so a planner can see
exactly what the change costs — what slips, by how much — *before* committing it.
This is the data behind challenge #6: "show me a change you recommended against."
"""

from datetime import UTC, datetime, time, timedelta

import pytest

from plant.data.sample import build_expedite_trap
from plant.model.models import (
    Job,
    MaintenanceWindow,
    Operation,
    Resource,
    Routing,
    Schedule,
    ScheduledOp,
    Shift,
    Worker,
)
from plant.scheduler.resolve import diff_schedules, expedite, machine_down, resolve


def _persisted_schedule(job, op, res, start, end):
    sched = Schedule.objects.create(
        kind=Schedule.Kind.CPSAT,
        feasible=True,
        objective_value=0,
        horizon_start=datetime(2030, 1, 7, tzinfo=UTC),
    )
    ScheduledOp.objects.create(
        schedule=sched,
        job=job,
        operation=op,
        resource=res,
        worker=None,
        start_minute=start,
        end_minute=end,
    )
    return sched


@pytest.mark.django_db
def test_diff_reports_completion_delta_and_slipped_jobs():
    res = Resource.objects.create(name="R", capacity=1)
    routing = Routing.objects.create(part_name="P")
    op = Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    job = Job.objects.create(routing=routing, quantity=1, due_date=datetime(2030, 1, 8, tzinfo=UTC))

    before = _persisted_schedule(job, op, res, start=0, end=30)
    after = _persisted_schedule(job, op, res, start=60, end=90)

    diff = diff_schedules(before, after)

    assert diff.deltas[job.id] == 60  # finishes 60 minutes later
    assert job.id in diff.slipped_job_ids
    assert job.id not in diff.improved_job_ids


@pytest.mark.django_db
def test_resolve_with_machine_down_re_solves_and_stays_feasible():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    res = Resource.objects.create(name="Anodize", capacity=1)
    Worker.objects.create(
        name="Tech", shift=Shift.objects.create(name="All", start_time=time(0), end_time=time(0))
    )
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    Job.objects.create(routing=routing, quantity=1, due_date=origin + timedelta(days=1))

    # The anodize tank goes down for an hour, two hours into the horizon.
    resolution = resolve(
        machine_down(res, origin + timedelta(hours=2), origin + timedelta(hours=3)),
        horizon_start=origin,
    )

    assert resolution.before.feasible is True
    assert resolution.after.feasible is True
    assert MaintenanceWindow.objects.filter(resource=res).count() == 1
    # The re-solved op must not run inside the new downtime window [120, 180).
    after_op = resolution.after.scheduled_ops.get()
    assert not (after_op.start_minute < 180 and after_op.end_minute > 120)


@pytest.mark.django_db
def test_expediting_the_trap_job_slips_at_least_two_other_jobs():
    """The headline trade: pulling the hot job forward 'looks free' but slips others.
    The diff surfaces exactly that, so a planner can decide with eyes open."""
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    trap_job = build_expedite_trap(base=origin)

    # Due in 110 min makes the hot lot urgent enough to take the front of the tank,
    # pushing the three on-time lots back.
    resolution = resolve(
        expedite(trap_job, new_due=origin + timedelta(minutes=110)),
        horizon_start=origin,
    )

    assert resolution.after.feasible is True
    assert len(resolution.diff.slipped_job_ids) >= 2
    # Surfacing the cost: total weighted tardiness rises once the others slip.
    assert resolution.weighted_tardiness_after > resolution.weighted_tardiness_before
