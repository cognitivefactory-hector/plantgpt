"""
CP-SAT solver (M3) — the safety core.

Models the plant as a constraint program (OR-Tools CP-SAT) and returns either a
feasible schedule that provably honors every hard constraint, or an explicit
*infeasible* result. Hard-constraint enforcement lives HERE and nowhere else; no
other path (UI, agent, LLM) ever presents a schedule as feasible (CLAUDE.md).

Hard constraints modeled:
  * routing precedence — op N+1 starts only after op N ends;
  * resource capacity — at most `capacity` operations on a resource at once;
  * time-between-ops — op N+1 starts within op N's max gap, when set;
  * maintenance windows — no operation runs while its resource is down;
  * worker certification — every op is staffed by exactly one *certified* worker;
  * worker single-tasking — no worker runs two operations at once;
  * worker shifts — a worker is assigned only while on duty (their shift window).

Objective: minimize weighted tardiness (AOG jobs weighted highest) — a soft
objective, never a hard constraint.

Shift times are wall-clock times of day, interpreted in the tz of ``horizon_start``
(UTC by default). The horizon is widened to span shift gaps so a plan that must wait
for the next on-shift window stays feasible rather than falsely reported infeasible.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from ortools.sat.python import cp_model

from plant.model.models import (
    Job,
    MaintenanceWindow,
    Operation,
    Resource,
    Schedule,
    ScheduledOp,
    Shift,
    Worker,
)


def _minutes_from(origin: datetime, moment: datetime) -> int:
    return int(round((moment - origin).total_seconds() / 60))


def _on_shift_windows(origin: datetime, shift: Shift, horizon: int) -> list[tuple[int, int]]:
    """The worker's on-duty windows within [0, horizon], in minutes from ``origin``.

    Shift times are wall-clock times of day, applied per calendar day. A shift whose
    end is at or before its start is treated as overnight (it wraps past midnight).
    """
    windows: list[tuple[int, int]] = []
    day = (origin - timedelta(days=1)).date()
    last = (origin + timedelta(minutes=horizon) + timedelta(days=1)).date()
    while day <= last:
        start_dt = datetime.combine(day, shift.start_time, tzinfo=origin.tzinfo)
        end_dt = datetime.combine(day, shift.end_time, tzinfo=origin.tzinfo)
        if end_dt <= start_dt:  # overnight shift wraps to the next day
            end_dt += timedelta(days=1)
        ws = max(0, _minutes_from(origin, start_dt))
        we = min(horizon, _minutes_from(origin, end_dt))
        if we > ws:
            windows.append((ws, we))
        day += timedelta(days=1)
    return windows


def _off_shift_blockers(origin: datetime, shift: Shift, horizon: int) -> list[tuple[int, int]]:
    """The complement of the on-shift windows within [0, horizon] — when the worker is
    off duty. Assigned operations must not overlap these."""
    merged: list[list[int]] = []
    for ws, we in sorted(_on_shift_windows(origin, shift, horizon)):
        if merged and ws <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], we)
        else:
            merged.append([ws, we])

    blockers: list[tuple[int, int]] = []
    cursor = 0
    for ws, we in merged:
        if ws > cursor:
            blockers.append((cursor, ws))
        cursor = max(cursor, we)
    if cursor < horizon:
        blockers.append((cursor, horizon))
    return blockers


@dataclass
class _Op:
    """A (job, operation) node with its CP-SAT variables."""

    job: Job
    operation: Operation
    start: cp_model.IntVar
    end: cp_model.IntVar
    # (worker, presence-literal) pairs — exactly one literal is true in a solution.
    worker_choices: list = None


@transaction.atomic
def run_cpsat(time_limit_s: float = 10.0, horizon_start: datetime | None = None) -> Schedule:
    """Build, solve, and persist a CP-SAT schedule over every Job in the database.

    ``horizon_start`` is the wall-clock origin of the minute grid (defaults to now);
    pass a fixed value to make shift/due-date math deterministic in tests.
    """
    now = horizon_start or timezone.now()
    jobs = list(Job.objects.select_related("routing"))
    op_lists: dict[int, list[Operation]] = {
        job.id: list(job.routing.operations.select_related("resource")) for job in jobs
    }

    # Maintenance windows in minutes from the horizon origin (clamped later to the horizon).
    maint_by_resource: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for mw in MaintenanceWindow.objects.all():
        maint_by_resource[mw.resource_id].append(
            (_minutes_from(now, mw.start), _minutes_from(now, mw.end))
        )

    # Horizon: room for all work to run serially after the latest downtime, plus slack
    # for shift fragmentation — workers are on duty only part of each day, so work may
    # span several days. ~8 usable hours/day is assumed, with two extra days of buffer.
    # A loose horizon only adds room; it never makes a genuinely feasible plan infeasible.
    total_work = sum(op.duration_minutes for ops in op_lists.values() for op in ops)
    latest_maint_end = max(
        (we for spans in maint_by_resource.values() for _, we in spans), default=0
    )
    DAY = 24 * 60
    shift_slack = (total_work // (8 * 60) + 2) * DAY
    horizon = max(total_work, 1) + max(latest_maint_end, 0) + shift_slack + 1

    model = cp_model.CpModel()
    nodes: list[_Op] = []
    intervals_by_resource: dict[int, list] = defaultdict(list)
    completion_by_job: dict[int, cp_model.IntVar] = {}

    for job in jobs:
        prev_end = None
        prev_op = None
        for op in op_lists[job.id]:
            suffix = f"j{job.id}_o{op.id}"
            start = model.new_int_var(0, horizon, f"start_{suffix}")
            end = model.new_int_var(0, horizon, f"end_{suffix}")
            interval = model.new_interval_var(start, op.duration_minutes, end, f"iv_{suffix}")
            nodes.append(_Op(job=job, operation=op, start=start, end=end))
            intervals_by_resource[op.resource_id].append(interval)

            if prev_end is not None:
                model.add(start >= prev_end)  # routing precedence
                # time-between-ops: this op must start within the previous op's max gap.
                if prev_op.max_gap_after_minutes is not None:
                    model.add(start <= prev_end + prev_op.max_gap_after_minutes)
            prev_end = end
            prev_op = op
        if prev_end is not None:
            completion_by_job[job.id] = prev_end  # end of the job's last operation

    # Resource capacity, with maintenance windows as full-capacity blockers.
    capacities = {r.id: r.capacity for r in Resource.objects.all()}
    for resource_id, intervals in intervals_by_resource.items():
        cap = capacities[resource_id]

        blockers = []
        for ws, we in maint_by_resource.get(resource_id, []):
            ws_c, we_c = max(0, ws), min(horizon, we)
            if we_c > ws_c:  # window overlaps the horizon
                blockers.append(
                    model.new_interval_var(ws_c, we_c - ws_c, we_c, f"maint_r{resource_id}_{ws_c}")
                )

        if cap == 1:
            model.add_no_overlap(intervals + blockers)
        else:
            # A blocker consumes the whole resource (demand = capacity).
            demands = [1] * len(intervals) + [cap] * len(blockers)
            model.add_cumulative(intervals + blockers, demands, cap)

    # Worker assignment: each operation is staffed by exactly one *certified* worker,
    # and no worker is in two places at once. An operation with no eligible worker
    # makes the whole plan infeasible — never staffed by an unqualified operator.
    workers = list(Worker.objects.select_related("shift").prefetch_related("certifications"))
    workers_by_id = {w.id: w for w in workers}
    worker_intervals: dict[int, list] = defaultdict(list)
    for node in nodes:
        op = node.operation
        eligible = [w for w in workers if w.is_certified_for(op)]
        if not eligible:
            return Schedule.objects.create(
                kind=Schedule.Kind.CPSAT, feasible=False, objective_value=None, horizon_start=now
            )

        choices = []
        for w in eligible:
            suffix = f"j{node.job.id}_o{op.id}_w{w.id}"
            present = model.new_bool_var(f"assign_{suffix}")
            choices.append((w, present))
            worker_intervals[w.id].append(
                model.new_optional_interval_var(
                    node.start, op.duration_minutes, node.end, present, f"wiv_{suffix}"
                )
            )
        model.add_exactly_one([present for _, present in choices])
        node.worker_choices = choices

    # A worker's assigned ops can't overlap each other (single-tasking) nor the
    # worker's off-shift periods (on-shift only) — both enforced by one no-overlap.
    for worker_id, intervals in worker_intervals.items():
        for ws, we in _off_shift_blockers(now, workers_by_id[worker_id].shift, horizon):
            intervals.append(model.new_interval_var(ws, we - ws, we, f"off_w{worker_id}_{ws}"))
        model.add_no_overlap(intervals)

    # Objective: minimize weighted tardiness. AOG jobs carry a high priority_weight,
    # so the solver pulls them earlier (a soft objective — never a hard constraint).
    jobs_by_id = {job.id: job for job in jobs}
    due_minutes = {job.id: _minutes_from(now, job.due_date) for job in jobs}
    # Tardiness can exceed the horizon when a job is already past due (negative due).
    tardy_ub = horizon + max((max(0, -d) for d in due_minutes.values()), default=0) + 1
    tardiness_terms = []
    for job_id, completion in completion_by_job.items():
        tardy = model.new_int_var(0, tardy_ub, f"tardy_j{job_id}")
        model.add(tardy >= completion - due_minutes[job_id])
        tardiness_terms.append(jobs_by_id[job_id].priority_weight * tardy)
    model.minimize(sum(tardiness_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    if not feasible:
        return Schedule.objects.create(
            kind=Schedule.Kind.CPSAT, feasible=False, objective_value=None, horizon_start=now
        )

    schedule = Schedule.objects.create(
        kind=Schedule.Kind.CPSAT,
        feasible=True,
        objective_value=round(solver.objective_value),
        horizon_start=now,
    )

    def _assigned_worker(node: _Op) -> Worker:
        return next(w for w, present in node.worker_choices if solver.boolean_value(present))

    ScheduledOp.objects.bulk_create(
        [
            ScheduledOp(
                schedule=schedule,
                job=node.job,
                operation=node.operation,
                resource=node.operation.resource,
                worker=_assigned_worker(node),
                start_minute=solver.value(node.start),
                end_minute=solver.value(node.end),
            )
            for node in nodes
        ]
    )
    return schedule
