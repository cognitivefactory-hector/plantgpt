"""
M6 gated propose layer — the human-in-the-loop write gate (TDD).

The crown jewels of the propose flow:
  * a proposed change is *previewed*, never auto-applied;
  * only an explicit approval persists; reject changes nothing;
  * an infeasible (or rejected) proposal can never be committed;
  * the agent has no tool that mutates the schedule — its only write path is to
    submit a scheduler request, which still goes through the human gate.
See CLAUDE.md "safety invariants", SPEC §4.B.2.
"""

import types
from datetime import UTC, datetime, timedelta

import pytest

from plant.agent.propose import propose
from plant.data.sample import build_expedite_trap
from plant.model.models import AuditEvent, Job, Schedule
from plant.propose.impact import ProposalInfeasible, approve, preview, reject
from plant.propose.request import SchedulerRequest
from plant.scheduler.cpsat import run_cpsat


def _expedite(job, origin, minutes=110):
    return SchedulerRequest(
        kind="expedite",
        params={"job_id": job.id, "new_due_iso": (origin + timedelta(minutes=minutes)).isoformat()},
    )


def _infeasible_solver(**kwargs):
    return Schedule.objects.create(
        kind=Schedule.Kind.CPSAT,
        feasible=False,
        objective_value=None,
        horizon_start=kwargs.get("horizon_start"),
    )


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


def _plant_state():
    """Counts that a non-applied proposal must leave untouched (audit log may grow)."""
    from plant.model.models import MaintenanceWindow, ScheduledOp

    return {
        "schedules": Schedule.objects.count(),
        "scheduled_ops": ScheduledOp.objects.count(),
        "maintenance": MaintenanceWindow.objects.count(),
        "aog_jobs": Job.objects.filter(is_aog=True).count(),
    }


@pytest.mark.django_db
def test_preview_computes_impact_without_applying_the_change():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)  # establish the current board
    state = _plant_state()

    req = SchedulerRequest(
        kind="expedite",
        params={"job_id": hot.id, "new_due_iso": (origin + timedelta(minutes=110)).isoformat()},
    )
    proposal = preview(req)

    # Nothing was applied: no new schedule, no mutated job.
    assert _plant_state() == state
    assert Job.objects.get(id=hot.id).is_aog is False
    # But the impact was computed: the trap slips at least two other lots.
    assert proposal.feasible is True
    assert len(proposal.diff.slipped_job_ids) >= 2


@pytest.mark.django_db
def test_preview_surfaces_a_worse_proposal():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)

    proposal = preview(_expedite(hot, origin))

    assert proposal.feasible is True
    assert proposal.tardiness_after > proposal.tardiness_before  # the expedite makes it worse


@pytest.mark.django_db
def test_approve_applies_the_change_and_persists_a_new_board():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    board = run_cpsat(horizon_start=origin)

    new_board = approve(_expedite(hot, origin))

    assert new_board.feasible is True
    assert new_board.id != board.id  # a fresh schedule was persisted
    assert Job.objects.get(id=hot.id).is_aog is True  # the request was applied
    assert AuditEvent.objects.filter(kind=AuditEvent.Kind.APPROVAL).count() == 1


@pytest.mark.django_db
def test_reject_changes_nothing_and_logs_a_rejection():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)
    state = _plant_state()

    reject(_expedite(hot, origin), reason="slip not worth it")

    assert _plant_state() == state
    assert Job.objects.get(id=hot.id).is_aog is False
    assert AuditEvent.objects.filter(kind=AuditEvent.Kind.REJECTION).count() == 1


@pytest.mark.django_db
def test_preview_surfaces_an_infeasible_result(monkeypatch):
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)  # real board first
    monkeypatch.setattr("plant.propose.impact.run_cpsat", _infeasible_solver)

    proposal = preview(_expedite(hot, origin))

    assert proposal.feasible is False
    assert proposal.diff is None
    assert proposal.tardiness_after is None


@pytest.mark.django_db
def test_approve_refuses_to_commit_an_infeasible_proposal(monkeypatch):
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)
    state = _plant_state()
    monkeypatch.setattr("plant.propose.impact.run_cpsat", _infeasible_solver)

    with pytest.raises(ProposalInfeasible):
        approve(_expedite(hot, origin))

    # Rolled back: nothing applied, no schedule persisted.
    assert _plant_state() == state
    assert Job.objects.get(id=hot.id).is_aog is False
    assert AuditEvent.objects.filter(kind=AuditEvent.Kind.APPROVAL).count() == 0


# --- The conversational propose layer (agent), driven by a fake client. ---


def _expedite_script(job, origin, recommendation, minutes=110):
    due = (origin + timedelta(minutes=minutes)).isoformat()
    return [
        _response(
            [
                _tool_use(
                    "propose_schedule_change",
                    {"kind": "expedite", "job_id": job.id, "new_due_iso": due},
                    "p",
                )
            ]
        ),
        _response(
            [
                _tool_use(
                    "present_proposal",
                    {
                        "narrative": "It slips three lots.",
                        "recommendation": recommendation,
                        "confidence": "high",
                    },
                    "a",
                )
            ]
        ),
    ]


@pytest.mark.django_db
def test_propose_previews_but_applies_nothing_and_returns_a_request_to_gate():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    run_cpsat(horizon_start=origin)
    state = _plant_state()
    client = FakeAnthropic(_expedite_script(hot, origin, "caution"))

    result = propose("Expedite the hot lot", client=client)

    # The agent only previewed — nothing was applied.
    assert _plant_state() == state
    assert Job.objects.get(id=hot.id).is_aog is False
    # But it computed the impact and returned a request for the human gate.
    assert result.proposal.feasible is True
    assert len(result.proposal.diff.slipped_job_ids) >= 2
    assert result.recommendation == "caution"
    assert result.request.kind == "expedite"


@pytest.mark.django_db
def test_propose_agent_has_no_tool_that_mutates_the_schedule():
    client = FakeAnthropic(
        [
            _response(
                [
                    _tool_use(
                        "present_proposal",
                        {"narrative": "n", "recommendation": "reject", "confidence": "low"},
                        "a",
                    )
                ]
            )
        ]
    )

    propose("do nothing", client=client)

    tool_names = {t["name"] for t in client.calls[0]["tools"]}
    # Read tools + the gated propose tool + the terminal answer tool. No apply/mutate tool.
    assert tool_names == {
        "jobs_missing_due_date",
        "resource_utilization",
        "list_jobs",
        "list_resources",
        "propose_schedule_change",
        "present_proposal",
    }


@pytest.mark.django_db
def test_human_can_approve_the_request_the_agent_proposed():
    origin = datetime(2030, 1, 7, tzinfo=UTC)
    hot = build_expedite_trap(base=origin)
    board = run_cpsat(horizon_start=origin)
    client = FakeAnthropic(_expedite_script(hot, origin, "approve"))

    result = propose("Expedite the hot lot for AOG", client=client)
    new_board = approve(result.request)  # the human approves what the agent proposed

    assert new_board.id != board.id
    assert Job.objects.get(id=hot.id).is_aog is True
