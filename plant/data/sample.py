"""
A small, obviously-fictional plant (SPEC.md §5). No employer routings, parts,
capacities, or names — ever.

M1 builds a coherent minimal plant so the model and (later) the schedulers have
something to run on. M4 expands this into the full corpus (~15–25 jobs, 1–2 AOG,
and the deliberately tight "expedite-looks-free-but-isn't" scenario).
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from plant.model.models import (
    Certification,
    Job,
    MaintenanceWindow,
    Operation,
    Resource,
    Routing,
    Shift,
    Worker,
)


def build_sample_plant() -> None:
    """Create the coherent synthetic plant corpus (SPEC §5) in the current database.

    ~16 jobs across 4 routings on 5 wet-process resources, 5 workers (2 anodize-
    certified), maintenance windows on the two bottleneck tanks, and a time-between-ops
    cap on the etch→anodize transition. Assumes an empty database. Durations and
    quantities are fixed (deterministic); only due dates are relative to now so the
    demo always looks current.
    """
    day = Shift.objects.create(name="Day", start_time=time(6), end_time=time(14))
    swing = Shift.objects.create(name="Swing", start_time=time(14), end_time=time(22))

    anodize_cert = Certification.objects.create(code="ANODIZE", name="Anodize qualified")

    # Wet-process line: clean → etch → anodize → seal → inspect. Anodize is the
    # capacity-1 bottleneck; the others have parallel capacity.
    clean = Resource.objects.create(name="Clean Line", capacity=3)
    etch = Resource.objects.create(name="Etch Tank", capacity=2)
    anodize = Resource.objects.create(name="Anodize Tank", capacity=1)
    seal = Resource.objects.create(name="Seal Tank", capacity=2)
    inspect = Resource.objects.create(name="Inspect Bench", capacity=3)

    # Only some workers are anodize-certified — the anodize step is the bottleneck cert.
    dana = Worker.objects.create(name="Dana", shift=day)
    dana.certifications.add(anodize_cert)
    Worker.objects.create(name="Sam", shift=day)  # not anodize-certified
    Worker.objects.create(name="Mia", shift=day)  # not anodize-certified
    lee = Worker.objects.create(name="Lee", shift=swing)
    lee.certifications.add(anodize_cert)
    Worker.objects.create(name="Ravi", shift=swing)  # not anodize-certified

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

    # Washer: a short routing that shares Clean/Seal/Inspect (resource contention).
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

    # Fitting: clean → etch → seal → inspect (no anodize — needs no cert).
    fitting = Routing.objects.create(part_name="Fitting")
    Operation.objects.create(
        routing=fitting, sequence=1, name="Clean", resource=clean, duration_minutes=15
    )
    Operation.objects.create(
        routing=fitting, sequence=2, name="Etch", resource=etch, duration_minutes=20
    )
    Operation.objects.create(
        routing=fitting, sequence=3, name="Seal", resource=seal, duration_minutes=20
    )
    Operation.objects.create(
        routing=fitting, sequence=4, name="Inspect", resource=inspect, duration_minutes=10
    )

    # Panel: clean → anodize → inspect, also gated by the time-between-ops cap.
    panel = Routing.objects.create(part_name="Panel")
    Operation.objects.create(
        routing=panel,
        sequence=1,
        name="Clean",
        resource=clean,
        duration_minutes=15,
        max_gap_after_minutes=20,
    )
    Operation.objects.create(
        routing=panel,
        sequence=2,
        name="Anodize",
        resource=anodize,
        duration_minutes=40,
        required_certification=anodize_cert,
    )
    Operation.objects.create(
        routing=panel, sequence=3, name="Inspect", resource=inspect, duration_minutes=15
    )

    # The two bottleneck tanks each have a short maintenance window in the first shift.
    now = timezone.now()
    MaintenanceWindow.objects.create(
        resource=anodize, start=now + timedelta(hours=3), end=now + timedelta(hours=4)
    )
    MaintenanceWindow.objects.create(
        resource=etch, start=now + timedelta(hours=5), end=now + timedelta(hours=6)
    )

    # ~16 jobs across the routings, staggered due dates, two AOG hot lots.
    # (routing, quantity, due-offset-hours, is_aog)
    plan = [
        (bracket, 4, 26, False),
        (bracket, 2, 30, False),
        (washer, 8, 20, False),
        (washer, 6, 24, False),
        (fitting, 5, 22, False),
        (fitting, 3, 28, False),
        (panel, 4, 26, False),
        (panel, 2, 32, False),
        (bracket, 3, 34, False),
        (washer, 10, 18, False),
        (fitting, 4, 30, False),
        (panel, 3, 36, False),
        (washer, 7, 21, False),
        (fitting, 2, 19, False),
        (bracket, 2, 10, True),  # AOG hot lot, due soon
        (panel, 1, 12, True),  # AOG hot lot, due soon
    ]
    for routing, quantity, due_hours, is_aog in plan:
        Job.objects.create(
            routing=routing,
            quantity=quantity,
            due_date=now + timedelta(hours=due_hours),
            is_aog=is_aog,
        )


def build_expedite_trap(base: datetime | None = None) -> Job:
    """The deliberately tight scenario (SPEC §5): a bottleneck anodize tank with three
    lots that all just make their due dates, plus one slack 'hot' lot scheduled last.

    Expediting the hot lot *looks* free — the tank "had room" for it at the end — but
    pulling it to the front slips the three on-time lots. This is the trade surfaced
    in challenge #6 ("a change I recommended against"). Returns the hot lot to expedite.

    ``base`` anchors the due dates; pass the same value as the solver's horizon_start.
    """
    base = base or timezone.now()
    shift = Shift.objects.create(name="All", start_time=time(0, 0), end_time=time(0, 0))
    Worker.objects.create(name="Tech", shift=shift)
    anodize = Resource.objects.create(name="Anodize Tank", capacity=1)  # the bottleneck

    def _lot(part_name: str, due_offset_minutes: int) -> Job:
        routing = Routing.objects.create(part_name=part_name)
        Operation.objects.create(
            routing=routing, sequence=1, name="Anodize", resource=anodize, duration_minutes=60
        )
        return Job.objects.create(
            routing=routing, quantity=1, due_date=base + timedelta(minutes=due_offset_minutes)
        )

    # Run in order, each finishes right on its due date: 60, 120, 180 ≤ 70, 130, 190.
    _lot("Lot-A", 70)
    _lot("Lot-B", 130)
    _lot("Lot-C", 190)
    # The hot lot has plenty of slack now (finishes 4th at 240 ≤ 600), so it looks
    # free to pull forward. Expediting it is the trap.
    return _lot("Hot-Lot", 600)
