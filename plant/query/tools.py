"""
Typed read-only query tools (M5).

The Ask agent answers questions by calling these tools — never by writing SQL.
Each tool runs a constrained, read-only ORM query and returns plain data. There is
no tool here that mutates anything: read-only is guaranteed by construction, not by
trusting the model (SPEC §4.B.1, CLAUDE.md safety invariants).

Tools read the latest feasible CP-SAT schedule; they never *create* one (that would
be a write). If no schedule exists yet, they say so.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from plant.model.models import Job, Resource, Schedule


@dataclass(frozen=True)
class ReadTool:
    name: str
    description: str
    input_schema: dict
    run: Callable[..., dict]


def _latest_schedule() -> Schedule | None:
    return (
        Schedule.objects.filter(kind=Schedule.Kind.CPSAT, feasible=True)
        .order_by("-created_at")
        .first()
    )


def _completion_by_job(schedule: Schedule) -> dict[int, int]:
    completions: dict[int, int] = {}
    for so in schedule.scheduled_ops.all():
        completions[so.job_id] = max(completions.get(so.job_id, 0), so.end_minute)
    return completions


def jobs_missing_due_date(**_: Any) -> dict:
    """Jobs whose completion in the latest schedule falls after their due date."""
    schedule = _latest_schedule()
    if schedule is None:
        return {"schedule": None, "note": "No feasible schedule has been generated yet."}

    origin = schedule.horizon_start
    completions = _completion_by_job(schedule)
    late = []
    for job in Job.objects.select_related("routing").filter(id__in=completions):
        due_min = (job.due_date - origin).total_seconds() / 60
        completion = completions[job.id]
        if completion > due_min:
            late.append(
                {
                    "job_id": job.id,
                    "part": job.routing.part_name,
                    "is_aog": job.is_aog,
                    "minutes_late": round(completion - due_min),
                }
            )
    late.sort(key=lambda r: r["minutes_late"], reverse=True)
    return {"schedule_id": schedule.id, "jobs_missing_due_date": late, "count": len(late)}


def resource_utilization(**_: Any) -> dict:
    """Per-resource utilization in the latest schedule; the bottleneck is the highest."""
    schedule = _latest_schedule()
    if schedule is None:
        return {"schedule": None, "note": "No feasible schedule has been generated yet."}

    ops = list(schedule.scheduled_ops.select_related("resource"))
    span = max((o.end_minute for o in ops), default=0)
    busy: dict[int, int] = {}
    for o in ops:
        busy[o.resource_id] = busy.get(o.resource_id, 0) + (o.end_minute - o.start_minute)

    rows = []
    for resource in Resource.objects.all():
        capacity_minutes = resource.capacity * span
        used = busy.get(resource.id, 0)
        rows.append(
            {
                "resource": resource.name,
                "capacity": resource.capacity,
                "busy_minutes": used,
                "utilization_pct": round(100 * used / capacity_minutes, 1)
                if capacity_minutes
                else 0.0,
            }
        )
    rows.sort(key=lambda r: r["utilization_pct"], reverse=True)
    return {"schedule_id": schedule.id, "horizon_minutes": span, "resources": rows}


def list_jobs(aog_only: bool = False, **_: Any) -> dict:
    """List jobs with quantity, due date, and AOG flag. Set aog_only to filter to AOG."""
    qs = Job.objects.select_related("routing").order_by("due_date")
    if aog_only:
        qs = qs.filter(is_aog=True)
    jobs = [
        {
            "job_id": j.id,
            "part": j.routing.part_name,
            "quantity": j.quantity,
            "due_date": j.due_date.isoformat(),
            "is_aog": j.is_aog,
        }
        for j in qs
    ]
    return {"jobs": jobs, "count": len(jobs)}


def list_resources(**_: Any) -> dict:
    """List resources (lines/tanks) and their capacity."""
    resources = [
        {"resource": r.name, "capacity": r.capacity} for r in Resource.objects.order_by("name")
    ]
    return {"resources": resources, "count": len(resources)}


READ_TOOLS: list[ReadTool] = [
    ReadTool(
        name="jobs_missing_due_date",
        description=(
            "Return the jobs that will miss their due date in the latest schedule, "
            "with how many minutes late each is. No arguments."
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        run=jobs_missing_due_date,
    ),
    ReadTool(
        name="resource_utilization",
        description=(
            "Return per-resource utilization in the latest schedule, sorted highest "
            "first (the top row is the bottleneck). No arguments."
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        run=resource_utilization,
    ),
    ReadTool(
        name="list_jobs",
        description="List jobs with quantity, due date, and AOG flag.",
        input_schema={
            "type": "object",
            "properties": {
                "aog_only": {
                    "type": "boolean",
                    "description": "If true, return only AOG (hot) jobs.",
                }
            },
            "additionalProperties": False,
        },
        run=list_jobs,
    ),
    ReadTool(
        name="list_resources",
        description="List the plant's resources (lines/tanks) and their capacity. No arguments.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        run=list_resources,
    ),
]

TOOLS_BY_NAME: dict[str, ReadTool] = {t.name: t for t in READ_TOOLS}


def run_tool(name: str, args: dict) -> dict:
    """Execute a read tool by name. Raises KeyError for an unknown tool."""
    return TOOLS_BY_NAME[name].run(**(args or {}))


def tool_specs() -> list[dict]:
    """Anthropic tool-use specs for the read tools."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in READ_TOOLS
    ]
