"""Load the synthetic plant into the database.

    python manage.py seed_plant          # only on an empty plant
    python manage.py seed_plant --force  # wipe the plant tables first, then seed
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from plant.data.sample import build_sample_plant
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

# Order matters: delete dependents before the rows they reference.
_MODELS_IN_DELETE_ORDER = [
    ScheduledOp,
    Schedule,
    AuditEvent,
    Job,
    Operation,
    Routing,
    MaintenanceWindow,
    Resource,
    Worker,
    Shift,
    Certification,
]


class Command(BaseCommand):
    help = "Load the synthetic plant (SPEC.md §5) into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Wipe existing plant data before seeding.",
        )

    def handle(self, *args, **options):
        if Routing.objects.exists() or Job.objects.exists():
            if not options["force"]:
                raise CommandError(
                    "The plant already has data. Re-run with --force to wipe and reseed."
                )
            for model in _MODELS_IN_DELETE_ORDER:
                model.objects.all().delete()

        with transaction.atomic():
            build_sample_plant()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded synthetic plant: {Routing.objects.count()} routings, "
                f"{Job.objects.count()} jobs, {Worker.objects.count()} workers."
            )
        )
