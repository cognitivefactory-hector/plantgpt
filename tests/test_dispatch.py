"""
M2 dispatching-baseline scheduler (TDD).

The baseline is an explainable list-scheduler (EDD / Critical-Ratio / SPT) that
produces a *feasible* plan respecting routing precedence and resource capacity.
It is the honest foil for the CP-SAT solver (M3); it does not claim optimality and
does not assign workers (that arrives with the solver).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from plant.data.sample import build_sample_plant
from plant.model.models import Job, Operation, Resource, Routing, Schedule
from plant.scheduler.dispatch import Rule, run_baseline


def _start_by_job(schedule):
    return {s.job_id: s.start_minute for s in schedule.scheduled_ops.all()}


@pytest.mark.django_db
def test_baseline_respects_routing_precedence_within_a_job():
    res_a = Resource.objects.create(name="A", capacity=1)
    res_b = Resource.objects.create(name="B", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op1", resource=res_a, duration_minutes=30
    )
    Operation.objects.create(
        routing=routing, sequence=2, name="op2", resource=res_b, duration_minutes=20
    )
    Job.objects.create(routing=routing, quantity=1, due_date=timezone.now() + timedelta(days=1))

    schedule = run_baseline(rule=Rule.EDD)

    ops = list(schedule.scheduled_ops.select_related("operation").order_by("operation__sequence"))
    assert [s.operation.sequence for s in ops] == [1, 2]
    # op2 cannot start until op1 has finished.
    assert ops[1].start_minute >= ops[0].end_minute
    # Each op occupies its declared duration.
    assert ops[0].end_minute - ops[0].start_minute == 30
    assert ops[1].end_minute - ops[1].start_minute == 20


def _max_concurrency(ops) -> int:
    """Peak number of operations running at the same instant."""
    events = []
    for o in ops:
        events.append((o.start_minute, 1))
        events.append((o.end_minute, -1))
    events.sort()
    running = peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    return peak


@pytest.mark.django_db
def test_baseline_never_exceeds_capacity_one_resource():
    res = Resource.objects.create(name="Single", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    now = timezone.now()
    Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))
    Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=2))

    schedule = run_baseline(rule=Rule.EDD)

    ops = list(schedule.scheduled_ops.filter(resource=res))
    assert _max_concurrency(ops) <= 1


@pytest.mark.django_db
def test_baseline_allows_concurrency_up_to_capacity():
    res = Resource.objects.create(name="Twin", capacity=2)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    now = timezone.now()
    for _ in range(3):
        Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))

    schedule = run_baseline(rule=Rule.EDD)

    ops = list(schedule.scheduled_ops.filter(resource=res))
    assert _max_concurrency(ops) <= 2
    # With capacity 2 and three identical jobs, two run together and the third waits.
    assert _max_concurrency(ops) == 2


@pytest.mark.django_db
def test_edd_schedules_earlier_due_job_first_on_a_contended_resource():
    res = Resource.objects.create(name="Single", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    now = timezone.now()
    # Create the later-due job first, so a pass can only come from sorting by due date.
    late = Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=5))
    early = Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))

    start = _start_by_job(run_baseline(rule=Rule.EDD))

    assert start[early.id] < start[late.id]


@pytest.mark.django_db
def test_spt_schedules_shorter_operation_first_on_a_contended_resource():
    res = Resource.objects.create(name="Single", capacity=1)
    long_routing = Routing.objects.create(part_name="Long")
    Operation.objects.create(
        routing=long_routing, sequence=1, name="long", resource=res, duration_minutes=60
    )
    short_routing = Routing.objects.create(part_name="Short")
    Operation.objects.create(
        routing=short_routing, sequence=1, name="short", resource=res, duration_minutes=10
    )
    now = timezone.now()
    long_job = Job.objects.create(
        routing=long_routing, quantity=1, due_date=now + timedelta(days=1)
    )
    short_job = Job.objects.create(
        routing=short_routing, quantity=1, due_date=now + timedelta(days=1)
    )

    start = _start_by_job(run_baseline(rule=Rule.SPT))

    assert start[short_job.id] < start[long_job.id]


@pytest.mark.django_db
def test_critical_ratio_prioritizes_least_slack_per_unit_work_not_just_due_date():
    """CR differs from EDD: a later-due job with far more work (less slack) goes first."""
    res = Resource.objects.create(name="Single", capacity=1)
    light = Routing.objects.create(part_name="Light")  # due sooner, tiny job
    Operation.objects.create(
        routing=light, sequence=1, name="op", resource=res, duration_minutes=10
    )
    heavy = Routing.objects.create(part_name="Heavy")  # due later, huge job → less slack
    Operation.objects.create(
        routing=heavy, sequence=1, name="op", resource=res, duration_minutes=600
    )
    now = timezone.now()
    light_job = Job.objects.create(routing=light, quantity=1, due_date=now + timedelta(days=3))
    heavy_job = Job.objects.create(routing=heavy, quantity=1, due_date=now + timedelta(days=4))

    # EDD would run the sooner-due light job first; CR runs the heavy one first.
    edd_start = _start_by_job(run_baseline(rule=Rule.EDD))
    assert edd_start[light_job.id] < edd_start[heavy_job.id]

    cr_start = _start_by_job(run_baseline(rule=Rule.CR))
    assert cr_start[heavy_job.id] < cr_start[light_job.id]


@pytest.mark.django_db
def test_baseline_schedules_every_operation_and_marks_feasible():
    build_sample_plant()
    total_ops = sum(job.routing.operations.count() for job in Job.objects.all())

    schedule = run_baseline(rule=Rule.EDD)

    assert schedule.kind == Schedule.Kind.BASELINE
    assert schedule.feasible is True
    assert schedule.horizon_start is not None
    assert schedule.scheduled_ops.count() == total_ops
