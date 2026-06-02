# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PlantGPT is a portfolio flagship: a constraint-based production scheduler (Pillar A) with a gated conversational AI layer on top (Pillar B). It models a synthetic wet-process plant (clean → etch → anodize → seal → inspect). **It is illustrative, on synthetic data — not connected to any MES/ERP and not a shop-floor control system.** Keep that disclaimer in the README footer and UI.

The repo is currently **scaffold-only**: `SPEC.md`, `PLAN.md`, `DECISIONS.md`, `README.md`, `LICENSE`, `.gitignore`. No application code, build tooling, or tests exist yet. The build follows `PLAN.md` milestones **M0 → M9**.

This is one of **three equal deliverables**: the app, the Decision Record (`DECISIONS.md`), and a recorded whiteboard session. The judgment behind the design is graded as heavily as the code — keep `DECISIONS.md` updated live as decisions are made (see its "Engineering decisions (recorded as built)" section).

## Source of truth — read these first

- **`SPEC.md`** — full product spec, architecture diagram (§6), CP-SAT model details (§7), synthetic-data design (§5), non-goals (§4.4).
- **`PLAN.md`** — the M0→M9 build sequence with per-milestone tasks, acceptance criteria, suggested repo layout (§"Suggested repo layout"), and testing strategy.
- **`DECISIONS.md`** — the Situation/Decision/Risk/Change record; update as you build.

Do not duplicate those documents here. When in doubt about scope or sequencing, they win.

## The safety invariants (non-negotiable — this is the whole point)

These cross-cutting rules are *the* hireable signal of the project. Any code that weakens them is wrong, even if it works:

1. **Hard-constraint enforcement lives only in the scheduler** (`scheduler/cpsat.py`), never in LLM output. Hard constraints: routing precedence, resource capacity, operator certification, **time-between-operations** max, maintenance windows, shift availability. The solver returns a feasible schedule **or** an explicit "infeasible" — no path ever presents a hand-built or LLM-built schedule as feasible.
2. **The AI can never auto-commit.** Every schedule change is a human-approved proposal with an impact preview (what slips, tardiness delta).
3. **Two separated tool sets for the Claude agent:** read tools (constrained, read-only queries that are *shown* to the user with a confidence signal) and a **single gated propose tool**. There is **no tool that mutates the schedule directly.** The agent's only write path is submitting a *scheduler request* (priority bump / resource block / due-date change) that the solver re-solves under.
4. **No NL write to arbitrary tables / no raw SQL mutation.**

If a change would let the AI commit, let raw LLM output become a schedule, or let a query mutate data — stop; that breaks the design thesis.

## Architecture (planned — see SPEC §6)

Backend is Django + Postgres. Intended module layout (`app/`):
- `model/` — `Job`/`Part`, `Operation`, `Routing`, `Resource`, `Worker`, `Certification`, `Shift`, `Schedule`, `ScheduledOp`, `AuditEvent`.
- `scheduler/` — `dispatch.py` (EDD / critical-ratio / SPT explainable baseline), `cpsat.py` (OR-Tools CP-SAT — the safety core), `resolve.py` (disruption re-solve + diff).
- `query/` — documented read-only schema + typed query tools (typed tools preferred over text-to-SQL for safety).
- `propose/` — NL intent → scheduler request → re-solve → impact preview.
- `agent/` — Claude tool-use: `ask.py` (read tools), `propose.py` (gated propose tool), `prompts.py`, `schemas.py`.
- `data/` — seeded synthetic plant corpus.

Two solvers run side by side on purpose: the dispatching baseline keeps the CP-SAT solver honest and is the explainable foil. Build the domain model + scheduler **first** (M1–M4, demoable alone); the AI layer goes on **last** and is deliberately boxed in.

## Conventions

- **TDD throughout.** The scheduler's constraint enforcement is the crown jewel — test it hardest: certification never violated, time-between-ops never exceeded, capacity/no-overlap holds, over-constrained scenarios return "infeasible," AOG weighting pulls jobs earlier. Safety tests on the agent: read tools are read-only, the only write path is a gated proposal, no direct-mutation tool exists.
- **Mock the Anthropic API in unit tests;** keep the one live integration run out of CI. Don't chase UI test coverage — the UI is demonstrated by the recording.
- **Synthetic data only, fixed seed, obviously-fictional numbers.** No employer routings/parts/capacities/names, ever.
- When building the Claude layer, invoke the **`claude-api`** skill and follow Anthropic SDK best practices (tool use, structured output for the shown query + proposals, prompt caching for system prompt + schema).
- Tooling planned per spec: **pytest + ruff**, Docker (`docker-compose.yml` with Postgres), GitHub Actions CI. Stack libs: `ortools`, `django`, `psycopg`, `pandas`, `plotly`, `anthropic`. Verify `ortools` wheels install in the deploy image early (M0).
- **Never commit `ANTHROPIC_API_KEY`** — `.env` is gitignored; use host secrets.

## Commands

None yet — build tooling lands in M0. When it exists, expect `docker compose up` for local run and `pytest` / `ruff` for test + lint. Update this section once those are real.
