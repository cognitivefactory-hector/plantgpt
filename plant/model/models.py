"""
Domain model — populated in M1 (TDD).

Planned entities (see SPEC.md §6, PLAN.md M1): Resource, Operation, Routing,
Part/Job, Worker, Certification, Shift, Schedule, ScheduledOp, AuditEvent.

Kept empty in M0 so there are no migrations yet. `plant/models.py` re-exports
everything defined here so Django's app loader and `makemigrations` find them.
"""
