"""
A small, obviously-fictional plant (SPEC.md §5). No employer routings, parts,
capacities, or names — ever.

M1 builds a coherent minimal plant so the model and (later) the schedulers have
something to run on. M4 expands this into the full corpus (~15–25 jobs, 1–2 AOG,
and the deliberately tight "expedite-looks-free-but-isn't" scenario).
"""

from datetime import timedelta

from django.utils import timezone

from plant.model.models import (
    Certification,
    Job,
    Operation,
    Resource,
    Routing,
    Shift,
    Worker,
)


def build_sample_plant() -> None:
    """Create a coherent synthetic plant in the current database.

    Assumes an empty database (used by tests and the seed command). Deterministic
    apart from due dates, which are relative to now so the demo always looks current.
    """
    day = Shift.objects.create(name="Day", start_time="06:00", end_time="14:00")
    swing = Shift.objects.create(name="Swing", start_time="14:00", end_time="22:00")

    anodize_cert = Certification.objects.create(code="ANODIZE", name="Anodize qualified")

    # Wet-process line: clean → etch → anodize → seal → inspect.
    clean = Resource.objects.create(name="Clean Line", capacity=4)
    etch = Resource.objects.create(name="Etch Tank", capacity=2)
    anodize = Resource.objects.create(name="Anodize Tank", capacity=1)
    seal = Resource.objects.create(name="Seal Tank", capacity=2)
    inspect = Resource.objects.create(name="Inspect Bench", capacity=3)

    # Only some workers are anodize-certified — the anodize step is the bottleneck cert.
    dana = Worker.objects.create(name="Dana", shift=day)
    dana.certifications.add(anodize_cert)
    Worker.objects.create(name="Sam", shift=day)  # not anodize-certified
    lee = Worker.objects.create(name="Lee", shift=swing)
    lee.certifications.add(anodize_cert)

    # Bracket: full routing, with a tight time-between-ops cap from etch → anodize
    # (etched parts must reach anodize before the surface re-passivates).
    bracket = Routing.objects.create(part_name="Bracket")
    Operation.objects.create(
        routing=bracket, sequence=1, name="Clean", resource=clean, duration_minutes=20
    )
    Operation.objects.create(
        routing=bracket,
        sequence=2,
        name="Etch",
        resource=etch,
        duration_minutes=30,
        max_gap_after_minutes=15,
    )
    Operation.objects.create(
        routing=bracket,
        sequence=3,
        name="Anodize",
        resource=anodize,
        duration_minutes=45,
        required_certification=anodize_cert,
    )
    Operation.objects.create(
        routing=bracket, sequence=4, name="Seal", resource=seal, duration_minutes=25
    )
    Operation.objects.create(
        routing=bracket, sequence=5, name="Inspect", resource=inspect, duration_minutes=15
    )

    # Washer: a simpler routing that shares Clean/Seal/Inspect (resource contention).
    washer = Routing.objects.create(part_name="Washer")
    Operation.objects.create(
        routing=washer, sequence=1, name="Clean", resource=clean, duration_minutes=10
    )
    Operation.objects.create(
        routing=washer, sequence=2, name="Seal", resource=seal, duration_minutes=20
    )
    Operation.objects.create(
        routing=washer, sequence=3, name="Inspect", resource=inspect, duration_minutes=10
    )

    now = timezone.now()
    Job.objects.create(routing=bracket, quantity=5, due_date=now + timedelta(days=2))
    Job.objects.create(routing=washer, quantity=8, due_date=now + timedelta(days=1))
    # One AOG hot job, due soon — it should jump the queue (high priority weight).
    Job.objects.create(routing=bracket, quantity=2, due_date=now + timedelta(hours=8), is_aog=True)
