"""
Scheduler requests (M6) — the only write path into the plant.

A SchedulerRequest is a structured, serializable description of a change a planner
wants ("expedite this lot", "block this tank Thursday"). The agent translates NL
intent into one of these — it never mutates the schedule directly. Applying a request
is gated: it happens inside a preview that rolls back, or on explicit human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from plant.model.models import Job, MaintenanceWindow, Resource


class UnknownRequestKind(ValueError):
    pass


@dataclass
class SchedulerRequest:
    """A requested schedule change. ``params`` is plain JSON so a proposal can be
    serialized between the propose step and the approve step (different HTTP requests).

    Kinds:
      * ``expedite``        — params: job_id, new_due_iso (optional). Marks the job AOG
                              and, if given, pulls its due date in.
      * ``block_resource``  — params: resource_name, start_iso, end_iso. Takes a resource
                              down for a window (a maintenance window).
    """

    kind: str
    params: dict = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == "expedite":
            due = self.params.get("new_due_iso")
            tail = f", due {due}" if due else ""
            return f"Expedite job {self.params['job_id']} (mark AOG{tail})"
        if self.kind == "block_resource":
            return (
                f"Block {self.params['resource_name']} "
                f"from {self.params['start_iso']} to {self.params['end_iso']}"
            )
        raise UnknownRequestKind(self.kind)

    def apply(self) -> None:
        """Mutate the plant. Only ever called inside a preview savepoint or on approval."""
        if self.kind == "expedite":
            job = Job.objects.get(id=self.params["job_id"])
            job.is_aog = True
            fields = ["is_aog"]
            if self.params.get("new_due_iso"):
                job.due_date = datetime.fromisoformat(self.params["new_due_iso"])
                fields.append("due_date")
            job.save(update_fields=fields)
        elif self.kind == "block_resource":
            resource = Resource.objects.get(name=self.params["resource_name"])
            MaintenanceWindow.objects.create(
                resource=resource,
                start=datetime.fromisoformat(self.params["start_iso"]),
                end=datetime.fromisoformat(self.params["end_iso"]),
            )
        else:
            raise UnknownRequestKind(self.kind)
