# Decision Record — PlantGPT

The four questions that make judgment portable. These are **first-draft answers** (from `SPEC.md` §1.1) — pressure-test and revise them in the recorded whiteboard session, then keep what survives.

## Situation
A plant runs many parts through shared wet-process lines (clean → etch → anodize → seal → inspect), each with hard constraints: tank/line capacity, **certified operators only** (NADCAP), **time-between-operations limits**, maintenance windows, and **AOG due dates** that jump the queue. Scheduling lives in spreadsheets and people's heads. When something slips, nobody can quickly answer "what's late and why" — and a hasty re-sequence to expedite one lot can quietly violate a constraint and scrap another. Facts I have: jobs, routings, resources, due dates. Facts I'm missing: a single queryable model of the floor, and a safe way to test a schedule change before committing it.

## Decision
Build (A) a **constraint-based scheduler** that produces a feasible schedule honoring routing precedence, capacity, worker shifts & certifications, time-between-ops, and due dates; and (B) a **conversational layer** that answers with **auditable, read-only queries (it shows its query)** and **proposes** schedule changes a human reviews and approves.
**Rejected:** (1) a free-form chatbot answering from memory (unauditable); (2) letting the AI **auto-commit** schedule changes (reckless on a regulated floor); (3) a purely heuristic scheduler with no feasibility guarantee — though I keep an explainable dispatching baseline alongside the solver.

## Risk
Two killers: (a) the NL layer silently runs a *wrong* query and a planner trusts a wrong "what's late" answer; (b) an AI-proposed re-sequence **violates a hard constraint** (uncertified operator, exceeded time-between-ops) and creates a nonconformance or scraps a lot. Mitigations: queries are read-only, schema-constrained, shown with a confidence signal; the **scheduler enforces hard constraints so no proposed change can ever violate one**; every change is a human-approved proposal with an impact preview; full audit trail.
**Consciously accepted:** the system is advisory and a touch slower than full automation — the right call on a floor that scraps real parts.

## Change
Anyone can ask the plant a question and get an *auditable* answer in seconds; a planner can test an expedite and see exactly what it costs *before* committing; AOG jobs get pulled forward **safely**, because re-sequencing can't break certifications or time-between-ops. The prevented loss: the wrong-data decision and the constraint-violating expedite that would have scrapped a lot.

## Whiteboard session
- Recording: _TBD_
- The change I recommended against (and why): _…_
- What the AI can never do: _commit a change; produce an infeasible schedule._
- What I revised under push-back / held the line on: _…_

---

## Engineering decisions (recorded as built)
- **Backend:** Django + Postgres — one framework across the whole portfolio.
- **Scheduler:** OR-Tools CP-SAT (interval vars, NoOverlap per resource, precedence + time-between-ops, cert/shift-limited worker assignment, weighted-tardiness objective) + an EDD/critical-ratio dispatching baseline as the explainable foil. Hard-constraint enforcement lives in the solver, never in LLM output.
- **AI:** Anthropic SDK, tool use split into **read tools** and a **single gated propose tool** — no tool mutates the schedule directly.
- **Host:** Render (Dockerized + Postgres) behind Cloudflare. Verify OR-Tools wheels install in the image early.

### M0 scaffold choices (recorded as built)
- **Python 3.12 / Django 5.1.** `python:3.12-slim` ships manylinux wheels for OR-Tools (verified: `ortools 9.15`), so the image needs no C build toolchain.
- **Single `pyproject.toml`** for deps + ruff + pytest config (one source of truth); this is an application, not a distributable library.
- **Layout:** a `config/` Django project (settings/urls/wsgi/asgi) + one `plant/` app holding `model/ scheduler/ query/ propose/ agent/ data/` subpackages — PLAN.md's layout mapped onto Django conventions. `plant/models.py` re-exports `plant/model/models.py` so the app loader finds the (future) domain model.
- **12-factor config:** `DATABASE_URL` via `dj-database-url`, `whitenoise` for static, `gunicorn` in prod, `runserver` in the compose dev override. Same image runs locally and on Render; only `DATABASE_URL` differs.
- **Deploy:** `render.yaml` Blueprint (Docker web service + managed Postgres, `/healthz` health check, `ANTHROPIC_API_KEY` as a dashboard secret) so M8 is wired now. CI: GitHub Actions runs ruff + pytest against a Postgres service.
- **M0 self-check:** the landing page and `/healthz` assert the three acceptance criteria live — page renders, Postgres answers, OR-Tools imports.

### M1 domain-model choices (recorded as built)
- **The model stores facts and read helpers; it does NOT enforce hard constraints.** `Worker.is_certified_for(op)` is a *query* the solver reads — certification/time-between-ops/capacity are enforced in the CP-SAT solver (M3), so the safety core stays in one place (CLAUDE.md invariants). Keeping enforcement out of the ORM avoids two competing sources of truth.
- **time-between-ops** is `Operation.max_gap_after_minutes` (nullable) — the max minutes allowed between an op's end and its successor's start. Most transitions have no cap; the Bracket etch→anodize transition does. This is the domain constraint an AI-only engineer wouldn't model.
- **AOG = a high tardiness weight,** not a separate queue. `Job.priority_weight` returns `AOG_WEIGHT` (100) when `is_aog`, else the stored weight, so the existing weighted-tardiness objective pulls AOG jobs earlier without special-casing the solver.
- **Schedule is feasible-with-objective or infeasible-with-none** — the data shape itself refuses to present a half-built plan as feasible.
- **Time grid:** `ScheduledOp` stores integer `start_minute`/`end_minute` from a `Schedule.horizon_start`, matching CP-SAT's integer interval variables (M3).
- **Seed:** `build_sample_plant()` + `manage.py seed_plant` load a coherent (schedulable) minimal plant; M4 expands it to the full corpus with the tight expedite scenario.

### M2 dispatching-baseline choices (recorded as built)
- **Baseline = a priority list-scheduler**, not an optimizer. Each step picks the highest-priority *ready* operation (by rule) and places it at the earliest minute a resource slot is free and the job's prior op has finished. Guarantees precedence + capacity; makes no optimality claim. It's the explainable foil that keeps the CP-SAT solver honest (and a fallback demo if the solver stalls — see the risk register).
- **Capacity = N parallel slots per resource**, tracked as a min-heap of free-times; an op takes the earliest-free slot. At most `capacity` operations overlap, by construction.
- **The baseline only enforces precedence + capacity.** It does NOT assign workers, and does NOT enforce certification or time-between-ops — those are the CP-SAT solver's hard constraints (M3). Keeping the baseline deliberately "dumber" makes the solver's added value visible and keeps a single home for hard-constraint enforcement.
- **AOG is not special-cased in the baseline.** EDD/CR pull an AOG job forward only because its due date is soonest; the AOG *weight* is a soft objective for the solver, not the rule scheduler. (Observed: on the seed plant, EDD pulls the AOG lot first on the anodize tank purely via its due date.)
- **Three rules (EDD / SPT / CR)** as required scope, each pinned by a test that distinguishes it — notably CR diverges from EDD when a later-due job has far less slack per unit work.
- **Quantity is informational in M2:** an operation's `duration_minutes` is treated as the whole job's processing time for that step (one batch). Quantity-scaled durations can come later if needed.
