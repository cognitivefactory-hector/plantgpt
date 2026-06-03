"""
Views: the M0 health check + the M7 screens (Schedule board / Ask / Propose).

The screens are thin — they render data and wire the browser to the already-tested
agent (`plant.agent`) and gate (`plant.propose`) layers. The board needs no AI; Ask
and Propose degrade gracefully to a notice when no ANTHROPIC_API_KEY is configured.
"""

import json

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from plant.agent.ask import ask as run_ask
from plant.agent.propose import propose as run_propose
from plant.charts import gantt_html, utilization_html
from plant.model.models import AuditEvent, Job, Resource, Schedule, Worker
from plant.propose.impact import (
    NoCurrentSchedule,
    ProposalInfeasible,
)
from plant.propose.impact import (
    approve as approve_request,
)
from plant.propose.impact import (
    reject as reject_request,
)
from plant.propose.request import SchedulerRequest
from plant.scheduler.cpsat import run_cpsat
from plant.scheduler.dispatch import Rule, run_baseline

# --- M0 health (Render uses /healthz) ---------------------------------------


def _checks() -> dict[str, dict]:
    checks: dict[str, dict] = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        detail = connection.vendor
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT version()")
                detail = cur.fetchone()[0].split(",")[0]
        except Exception:  # noqa: BLE001
            pass
        checks["database"] = {"ok": True, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "detail": str(exc)}

    try:
        import ortools
        from ortools.sat.python import cp_model  # noqa: F401

        checks["ortools"] = {"ok": True, "detail": f"ortools {ortools.__version__}"}
    except Exception as exc:  # noqa: BLE001
        checks["ortools"] = {"ok": False, "detail": str(exc)}
    return checks


def health(request):
    checks = _checks()
    all_ok = all(c["ok"] for c in checks.values())
    return JsonResponse({"ok": all_ok, "checks": checks}, status=200 if all_ok else 503)


# --- helpers ----------------------------------------------------------------


def _latest(kind: str) -> Schedule | None:
    return Schedule.objects.filter(kind=kind, feasible=True).order_by("-created_at").first()


def _ai_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def _late_count(schedule: Schedule | None) -> int:
    if schedule is None:
        return 0
    from plant.scheduler.resolve import completion_by_job

    origin = schedule.horizon_start
    completions = completion_by_job(schedule)
    late = 0
    for job in Job.objects.filter(id__in=completions):
        due_min = (job.due_date - origin).total_seconds() / 60
        if completions[job.id] > due_min:
            late += 1
    return late


# --- Schedule board ---------------------------------------------------------


def board(request):
    by = "job" if request.GET.get("by") == "job" else "resource"
    solver = "baseline" if request.GET.get("solver") == "baseline" else "cpsat"
    kind = Schedule.Kind.BASELINE if solver == "baseline" else Schedule.Kind.CPSAT
    schedule = _latest(kind)

    context = {
        "active": "board",
        "by": by,
        "solver": solver,
        "schedule": schedule,
        "seeded": Job.objects.exists(),
        "gantt": gantt_html(schedule, by=by),
        "utilization": utilization_html(_latest(Schedule.Kind.CPSAT)),
        "stats": {
            "jobs": Job.objects.count(),
            "resources": Resource.objects.count(),
            "workers": Worker.objects.count(),
            "aog": Job.objects.filter(is_aog=True).count(),
            "late": _late_count(_latest(Schedule.Kind.CPSAT)),
        },
        "ai_enabled": _ai_enabled(),
    }
    return render(request, "board.html", context)


@require_POST
def seed(request):
    call_command("seed_plant", "--force")
    return redirect("board")


@require_POST
def solve(request):
    if Job.objects.exists():
        run_baseline(rule=Rule.EDD)
        run_cpsat()
    return redirect("board")


# --- Ask --------------------------------------------------------------------


def ask_page(request):
    return render(request, "ask.html", {"active": "ask", "ai_enabled": _ai_enabled()})


@require_POST
def ask_run(request):
    question = (request.POST.get("question") or "").strip()
    if not _ai_enabled():
        return render(request, "_ai_disabled.html")
    if not question:
        return render(request, "_ask_result.html", {"error": "Ask a question first."})
    try:
        result = run_ask(question)
    except Exception as exc:  # noqa: BLE001
        return render(request, "_ask_result.html", {"error": f"The query failed: {exc}"})
    return render(request, "_ask_result.html", {"result": result})


# --- Propose ----------------------------------------------------------------


def propose_page(request):
    return render(
        request,
        "propose.html",
        {
            "active": "propose",
            "ai_enabled": _ai_enabled(),
            "has_schedule": _latest(Schedule.Kind.CPSAT) is not None,
        },
    )


@require_POST
def propose_run(request):
    intent = (request.POST.get("intent") or "").strip()
    if not _ai_enabled():
        return render(request, "_ai_disabled.html")
    if _latest(Schedule.Kind.CPSAT) is None:
        return render(request, "_proposal.html", {"error": "Solve the board before proposing."})
    if not intent:
        return render(request, "_proposal.html", {"error": "Describe a change first."})
    try:
        result = run_propose(intent)
    except Exception as exc:  # noqa: BLE001
        return render(request, "_proposal.html", {"error": f"The proposal failed: {exc}"})
    request_json = (
        json.dumps({"kind": result.request.kind, "params": result.request.params})
        if result.request
        else ""
    )
    return render(request, "_proposal.html", {"result": result, "request_json": request_json})


def _request_from_post(request) -> SchedulerRequest:
    payload = json.loads(request.POST["request_json"])
    return SchedulerRequest(kind=payload["kind"], params=payload["params"])


@require_POST
def propose_approve(request):
    req = _request_from_post(request)
    try:
        schedule = approve_request(req)
    except (ProposalInfeasible, NoCurrentSchedule) as exc:
        return render(request, "_proposal_result.html", {"refused": str(exc)})
    return render(request, "_proposal_result.html", {"approved": True, "schedule": schedule})


@require_POST
def propose_reject(request):
    req = _request_from_post(request)
    reject_request(req, reason=request.POST.get("reason", "rejected by planner"))
    return render(request, "_proposal_result.html", {"rejected": True})


# --- Audit trail ------------------------------------------------------------


def audit(request):
    events = AuditEvent.objects.order_by("-created_at")[:50]
    return render(request, "audit.html", {"active": "audit", "events": events})
