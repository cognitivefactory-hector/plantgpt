"""
M7 view smoke tests. The UI is demonstrated by the recording (PLAN.md), so these
only guard that the screens render and that Ask/Propose degrade safely without an
API key — the agent and gate logic itself is covered in their own suites.
"""

import pytest

from plant.data.sample import build_sample_plant
from plant.scheduler.cpsat import run_cpsat


@pytest.mark.django_db
def test_board_renders_empty_and_after_solving(client):
    assert client.get("/").status_code == 200  # empty plant, no schedule

    build_sample_plant()
    run_cpsat()
    resp = client.get("/?solver=cpsat&by=resource")
    assert resp.status_code == 200
    assert b"Gantt" in resp.content


@pytest.mark.django_db
def test_ask_propose_audit_pages_render(client):
    assert client.get("/ask").status_code == 200
    assert client.get("/propose").status_code == 200
    assert client.get("/audit").status_code == 200


@pytest.mark.django_db
def test_ask_run_without_api_key_degrades_to_a_notice(client):
    # No ANTHROPIC_API_KEY in the test env → no API call, just the notice.
    resp = client.post("/ask/run", {"question": "what is late?"})
    assert resp.status_code == 200
    assert b"AI layer not configured" in resp.content


@pytest.mark.django_db
def test_propose_run_without_api_key_degrades_to_a_notice(client):
    resp = client.post("/propose/run", {"intent": "expedite the hot lot"})
    assert resp.status_code == 200
    assert b"AI layer not configured" in resp.content
