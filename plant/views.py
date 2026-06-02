"""
M0 landing + health views.

The landing page is intentionally a self-check: it proves the three M0 acceptance
criteria at a glance — the page renders, Postgres answers, and OR-Tools imports.
Real screens (Schedule board / Ask / Propose) replace this in M7.
"""

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def _checks() -> dict[str, dict]:
    """Run the M0 self-checks; never raise (a failure is reported, not 500)."""
    checks: dict[str, dict] = {}

    # Database reachable? Connectivity (portable SELECT 1) is the pass/fail signal;
    # the version string is best-effort display only.
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

    # OR-Tools importable? (the scheduler's safety core depends on it — M3)
    try:
        import ortools
        from ortools.sat.python import cp_model  # noqa: F401

        checks["ortools"] = {"ok": True, "detail": f"ortools {ortools.__version__}"}
    except Exception as exc:  # noqa: BLE001
        checks["ortools"] = {"ok": False, "detail": str(exc)}

    return checks


def home(request):
    checks = _checks()
    all_ok = all(c["ok"] for c in checks.values())
    return render(request, "home.html", {"checks": checks, "all_ok": all_ok})


def health(request):
    """Liveness/readiness endpoint for Render health checks."""
    checks = _checks()
    all_ok = all(c["ok"] for c in checks.values())
    return JsonResponse({"ok": all_ok, "checks": checks}, status=200 if all_ok else 503)
