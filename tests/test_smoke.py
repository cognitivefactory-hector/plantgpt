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
def test_board_page_serves_with_the_disclaimer(client):
    resp = client.get("/")  # the schedule board is the landing page (M7)
    assert resp.status_code == 200
    assert b"PlantGPT" in resp.content
    # The not-a-control-system disclaimer must be present on every page.
    assert b"Not a shop-floor control system" in resp.content


@pytest.mark.django_db
def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checks"]["ortools"]["ok"] is True
    assert body["checks"]["database"]["ok"] is True
