"""
Ask — the read-only conversational layer (M5).

Claude answers a plain-English question by calling the typed read tools (it shows the
query it runs), then calls a single `present_answer` tool with a narrative and a
confidence flag. The agent is given ONLY read tools plus that terminal answer tool —
there is no tool that mutates the schedule or the database. Every query and answer is
logged to the audit trail. (SPEC §4.B.1; CLAUDE.md safety invariants.)

The Anthropic client is injectable so unit tests can drive the loop without the API.
Follows the claude-api skill: claude-opus-4-8, prompt-cached system prompt, typed tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from plant.agent.prompts import ASK_SYSTEM
from plant.model.models import AuditEvent
from plant.query.tools import run_tool, tool_specs

DEFAULT_MODEL = "claude-opus-4-8"

# Terminal tool: the agent calls this once to deliver its answer + confidence. It is
# not a read tool and not a write — it carries the synthesized result out of the loop.
ANSWER_TOOL = {
    "name": "present_answer",
    "description": (
        "Present the final answer to the planner. Call this exactly once, after you "
        "have gathered the data you need."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative": {"type": "string", "description": "Concise plain-English answer."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["narrative", "confidence"],
        "additionalProperties": False,
    },
}


@dataclass
class AskResult:
    question: str
    shown_queries: list[dict] = field(default_factory=list)  # [{"tool", "args"}] — auditable
    data: list[dict] = field(default_factory=list)  # [{"tool", "result"}]
    narrative: str = ""
    confidence: str = "low"
    audit_event_id: int | None = None


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def ask(question: str, *, client=None, model: str = DEFAULT_MODEL, max_steps: int = 6) -> AskResult:
    """Answer a read-only question over the plant + schedule, auditing the query."""
    client = client or _default_client()
    tools = tool_specs() + [ANSWER_TOOL]
    messages: list[dict] = [{"role": "user", "content": question}]
    shown_queries: list[dict] = []
    data: list[dict] = []

    narrative, confidence = "Unable to answer within the step limit.", "low"

    for _ in range(max_steps):
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[{"type": "text", "text": ASK_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        )

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            narrative, confidence = _text(resp), "low"  # answered without the answer tool
            break

        messages.append({"role": "assistant", "content": resp.content})

        answer = next((b for b in tool_uses if b.name == "present_answer"), None)
        if answer is not None:
            narrative = answer.input.get("narrative", "")
            confidence = answer.input.get("confidence", "low")
            break

        results = []
        for tu in tool_uses:
            args = dict(tu.input)
            shown_queries.append({"tool": tu.name, "args": args})
            result = run_tool(tu.name, args)  # read-only by construction
            data.append({"tool": tu.name, "result": result})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, default=str),
                }
            )
        messages.append({"role": "user", "content": results})

    event = AuditEvent.objects.create(
        kind=AuditEvent.Kind.QUERY,
        payload={"question": question, "shown_queries": shown_queries, "confidence": confidence},
        note=question[:255],
    )
    return AskResult(
        question=question,
        shown_queries=shown_queries,
        data=data,
        narrative=narrative,
        confidence=confidence,
        audit_event_id=event.id,
    )
