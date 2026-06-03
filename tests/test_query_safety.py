"""
M5 read-only query layer — safety tests (TDD).

The Ask layer exposes the plant + schedule through *typed read tools* (not raw
SQL). The safety guarantees this file pins:
  * every query tool is read-only — it cannot mutate the database;
  * the agent is given only read tools (plus the terminal answer tool) — there is
    no tool that writes;
  * the query the agent shows is exactly the query that executes.
See CLAUDE.md "safety invariants", SPEC §4.B.1.
"""

import types
from datetime import UTC, datetime, timedelta

import pytest

from plant.agent.ask import ask
from plant.data.sample import build_sample_plant
from plant.model.models import (
    AuditEvent,
    Job,
    Operation,
    Resource,
    Routing,
    Schedule,
    ScheduledOp,
)
from plant.query.tools import READ_TOOLS, run_tool

# --- A tiny fake Anthropic client that replays scripted responses (no API call). ---


def _tool_use(name, tool_input, block_id="tu"):
    return types.SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def _response(content):
    return types.SimpleNamespace(content=content, stop_reason="tool_use")


class FakeAnthropic:
    def __init__(self, scripted_responses):
        self._responses = list(scripted_responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _db_snapshot():
    from django.apps import apps

    return {m.__name__: m.objects.count() for m in apps.get_app_config("plant").get_models()}


@pytest.mark.django_db
def test_every_read_tool_leaves_the_database_unchanged():
    build_sample_plant()
    before = _db_snapshot()

    for tool in READ_TOOLS:
        run_tool(tool.name, {})

    assert _db_snapshot() == before


@pytest.mark.django_db
def test_jobs_missing_due_date_flags_a_late_job():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    res = Resource.objects.create(name="R", capacity=1)
    routing = Routing.objects.create(part_name="Late")
    op = Operation.objects.create(
        routing=routing, sequence=1, name="op", resource=res, duration_minutes=60
    )
    job = Job.objects.create(routing=routing, quantity=1, due_date=origin + timedelta(minutes=30))
    sched = Schedule.objects.create(
        kind=Schedule.Kind.CPSAT, feasible=True, objective_value=30, horizon_start=origin
    )
    # Completes at minute 60, 30 minutes after its due date.
    ScheduledOp.objects.create(
        schedule=sched, job=job, operation=op, resource=res, start_minute=0, end_minute=60
    )

    out = run_tool("jobs_missing_due_date", {})

    assert out["count"] == 1
    assert out["jobs_missing_due_date"][0]["job_id"] == job.id
    assert out["jobs_missing_due_date"][0]["minutes_late"] == 30


@pytest.mark.django_db
def test_ask_exposes_only_read_tools_plus_the_answer_tool():
    client = FakeAnthropic(
        [_response([_tool_use("present_answer", {"narrative": "ok", "confidence": "low"}, "a")])]
    )

    ask("anything", client=client)

    tool_names = {t["name"] for t in client.calls[0]["tools"]}
    assert tool_names == {
        "jobs_missing_due_date",
        "resource_utilization",
        "list_jobs",
        "list_resources",
        "present_answer",
    }


@pytest.mark.django_db
def test_ask_shows_the_query_it_runs_and_returns_a_confidence():
    build_sample_plant()  # has exactly two AOG jobs
    client = FakeAnthropic(
        [
            _response([_tool_use("list_jobs", {"aog_only": True}, "q1")]),
            _response(
                [
                    _tool_use(
                        "present_answer",
                        {"narrative": "Two AOG lots are queued.", "confidence": "high"},
                        "a",
                    )
                ]
            ),
        ]
    )

    result = ask("Which lots are AOG?", client=client)

    # The shown query is exactly the query that executed.
    assert result.shown_queries == [{"tool": "list_jobs", "args": {"aog_only": True}}]
    assert result.data[0]["tool"] == "list_jobs"
    assert result.data[0]["result"]["count"] == 2
    assert result.confidence == "high"
    assert "AOG" in result.narrative


@pytest.mark.django_db
def test_ask_logs_an_audit_event_with_the_shown_query():
    client = FakeAnthropic(
        [
            _response([_tool_use("list_resources", {}, "q1")]),
            _response(
                [
                    _tool_use(
                        "present_answer", {"narrative": "5 resources.", "confidence": "high"}, "a"
                    )
                ]
            ),
        ]
    )

    result = ask("List the resources", client=client)

    event = AuditEvent.objects.get(id=result.audit_event_id)
    assert event.kind == AuditEvent.Kind.QUERY
    assert event.payload["question"] == "List the resources"
    assert event.payload["shown_queries"] == [{"tool": "list_resources", "args": {}}]
