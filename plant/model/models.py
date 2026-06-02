"""
Domain model (M1).

Entities (SPEC.md §6): Resource, MaintenanceWindow, Operation, Routing, Job,
Worker, Certification, Shift, Schedule, ScheduledOp, AuditEvent.

The model stores facts and exposes read helpers (e.g. ``Worker.is_certified_for``)
that the scheduler reads. It does NOT enforce hard constraints — that is the
solver's job in M3 (see CLAUDE.md "safety invariants"). `plant/models.py`
re-exports everything here so Django's app loader finds it.
"""

from django.db import models


class Certification(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)

    def __str__(self) -> str:
        return self.code


class Shift(models.Model):
    name = models.CharField(max_length=60)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self) -> str:
        return self.name


class Worker(models.Model):
    name = models.CharField(max_length=120)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="workers")
    certifications = models.ManyToManyField(Certification, related_name="workers", blank=True)

    def __str__(self) -> str:
        return self.name

    def is_certified_for(self, operation: "Operation") -> bool:
        """True if the operation needs no certification, or this worker holds it.

        A read helper for the scheduler — never an enforcement point.
        """
        required = operation.required_certification_id
        if required is None:
            return True
        return self.certifications.filter(pk=required).exists()


class Resource(models.Model):
    name = models.CharField(max_length=120)
    capacity = models.PositiveIntegerField(default=1)

    def __str__(self) -> str:
        return self.name


class MaintenanceWindow(models.Model):
    """A span during which a resource is unavailable. The solver schedules around it."""

    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="maintenance_windows"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()

    class Meta:
        ordering = ["start"]

    def __str__(self) -> str:
        return f"{self.resource.name} down {self.start:%Y-%m-%d %H:%M}–{self.end:%H:%M}"


class Routing(models.Model):
    part_name = models.CharField(max_length=120)

    def __str__(self) -> str:
        return self.part_name


class Operation(models.Model):
    routing = models.ForeignKey(Routing, on_delete=models.CASCADE, related_name="operations")
    sequence = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="operations")
    duration_minutes = models.PositiveIntegerField()
    required_certification = models.ForeignKey(
        Certification, on_delete=models.PROTECT, null=True, blank=True, related_name="operations"
    )
    # time-between-ops: max minutes allowed between this op's end and the next op's
    # start. None = no limit. The solver enforces this as a hard constraint (M3).
    max_gap_after_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["routing", "sequence"], name="unique_operation_sequence_per_routing"
            )
        ]

    def __str__(self) -> str:
        return f"{self.routing.part_name} #{self.sequence} {self.name}"


class Job(models.Model):
    """An order to produce a part: a routing instance with a due date and weight.

    AOG ("aircraft on ground") jobs jump the queue — they carry a high tardiness
    weight so the solver pulls them earlier (the objective is weighted tardiness).
    """

    # Tardiness weight applied to AOG jobs. High enough to dominate normal jobs.
    AOG_WEIGHT = 100

    routing = models.ForeignKey(Routing, on_delete=models.PROTECT, related_name="jobs")
    quantity = models.PositiveIntegerField(default=1)
    due_date = models.DateTimeField()
    is_aog = models.BooleanField(default=False)
    weight = models.PositiveIntegerField(default=1)

    def __str__(self) -> str:
        flag = " [AOG]" if self.is_aog else ""
        return f"Job {self.pk} · {self.routing.part_name} ×{self.quantity}{flag}"

    @property
    def priority_weight(self) -> int:
        return self.AOG_WEIGHT if self.is_aog else self.weight


class Schedule(models.Model):
    """A generated plan. Produced by the dispatching baseline (M2) or CP-SAT (M3).

    A schedule is either feasible (with an objective value) or infeasible. Nothing
    else ever presents itself as a feasible schedule — see CLAUDE.md safety invariants.
    """

    class Kind(models.TextChoices):
        BASELINE = "baseline", "Dispatching baseline"
        CPSAT = "cpsat", "CP-SAT solver"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    feasible = models.BooleanField(default=False)
    # Weighted tardiness; None when infeasible.
    objective_value = models.IntegerField(null=True, blank=True)
    # Wall-clock origin for the integer minute grid the scheduler works in.
    horizon_start = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        state = "feasible" if self.feasible else "infeasible"
        return f"Schedule {self.pk} · {self.get_kind_display()} · {state}"


class ScheduledOp(models.Model):
    """One operation placed on the timeline: which job/op, on which resource, by whom,
    in the minute window [start_minute, end_minute) from the schedule's horizon_start."""

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="scheduled_ops")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="scheduled_ops")
    operation = models.ForeignKey(Operation, on_delete=models.PROTECT, related_name="scheduled_ops")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="scheduled_ops")
    worker = models.ForeignKey(
        Worker, on_delete=models.PROTECT, null=True, blank=True, related_name="scheduled_ops"
    )
    start_minute = models.PositiveIntegerField()
    end_minute = models.PositiveIntegerField()

    class Meta:
        ordering = ["start_minute"]

    def __str__(self) -> str:
        return f"{self.operation} @ {self.resource.name} [{self.start_minute}–{self.end_minute}]"


class AuditEvent(models.Model):
    """Append-only log: every read query (with its query text) and every proposed/
    approved change. The trail the planner and an auditor can replay (SPEC §4.B.3)."""

    class Kind(models.TextChoices):
        QUERY = "query", "Read-only query"
        PROPOSAL = "proposal", "Proposed change"
        APPROVAL = "approval", "Approved change"
        REJECTION = "rejection", "Rejected change"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} @ {self.created_at:%Y-%m-%d %H:%M}"
