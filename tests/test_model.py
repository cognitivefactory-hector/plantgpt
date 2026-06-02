"""
M1 domain-model invariants (TDD).

These test the *data model and its query helpers* — not constraint enforcement.
Enforcing hard constraints (no uncertified assignment, time-between-ops, capacity)
is the solver's job in M3; the model only exposes the facts the solver reads.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from plant.model.models import (
    AuditEvent,
    Certification,
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


@pytest.mark.django_db
def test_worker_not_certified_when_missing_required_cert():
    shift = Shift.objects.create(name="Day", start_time="06:00", end_time="14:00")
    anodize = Certification.objects.create(code="ANODIZE", name="Anodize qualified")
    tank = Resource.objects.create(name="Anodize Tank", capacity=1)
    routing = Routing.objects.create(part_name="Bracket")
    op = Operation.objects.create(
        routing=routing,
        sequence=1,
        name="Anodize",
        resource=tank,
        duration_minutes=30,
        required_certification=anodize,
    )
    worker = Worker.objects.create(name="Sam", shift=shift)  # holds no certifications

    assert worker.is_certified_for(op) is False


@pytest.mark.django_db
def test_any_worker_is_certified_for_operation_needing_no_cert():
    shift = Shift.objects.create(name="Day", start_time="06:00", end_time="14:00")
    sink = Resource.objects.create(name="Clean Tank", capacity=2)
    routing = Routing.objects.create(part_name="Bracket")
    op = Operation.objects.create(
        routing=routing, sequence=1, name="Clean", resource=sink, duration_minutes=15
    )  # required_certification is None
    worker = Worker.objects.create(name="Sam", shift=shift)

    assert worker.is_certified_for(op) is True


@pytest.mark.django_db
def test_worker_certified_when_holding_the_required_cert():
    shift = Shift.objects.create(name="Day", start_time="06:00", end_time="14:00")
    anodize = Certification.objects.create(code="ANODIZE", name="Anodize qualified")
    tank = Resource.objects.create(name="Anodize Tank", capacity=1)
    routing = Routing.objects.create(part_name="Bracket")
    op = Operation.objects.create(
        routing=routing,
        sequence=1,
        name="Anodize",
        resource=tank,
        duration_minutes=30,
        required_certification=anodize,
    )
    worker = Worker.objects.create(name="Dana", shift=shift)
    worker.certifications.add(anodize)

    assert worker.is_certified_for(op) is True


@pytest.mark.django_db
def test_routing_operations_are_ordered_by_sequence():
    clean = Resource.objects.create(name="Clean", capacity=2)
    etch = Resource.objects.create(name="Etch", capacity=1)
    seal = Resource.objects.create(name="Seal", capacity=1)
    routing = Routing.objects.create(part_name="Bracket")
    # Insert out of order on purpose.
    Operation.objects.create(
        routing=routing, sequence=3, name="Seal", resource=seal, duration_minutes=20
    )
    Operation.objects.create(
        routing=routing, sequence=1, name="Clean", resource=clean, duration_minutes=15
    )
    Operation.objects.create(
        routing=routing, sequence=2, name="Etch", resource=etch, duration_minutes=10
    )

    names = [op.name for op in routing.operations.all()]

    assert names == ["Clean", "Etch", "Seal"]


@pytest.mark.django_db
def test_operation_sequence_is_unique_within_a_routing():
    from django.db import IntegrityError

    res = Resource.objects.create(name="Clean", capacity=2)
    routing = Routing.objects.create(part_name="Bracket")
    Operation.objects.create(
        routing=routing, sequence=1, name="Clean", resource=res, duration_minutes=15
    )

    with pytest.raises(IntegrityError):
        Operation.objects.create(
            routing=routing, sequence=1, name="Duplicate", resource=res, duration_minutes=5
        )


@pytest.mark.django_db
def test_aog_job_carries_higher_weight_than_a_normal_job():
    routing = Routing.objects.create(part_name="Bracket")
    due = timezone.now() + timedelta(days=2)
    normal = Job.objects.create(routing=routing, quantity=10, due_date=due, is_aog=False)
    aog = Job.objects.create(routing=routing, quantity=10, due_date=due, is_aog=True)

    assert aog.priority_weight > normal.priority_weight


@pytest.mark.django_db
def test_normal_job_priority_weight_uses_its_stored_weight():
    routing = Routing.objects.create(part_name="Bracket")
    due = timezone.now() + timedelta(days=2)
    job = Job.objects.create(routing=routing, quantity=5, due_date=due, weight=3)

    assert job.priority_weight == 3


@pytest.mark.django_db
def test_operation_can_cap_the_gap_before_its_successor():
    """time-between-ops: a part can't sit too long between steps. The cap lives on
    the operation *after which* the gap is measured; most transitions have no cap."""
    etch_res = Resource.objects.create(name="Etch", capacity=1)
    rinse_res = Resource.objects.create(name="Rinse", capacity=1)
    routing = Routing.objects.create(part_name="Bracket")
    etch = Operation.objects.create(
        routing=routing,
        sequence=1,
        name="Etch",
        resource=etch_res,
        duration_minutes=10,
        max_gap_after_minutes=20,
    )
    rinse = Operation.objects.create(
        routing=routing, sequence=2, name="Rinse", resource=rinse_res, duration_minutes=5
    )

    assert etch.max_gap_after_minutes == 20
    assert rinse.max_gap_after_minutes is None


@pytest.mark.django_db
def test_resource_has_maintenance_windows():
    res = Resource.objects.create(name="Anodize Tank", capacity=1)
    start = timezone.now() + timedelta(hours=4)
    window = MaintenanceWindow.objects.create(
        resource=res, start=start, end=start + timedelta(hours=2)
    )

    assert list(res.maintenance_windows.all()) == [window]
    assert window.end > window.start


@pytest.mark.django_db
def test_scheduled_op_links_job_operation_worker_resource_with_a_time_window():
    shift = Shift.objects.create(name="Day", start_time="06:00", end_time="14:00")
    res = Resource.objects.create(name="Etch", capacity=1)
    routing = Routing.objects.create(part_name="Bracket")
    op = Operation.objects.create(
        routing=routing, sequence=1, name="Etch", resource=res, duration_minutes=30
    )
    job = Job.objects.create(
        routing=routing, quantity=1, due_date=timezone.now() + timedelta(days=1)
    )
    worker = Worker.objects.create(name="Sam", shift=shift)
    schedule = Schedule.objects.create(kind=Schedule.Kind.CPSAT, feasible=True, objective_value=0)

    sop = ScheduledOp.objects.create(
        schedule=schedule,
        job=job,
        operation=op,
        worker=worker,
        resource=res,
        start_minute=0,
        end_minute=30,
    )

    assert list(schedule.scheduled_ops.all()) == [sop]
    assert sop.end_minute - sop.start_minute == 30
    assert schedule.feasible is True


@pytest.mark.django_db
def test_infeasible_schedule_has_no_objective_value():
    schedule = Schedule.objects.create(kind=Schedule.Kind.CPSAT, feasible=False)

    assert schedule.feasible is False
    assert schedule.objective_value is None


@pytest.mark.django_db
def test_audit_event_records_kind_and_json_payload():
    event = AuditEvent.objects.create(
        kind=AuditEvent.Kind.QUERY,
        payload={"query": "jobs missing due date", "confidence": "high"},
        note="Ask: which jobs miss their due date?",
    )

    assert event.kind == AuditEvent.Kind.QUERY
    assert event.payload["confidence"] == "high"
