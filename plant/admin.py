"""Admin registrations — make the seeded synthetic plant browsable (aids the M1–M4
scheduler demo before any UI exists). Read/inspect oriented; not the planner UI (M7)."""

from django.contrib import admin

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


class OperationInline(admin.TabularInline):
    model = Operation
    extra = 0
    fields = (
        "sequence",
        "name",
        "resource",
        "duration_minutes",
        "required_certification",
        "max_gap_after_minutes",
    )
    ordering = ("sequence",)


@admin.register(Routing)
class RoutingAdmin(admin.ModelAdmin):
    list_display = ("part_name",)
    inlines = [OperationInline]


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("__str__", "routing", "quantity", "due_date", "is_aog", "priority_weight")
    list_filter = ("is_aog", "routing")


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("name", "shift")
    list_filter = ("shift", "certifications")
    filter_horizontal = ("certifications",)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity")


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "kind", "feasible", "objective_value", "created_at")
    list_filter = ("kind", "feasible")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("kind", "note", "created_at")
    list_filter = ("kind",)
    readonly_fields = ("created_at",)


admin.site.register([Certification, Shift, MaintenanceWindow, ScheduledOp])
