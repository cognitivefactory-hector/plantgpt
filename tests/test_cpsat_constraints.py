"""
M3 CP-SAT solver — the safety core (TDD). These are the crown-jewel tests.

The solver returns either a *feasible* schedule that provably honors every hard
constraint, or an explicit *infeasible* result. Nothing here ever presents a
hand-built or LLM-built plan as feasible — that is the whole safety thesis
(CLAUDE.md invariants, SPEC §7).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from plant.model.models import (
    Certification,
    Job,
    MaintenanceWindow,
    Operation,
    Resource,
    Routing,
    Schedule,
    Shift,
    Worker,
)
from plant.scheduler.cpsat import run_cpsat
from plant.scheduler.dispatch import Rule, run_baseline


def _weighted_tardiness(schedule) -> float:
    """Weighted tardiness of a persisted schedule, in its own minute frame."""
    origin = schedule.horizon_start
    total = 0.0
    for job in Job.objects.all():
        ends = [o.end_minute for o in schedule.scheduled_ops.filter(job=job)]
        if not ends:
            continue
        due_min = (job.due_date - origin).total_seconds() / 60
        total += job.priority_weight * max(0.0, max(ends) - due_min)
    return total


def _ops_by_sequence(schedule):
    return list(schedule.scheduled_ops.select_related("operation").order_by("operation__sequence"))


def _shift():
    """An all-hours shift — shift time-of-day windows are a later M3 step."""
    return Shift.objects.create(name="All", start_time="00:00", end_time="23:59")


def _no_overlap(ops) -> bool:
    spans = sorted((o.start_minute, o.end_minute) for o in ops)
    return all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


@pytest.mark.django_db
def test_cpsat_produces_a_feasible_schedule_respecting_precedence():
    res_a = Resource.objects.create(name="A", capacity=1)
    res_b = Resource.objects.create(name="B", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op1", resource=res_a, duration_minutes=30
    )
    Operation.objects.create(
        routing=routing, sequence=2, name="op2", resource=res_b, duration_minutes=20
    )
    Worker.objects.create(name="Sam", shift=_shift())  # every op needs staffing
    Job.objects.create(routing=routing, quantity=1, due_date=timezone.now() + timedelta(days=1))

    schedule = run_cpsat()

    assert schedule.kind == Schedule.Kind.CPSAT
    assert schedule.feasible is True
    ops = _ops_by_sequence(schedule)
    assert [s.operation.sequence for s in ops] == [1, 2]
    assert ops[1].start_minute >= ops[0].end_minute


@pytest.mark.django_db
def test_cpsat_honors_time_between_ops_even_when_the_next_resource_is_delayed():
    """B is down for 100 minutes, so op2 cannot start before 100. The 10-minute cap
    then drags op1 late — it can't sit finished at minute 0 waiting. This binds: drop
    the constraint and the solver would leave op1 at 0 with a 100-minute gap."""
    res_a = Resource.objects.create(name="A", capacity=1)
    res_b = Resource.objects.create(name="B", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing,
        sequence=1,
        name="op1",
        resource=res_a,
        duration_minutes=30,
        max_gap_after_minutes=10,
    )
    Operation.objects.create(
        routing=routing, sequence=2, name="op2", resource=res_b, duration_minutes=20
    )
    now = timezone.now()
    Worker.objects.create(name="Sam", shift=_shift())
    Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))
    MaintenanceWindow.objects.create(resource=res_b, start=now, end=now + timedelta(minutes=100))

    schedule = run_cpsat()

    assert schedule.feasible is True
    ops = _ops_by_sequence(schedule)
    assert ops[1].start_minute >= 100  # op2 pushed past B's downtime
    assert ops[1].start_minute - ops[0].end_minute <= 10  # gap cap honored
    assert ops[0].start_minute >= 60  # so op1 is dragged late, not left at minute 0


@pytest.mark.django_db
def test_cpsat_keeps_operations_out_of_maintenance_windows():
    res = Resource.objects.create(name="A", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=30
    )
    now = timezone.now()
    Worker.objects.create(name="Sam", shift=_shift())
    Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))
    # Resource A is down for the first 60 minutes of the horizon.
    MaintenanceWindow.objects.create(resource=res, start=now, end=now + timedelta(minutes=60))

    schedule = run_cpsat()

    assert schedule.feasible is True
    op = schedule.scheduled_ops.get()
    # The op cannot run during [0, 60); it must start at or after the window ends.
    assert op.start_minute >= 60


@pytest.mark.django_db
def test_cpsat_never_assigns_an_uncertified_worker():
    shift = _shift()
    cert = Certification.objects.create(code="ANODIZE", name="Anodize qualified")
    res = Resource.objects.create(name="Anodize", capacity=1)
    routing = Routing.objects.create(part_name="P")
    op = Operation.objects.create(
        routing=routing,
        sequence=1,
        name="anodize",
        resource=res,
        duration_minutes=30,
        required_certification=cert,
    )
    certified = Worker.objects.create(name="Dana", shift=shift)
    certified.certifications.add(cert)
    Worker.objects.create(name="Sam", shift=shift)  # NOT anodize-certified
    Job.objects.create(routing=routing, quantity=1, due_date=timezone.now() + timedelta(days=1))

    schedule = run_cpsat()

    assert schedule.feasible is True
    so = schedule.scheduled_ops.get()
    assert so.worker_id == certified.id
    assert so.worker.is_certified_for(op)


@pytest.mark.django_db
def test_cpsat_is_infeasible_when_no_worker_holds_the_required_cert():
    """The over-constrained crown jewel: a required cert nobody holds → 'infeasible',
    never a silent plan that staffs the step with an unqualified operator."""
    shift = _shift()
    cert = Certification.objects.create(code="ANODIZE", name="Anodize qualified")
    res = Resource.objects.create(name="Anodize", capacity=1)
    routing = Routing.objects.create(part_name="P")
    Operation.objects.create(
        routing=routing,
        sequence=1,
        name="anodize",
        resource=res,
        duration_minutes=30,
        required_certification=cert,
    )
    Worker.objects.create(name="Sam", shift=shift)  # nobody is certified
    Job.objects.create(routing=routing, quantity=1, due_date=timezone.now() + timedelta(days=1))

    schedule = run_cpsat()

    assert schedule.feasible is False
    assert schedule.objective_value is None
    assert schedule.scheduled_ops.count() == 0


@pytest.mark.django_db
def test_cpsat_does_not_double_book_a_worker():
    shift = _shift()
    cert = Certification.objects.create(code="ANODIZE", name="Anodize qualified")
    # Two anodize ops on different resources (so capacity alone wouldn't serialize
    # them), but only ONE certified worker — they cannot run at the same time.
    res1 = Resource.objects.create(name="Anodize-1", capacity=1)
    res2 = Resource.objects.create(name="Anodize-2", capacity=1)
    dana = Worker.objects.create(name="Dana", shift=shift)
    dana.certifications.add(cert)
    now = timezone.now()
    for i, res in enumerate((res1, res2)):
        routing = Routing.objects.create(part_name=f"P{i}")
        Operation.objects.create(
            routing=routing,
            sequence=1,
            name="anodize",
            resource=res,
            duration_minutes=30,
            required_certification=cert,
        )
        Job.objects.create(routing=routing, quantity=1, due_date=now + timedelta(days=1))

    schedule = run_cpsat()

    assert schedule.feasible is True
    ops = list(schedule.scheduled_ops.all())
    assert all(o.worker_id == dana.id for o in ops)
    assert _no_overlap(ops)  # Dana cannot be in two places at once


@pytest.mark.django_db
def test_cpsat_finishes_an_aog_job_before_a_normal_job_under_contention():
    res = Resource.objects.create(name="Bottleneck", capacity=1)
    Worker.objects.create(name="Sam", shift=_shift())
    now = timezone.now()
    due = now + timedelta(minutes=10)  # tight: both end up tardy, so weight decides order
    normal_r = Routing.objects.create(part_name="Normal")
    Operation.objects.create(
        routing=normal_r, sequence=1, name="op", resource=res, duration_minutes=60
    )
    aog_r = Routing.objects.create(part_name="AOG")
    Operation.objects.create(
        routing=aog_r, sequence=1, name="op", resource=res, duration_minutes=60
    )
    normal = Job.objects.create(routing=normal_r, quantity=1, due_date=due, is_aog=False)
    aog = Job.objects.create(routing=aog_r, quantity=1, due_date=due, is_aog=True)

    schedule = run_cpsat()

    assert schedule.feasible is True
    starts = {s.job_id: s.start_minute for s in schedule.scheduled_ops.all()}
    assert starts[aog.id] < starts[normal.id]


@pytest.mark.django_db
def test_cpsat_beats_the_edd_baseline_on_weighted_tardiness():
    """EDD sequences the soon-due light job first; the optimizer instead finishes the
    heavy-weight (AOG) job first, slashing weighted tardiness. Two workers so worker
    contention does not bind — the win comes from sequencing, not staffing."""
    res = Resource.objects.create(name="Bottleneck", capacity=1)
    shift = _shift()
    Worker.objects.create(name="W1", shift=shift)
    Worker.objects.create(name="W2", shift=shift)
    now = timezone.now()
    light = Routing.objects.create(part_name="Light")  # due very soon, low weight, long
    Operation.objects.create(
        routing=light, sequence=1, name="op", resource=res, duration_minutes=100
    )
    heavy = Routing.objects.create(part_name="Heavy")  # due later, AOG weight, short
    Operation.objects.create(
        routing=heavy, sequence=1, name="op", resource=res, duration_minutes=10
    )
    Job.objects.create(routing=light, quantity=1, due_date=now + timedelta(minutes=10), weight=1)
    Job.objects.create(routing=heavy, quantity=1, due_date=now + timedelta(minutes=90), is_aog=True)

    baseline = run_baseline(rule=Rule.EDD)
    cpsat = run_cpsat()

    assert cpsat.feasible is True
    assert _weighted_tardiness(cpsat) < _weighted_tardiness(baseline)
    # The solver records its objective; it should match the realized weighted tardiness.
    assert cpsat.objective_value == pytest.approx(_weighted_tardiness(cpsat), abs=1)
