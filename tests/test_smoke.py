"""M0 smoke tests: the app boots, the scaffold renders, OR-Tools is importable.

These guard the M0 acceptance criteria. Richer suites (model invariants, the
crown-jewel constraint tests) arrive with M1–M6.
"""

import pytest


def test_ortools_imports_and_builds_a_model():
    """OR-Tools must import and construct a CP-SAT model — the scheduler depends on it."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x = model.NewIntVar(0, 10, "x")
    model.Add(x == 7)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    assert solver.Value(x) == 7


@pytest.mark.django_db
def test_home_page_serves_and_reports_checks(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"PlantGPT" in resp.content
    # The disclaimer must be present on every page.
    assert b"not a shop-floor control system" in resp.content


@pytest.mark.django_db
def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checks"]["ortools"]["ok"] is True
    assert body["checks"]["database"]["ok"] is True
