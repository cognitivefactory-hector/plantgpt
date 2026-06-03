"""
Propose gate (M6): preview → human approve/reject.

`preview` re-solves the plant under a requested change *inside a savepoint that always
rolls back*, so the impact (what slips, the tardiness delta, feasibility) is computed
without applying anything. `approve` re-solves and persists — but only if the result is
feasible; an infeasible change can never be committed. `reject` changes nothing. Every
step is logged to the audit trail.

This is the human-in-the-loop core: the AI proposes, the constraint solver enforces, a
human disposes. (SPEC §4.B.2; CLAUDE.md safety invariants.)
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from plant.model.models import AuditEvent, Schedule
from plant.propose.request import SchedulerRequest
from plant.scheduler.cpsat import run_cpsat
from plant.scheduler.resolve import ScheduleDiff, diff_schedules, weighted_tardiness


class NoCurrentSchedule(RuntimeError):
    pass


class ProposalInfeasible(RuntimeError):
    """Raised when approving a request would yield an infeasible schedule."""


@dataclass
class Proposal:
    request: SchedulerRequest
    feasible: bool
    diff: ScheduleDiff | None  # None when infeasible
    tardiness_before: float
    tardiness_after: float | None  # None when infeasible
    before_schedule_id: int


class _Rollback(Exception):
    pass


def _current_schedule() -> Schedule:
    schedule = (
        Schedule.objects.filter(kind=Schedule.Kind.CPSAT, feasible=True)
        .order_by("-created_at")
        .first()
    )
    if schedule is None:
        raise NoCurrentSchedule("Generate a feasible schedule before proposing changes.")
    return schedule


def preview(request: SchedulerRequest) -> Proposal:
    """Re-solve under the request and diff against the current board — applying nothing."""
    before = _current_schedule()
    origin = before.horizon_start
    tardiness_before = weighted_tardiness(before, origin)  # original due dates

    captured: dict = {}
    try:
        with transaction.atomic():
            request.apply()
            after = run_cpsat(horizon_start=origin)
            captured["feasible"] = after.feasible
            if after.feasible:
                captured["diff"] = diff_schedules(before, after)
                captured["tardiness_after"] = weighted_tardiness(after, origin)  # new due dates
            raise _Rollback()  # discard the mutation and the re-solved schedule
    except _Rollback:
        pass

    AuditEvent.objects.create(
        kind=AuditEvent.Kind.PROPOSAL,
        payload={
            "request": {"kind": request.kind, "params": request.params},
            "feasible": captured["feasible"],
            "tardiness_before": tardiness_before,
            "tardiness_after": captured.get("tardiness_after"),
        },
        note=request.describe()[:255],
    )

    return Proposal(
        request=request,
        feasible=captured["feasible"],
        diff=captured.get("diff"),
        tardiness_before=tardiness_before,
        tardiness_after=captured.get("tardiness_after"),
        before_schedule_id=before.id,
    )


def approve(request: SchedulerRequest) -> Schedule:
    """Apply the request and persist the re-solved schedule — only if feasible."""
    before = _current_schedule()
    origin = before.horizon_start
    try:
        with transaction.atomic():
            request.apply()
            after = run_cpsat(horizon_start=origin)
            if not after.feasible:
                raise ProposalInfeasible(request.describe())
            AuditEvent.objects.create(
                kind=AuditEvent.Kind.APPROVAL,
                payload={
                    "request": {"kind": request.kind, "params": request.params},
                    "schedule_id": after.id,
                },
                note=request.describe()[:255],
            )
            return after
    except ProposalInfeasible:
        # The atomic block rolled back: nothing was applied, no schedule persisted.
        AuditEvent.objects.create(
            kind=AuditEvent.Kind.PROPOSAL,
            payload={
                "request": {"kind": request.kind, "params": request.params},
                "feasible": False,
            },
            note=f"REFUSED (infeasible): {request.describe()}"[:255],
        )
        raise


def reject(request: SchedulerRequest, *, reason: str = "") -> AuditEvent:
    """Decline a proposal. Nothing is applied; the rejection is logged."""
    return AuditEvent.objects.create(
        kind=AuditEvent.Kind.REJECTION,
        payload={"request": {"kind": request.kind, "params": request.params}, "reason": reason},
        note=request.describe()[:255],
    )
