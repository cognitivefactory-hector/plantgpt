"""
Propose — the gated conversational write layer (M6).

Claude turns a plain-English intent into ONE scheduler request, previews its impact
(via the constraint-enforcing solver), and recommends — it cannot apply anything. Its
only "write-ish" tool, propose_schedule_change, runs a *preview* that rolls back; there
is no tool that mutates the schedule. A human then calls approve()/reject() on the
returned request. (SPEC §4.B.2; CLAUDE.md safety invariants.)

The Anthropic client is injectable so the loop is unit-tested without the API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from plant.agent.prompts import PROPOSE_SYSTEM
from plant.propose.impact import Proposal, preview
from plant.propose.request import SchedulerRequest
from plant.query.tools import run_tool, tool_specs

DEFAULT_MODEL = "claude-opus-4-8"

PROPOSE_TOOL = {
    "name": "propose_schedule_change",
    "description": (
        "Submit ONE proposed schedule change for impact analysis. This does NOT apply "
        "the change — it previews what re-solving under it would cost (which lots slip, "
        "the tardiness delta, feasibility). Call it once, then present_proposal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["expedite", "block_resource"]},
            "job_id": {"type": "integer", "description": "Job to expedite (kind=expedite)."},
            "new_due_iso": {"type": "string", "description": "New due date, ISO 8601 (optional)."},
            "resource_name": {
                "type": "string",
                "description": "Resource to block (kind=block_resource).",
            },
            "start_iso": {"type": "string", "description": "Block start, ISO 8601."},
            "end_iso": {"type": "string", "description": "Block end, ISO 8601."},
        },
        "required": ["kind"],
        "additionalProperties": False,
    },
}

PRESENT_PROPOSAL_TOOL = {
    "name": "present_proposal",
    "description": "Present the proposal and recommendation to the planner. Call once, last.",
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative": {"type": "string", "description": "What it does and what it costs."},
            "recommendation": {"type": "string", "enum": ["approve", "caution", "reject"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["narrative", "recommendation", "confidence"],
        "additionalProperties": False,
    },
}

# Only the params each request kind needs — keeps SchedulerRequest.params clean.
_PARAMS_BY_KIND = {
    "expedite": ("job_id", "new_due_iso"),
    "block_resource": ("resource_name", "start_iso", "end_iso"),
}


def _request_from_tool_input(tool_input: dict) -> SchedulerRequest:
    kind = tool_input["kind"]
    keys = _PARAMS_BY_KIND[kind]
    params = {k: tool_input[k] for k in keys if tool_input.get(k) is not None}
    return SchedulerRequest(kind=kind, params=params)


@dataclass
class ProposeResult:
    intent: str
    request: SchedulerRequest | None = None  # pass to approve()/reject()
    proposal: Proposal | None = None  # the previewed impact
    narrative: str = ""
    recommendation: str = "reject"
    confidence: str = "low"


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _impact_summary(proposal: Proposal) -> dict:
    """The impact handed back to the agent (and rendered to the planner)."""
    if not proposal.feasible:
        return {"feasible": False, "note": "Re-solving under this request is infeasible."}
    return {
        "feasible": True,
        "slipped_job_ids": proposal.diff.slipped_job_ids,
        "improved_job_ids": proposal.diff.improved_job_ids,
        "tardiness_before": proposal.tardiness_before,
        "tardiness_after": proposal.tardiness_after,
    }


def propose(
    intent: str, *, client=None, model: str = DEFAULT_MODEL, max_steps: int = 6
) -> ProposeResult:
    """Turn an intent into a previewed proposal + recommendation. Applies nothing."""
    client = client or _default_client()
    tools = tool_specs() + [PROPOSE_TOOL, PRESENT_PROPOSAL_TOOL]
    messages: list[dict] = [{"role": "user", "content": intent}]
    result = ProposeResult(intent=intent)

    for _ in range(max_steps):
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {"type": "text", "text": PROPOSE_SYSTEM, "cache_control": {"type": "ephemeral"}}
            ],
            tools=tools,
            messages=messages,
        )

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            break

        messages.append({"role": "assistant", "content": resp.content})

        answer = next((b for b in tool_uses if b.name == "present_proposal"), None)
        if answer is not None:
            result.narrative = answer.input.get("narrative", "")
            result.recommendation = answer.input.get("recommendation", "reject")
            result.confidence = answer.input.get("confidence", "low")
            break

        results = []
        for tu in tool_uses:
            if tu.name == "propose_schedule_change":
                request = _request_from_tool_input(dict(tu.input))
                proposal = preview(request)  # previews + audits; applies nothing
                result.request = request
                result.proposal = proposal
                content = json.dumps(_impact_summary(proposal))
            else:
                content = json.dumps(run_tool(tu.name, dict(tu.input)), default=str)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content})
        messages.append({"role": "user", "content": results})

    return result
