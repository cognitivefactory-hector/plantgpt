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

### M3 CP-SAT solver choices (recorded as built) — the safety core
- **Hard-constraint enforcement lives only here.** Each operation is an interval var; precedence, resource capacity (no-overlap/cumulative), time-between-ops, maintenance windows, certified worker assignment, and worker single-tasking are all CP-SAT constraints. The solver returns a feasible schedule **or** an explicit `feasible=False` with no scheduled ops — never a partial/hand-built plan.
- **time-between-ops cannot cause infeasibility on its own.** With finite maintenance windows and no hard deadlines, a schedule can always wait out downtime and run everything late at gap 0 — so the over-constrained→infeasible crown jewel is proven via **certification** (a required cert nobody holds → infeasible), which is robust and finite. time-between-ops enforcement is proven by a maintenance-bounded test where the cap provably drags the prior op late.
- **Worker assignment = exactly-one certified worker per op + per-worker no-overlap** (optional intervals present iff assigned). An op with no eligible worker short-circuits to infeasible — never staffed by an unqualified operator. *Every* operation must be staffed (a plant can't run unstaffed), so even cert-free ops consume a worker.
- **Shifts reuse the same no-overlap machinery.** A worker's off-shift periods (the complement of their daily shift windows within the horizon) are added as fixed "blocker" intervals to that worker's no-overlap set — so one constraint enforces both single-tasking *and* on-shift-only. Shift times are wall-clock times of day in the `horizon_start` tz (UTC default); `horizon_start` is injectable so shift/due math is deterministic in tests.
- **Shifts don't create real infeasibility (daily recurrence).** Like time-between-ops, a worker is eventually on-shift again, so "off-shift" can't make a finite-maintenance plan infeasible — it just delays it. The horizon is therefore widened (≈ work ÷ 8h/day, + 2 days) so a plan that waits for the next shift stays feasible instead of being falsely cut off by a tight horizon. A loose horizon only adds room; it never turns a genuinely feasible plan infeasible.
- **AOG = a soft weight, not a hard rule.** The objective minimizes Σ `priority_weight`·tardiness; AOG's high weight pulls it earlier, but the solver can still choose otherwise if hard constraints demand — AOG never overrides feasibility.
- **Capacity model:** `cap == 1` → `add_no_overlap`; `cap > 1` → `add_cumulative` (demand 1 per op). Maintenance windows are full-capacity blockers (`demand = cap`).
- **Horizon:** total serial work + latest maintenance end + shift slack (≈ work ÷ 8h/day, + 2 days) + 1 — a safe upper bound that also lets work wait for on-shift windows; tardiness vars get headroom for already-past-due jobs.

### M4 corpus + disruption re-solve choices (recorded as built)
- **Disruption re-solve always goes through CP-SAT.** A disruption is a callable that mutates the plant (`machine_down` adds a maintenance window; `expedite` marks a job AOG + pulls its due date); `resolve()` solves, applies it, re-solves, and diffs. Because the re-solve is the same constraint solver, a disruption response can never break a hard constraint — same safety core as everywhere.
- **Both solves share one `horizon_start`** so completion minutes are directly comparable; the diff is per-job completion delta (mutation-safe, read from `ScheduledOp` rows), with weighted tardiness captured *before* the mutation (original dues) and *after* (new dues).
- **The expedite trap is a separate, deterministic fixture** (`build_expedite_trap`), not buried in the main corpus, so the "recommended-against" trade is reproducible and testable: three lots that just make their dates + one slack hot lot; expediting the hot lot (due → +110 min) slips all three by 60 min (tardiness 0 → 150). This is the data behind whiteboard challenge #6.
- **`resolve()` applies the disruption to the plant** (the disruption "happened"); the M6 propose layer adds the approve/reject gate (savepoint/rollback) on top — kept out of M4 to stay focused.
- **Corpus sized for a live demo, not maximal realism:** ~16 jobs / 4 routings / 5 resources / 5 workers solves to optimal in ~0.2s (SPEC §11's "fast enough to feel live"). Maintenance windows are on the two bottleneck tanks only (not every resource) to keep it tractable and clearly feasible. Anodize (cap 1) is the deliberate bottleneck; 2 of 5 workers are anodize-certified.

### M5 Ask (read-only NL query) choices (recorded as built)
- **Typed read tools, not text-to-SQL** (resolving SPEC §11's open question). The agent answers by calling a small set of typed tools (`jobs_missing_due_date`, `resource_utilization`, `list_jobs`, `list_resources`), each a constrained read-only ORM query. Read-only is guaranteed *by construction* — there is no tool that writes — rather than by trusting the model not to emit a mutating query. "The query it shows" = the tool name + args, surfaced and audited.
- **A single terminal `present_answer` tool** carries the narrative + a `high/medium/low` confidence flag out of the loop. The agent is given only the read tools plus this answer tool; neither mutates anything. (The confidence flag is the SPEC §4.B.1 "confidence signal".)
- **Tools read the latest schedule; they never create one.** Generating a schedule is a write (a `Schedule` row), so the read layer reads the most recent feasible CP-SAT schedule and reports "no schedule yet" if absent — keeping Ask strictly read-only.
- **Model: `claude-opus-4-8`, adaptive thinking, prompt-cached system prompt** (per the claude-api skill). `claude-sonnet-4-6` is the cost-down option if query volume grows — recorded but not adopted; the agent runs on-demand and token-capped.
- **The Anthropic client is injectable** (`ask(question, *, client=...)`) so the whole loop is unit-tested against a fake client with scripted tool calls — no API key, no network in CI. The one live integration run waits for M8 (key as a host secret).
- **Every Ask is logged** to `AuditEvent(kind=QUERY)` with the question, the shown queries, and the confidence — the auditable trail (SPEC §4.B.3).
