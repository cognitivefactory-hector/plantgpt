"""The M1 seed must load a *coherent* synthetic plant — one that could actually be
scheduled. The full corpus (15–25 jobs, the tight expedite scenario) arrives in M4."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from plant.data.sample import build_sample_plant
from plant.model.models import Job, Operation, Routing, Worker


@pytest.mark.django_db
def test_every_routing_has_at_least_one_operation():
    build_sample_plant()

    assert Routing.objects.exists()
    for routing in Routing.objects.all():
        assert routing.operations.exists(), f"{routing} has no operations"


@pytest.mark.django_db
def test_every_cert_required_operation_has_a_qualified_worker():
    """Coherence: a plant where a step needs a cert nobody holds can never be scheduled."""
    build_sample_plant()

    cert_ops = Operation.objects.filter(required_certification__isnull=False)
    assert cert_ops.exists()
    workers = list(Worker.objects.all())
    for op in cert_ops:
        assert any(w.is_certified_for(op) for w in workers), f"no worker can run {op}"


@pytest.mark.django_db
def test_plant_exercises_a_time_between_ops_limit():
    build_sample_plant()

    assert Operation.objects.filter(max_gap_after_minutes__isnull=False).exists()


@pytest.mark.django_db
def test_plant_has_an_aog_job_that_outweighs_a_normal_job():
    build_sample_plant()

    aog = Job.objects.filter(is_aog=True).first()
    normal = Job.objects.filter(is_aog=False).first()
    assert aog is not None and normal is not None
    assert aog.priority_weight > normal.priority_weight


@pytest.mark.django_db
def test_seed_plant_command_populates_the_database():
    call_command("seed_plant")

    assert Job.objects.exists()
    assert Routing.objects.exists()


@pytest.mark.django_db
def test_seed_plant_command_refuses_to_run_on_a_non_empty_database():
    build_sample_plant()

    with pytest.raises(CommandError):
        call_command("seed_plant")  # no --force: must not double-seed
