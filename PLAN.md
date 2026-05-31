# PlantGPT — Implementation Plan

Companion to `SPEC.md`. The build sequence: milestones, concrete tasks, acceptance criteria, and the definition of done. Self-contained — hand this repo to a fresh session and start.

- **Repo:** `plantgpt` (public, under `cognitivefactory-hector`)
- **Scale:** Flagship (~4 weeks). Two systems: a constraint scheduler and a gated conversational layer.
- **Approach:** build the **domain model and the constraint scheduler first** — the scheduler is the safety core that makes every AI proposal impossible to break. The LLM layer goes on last and is deliberately boxed in (read tools + one propose tool, never direct mutation).

> **Illustrative on synthetic data. Not a shop-floor control system.** Keep the disclaimer in the footer and README.

---

## The spine (carry through every milestone)

Keep `DECISIONS.md` open and capture reasoning live:

> **Situation** · **Decision** (incl. what you *rejected* — auto-commit, free-form chatbot, heuristic-only) · **Risk** (incl. what you *accepted* — advisory, not autonomous) · **Change**.

The hardest decision (AI proposes, the constraint-enforcing scheduler + human dispose) is the spine of the **recorded whiteboard session** — see `SPEC.md` §3.

---

## Prerequisites
- Python 3.11+, Docker, a GitHub account (`gh` authenticated).
- `ortools` (verify pip install on your base image), Postgres.
- An `ANTHROPIC_API_KEY` (in `.env`, gitignored — **never committed**) for the conversational layer.

---

## Milestones

### M0 — Repo scaffold *(½ day)*
- [ ] Folder + `SPEC.md` + `PLAN.md`.
- [ ] `README.md` (stub + disclaimer), `DECISIONS.md` (paste template from `SPEC.md` §10), `.gitignore` (Python **+ `.env`**), `LICENSE` (MIT).
- [ ] Django + Postgres via `docker-compose.yml`; `pyproject.toml`/`requirements.txt` incl. `ortools`; `Dockerfile`; verify `ortools` imports in the container.
- [ ] Record framework + model + solver choices in `DECISIONS.md`.
- [ ] `gh repo create … --public --push`.
- **Acceptance:** `docker compose up` serves a page, connects to Postgres, and `import ortools` works; repo on GitHub.

### M1 — Domain model (TDD) *(1–2 days)*
- [ ] Models: `Resource` (capacity, maintenance window), `Operation`, `Routing`, `Part`/`Job` (qty, due date, AOG weight), `Worker` (shift), `Certification`, `Schedule`, `ScheduledOp`, `AuditEvent`.
- [ ] Encode the hard-constraint data: per-step times, **time-between-ops** limit on a transition, cert requirements per operation.
- [ ] **Tests:** model invariants (a job's routing is ordered; an operation names a required cert; an AOG job carries higher weight).
- **Acceptance:** `pytest` green; fixtures load a coherent synthetic plant.

### M2 — Dispatching baseline scheduler (TDD) *(1 day)*
- [ ] `scheduler/dispatch.py`: EDD / Critical-Ratio / SPT rules producing a feasible schedule respecting precedence + resource capacity.
- [ ] **Tests:** output respects routing order and never double-books a resource beyond capacity; EDD orders by due date.
- **Acceptance:** `pytest` green; baseline produces a valid (if not optimal) Gantt.

### M3 — CP-SAT solver with hard constraints (TDD) *(3–4 days)* — **the safety core**
- [ ] `scheduler/cpsat.py`: OR-Tools model — operations as interval vars; `NoOverlap` per resource; precedence; **time-between-ops**; worker assignment limited to **certified + on-shift**; maintenance windows; objective = weighted tardiness (AOG weighted).
- [ ] Return either a feasible schedule or an explicit **infeasible** result. **No path returns a hand/LLM-built schedule as feasible.**
- [ ] **Tests (the crown jewels):**
  - No schedule violates certification (an uncertified worker is never assigned).
  - No transition exceeds the time-between-ops limit.
  - Capacity / no-overlap holds on every resource.
  - An over-constrained scenario returns "infeasible," not a silent bad plan.
  - Raising an AOG job's weight pulls it earlier.
- **Acceptance:** `pytest` green; all constraint-violation tests pass; solver beats baseline on weighted tardiness.

### M4 — Synthetic plant corpus + disruption re-solve *(1 day)*
- [ ] Author the §5 corpus (resources, routings incl. a time-between-ops transition, certified/uncertified workers, ~15–25 jobs incl. 1–2 AOG, and the tight "expedite-looks-free-but-isn't" scenario).
- [ ] `scheduler/resolve.py`: apply a disruption (machine down / hot job) → re-solve → diff.
- [ ] Tests: disruption re-solve stays feasible; the tight scenario shows the hidden slippage.
- **Acceptance:** corpus loads; re-solve produces a sensible delta.

### M5 — Read-only NL query layer *(2 days)*
- [ ] `query/`: expose a **documented read-only schema** (or typed query tools — preferred).
- [ ] `agent/ask.py`: Claude tool-use restricted to **read tools**; the agent emits the query it intends to run (surfaced to the user) + a confidence; execute read-only; render result + narrative.
- [ ] **Tests (mocked API):** the agent can only call read tools; a generated query is read-only (no mutation); the shown query matches what executes.
- **Acceptance:** ask "which jobs miss their due date?" → see the query, a chart, an answer, and a confidence flag.
- **Note:** if building in Claude Code, invoke the `claude-api` skill here.

### M6 — Gated NL propose layer *(2 days)* — **the human-in-the-loop gate**
- [ ] `propose/`: translate an NL intent into a **scheduler request** (priority bump / resource block / due-date change) — the **only** write path.
- [ ] Re-solve under the request via CP-SAT; build an **impact preview** (diff: what slips, tardiness delta, feasibility).
- [ ] Approve/Reject: only on approval does the new schedule persist; log to audit trail.
- [ ] **Tests:** a proposed change is never auto-applied; an infeasible/worse proposal is surfaced as such; the agent has no tool that mutates the schedule directly.
- **Acceptance:** "expedite lot 4471 for AOG" → proposal + impact → approve updates the board; a bad expedite is shown as worse and can be rejected.

### M7 — UI: Schedule board / Ask / Propose *(2–3 days)*
- [ ] Gantt board (by resource + by job), AOG/due-date flags, **baseline-vs-CP-SAT toggle**, utilization charts.
- [ ] Ask tab: query box → shown query + chart + narrative + confidence.
- [ ] Propose tab: intent → schedule diff + impact → Approve / Reject.
- [ ] Footer disclaimer: "Illustrative; synthetic data; not a shop-floor control system. AI proposes; a qualified planner approves."
- **Acceptance:** the three core flows work end-to-end in the browser.

### M8 — Polish, README, deploy *(1 day)*
- [ ] `README.md`: what/why, one-command run, screenshots/GIF, links to live demo + `DECISIONS.md` + whiteboard video; disclaimers prominent.
- [ ] Deploy with `ANTHROPIC_API_KEY` as a host secret; verify OR-Tools runs in prod; token cap + caching; smoke-test.
- [ ] Optional: `plant.hector-garza.com`.
- **Acceptance:** public URL works from a fresh browser; full flow runs deployed.

### M9 — Decision Record + Whiteboard session *(½ day)* — **do not skip; this is the differentiator**
- [ ] Complete `DECISIONS.md` (Situation/Decision/Risk/Change; rejected auto-commit/free-form/heuristic-only; accepted advisory-not-autonomous).
- [ ] Record the 5–8 min whiteboard session using `SPEC.md` §3.1 — center challenge #3 (why AI re-sequencing isn't reckless) and #6 (the change you recommended against).
- [ ] Embed/link the recording in README and on hector-garza.com.
- **Acceptance:** a stranger can read `DECISIONS.md` + watch the video and explain *why the AI can propose but never commit, and can never produce an infeasible plan.*

---

## Testing strategy
- **The scheduler's constraint enforcement is the crown jewel — test it hardest.** Certification, time-between-ops, capacity, infeasibility handling, AOG weighting.
- **Safety tests on the agent:** read tools are read-only; the only write path is a gated proposal; no direct-mutation tool exists.
- Mock the Anthropic API in unit tests; one live integration run for the ask/propose flows, kept out of CI.
- UI is demonstrated by the recording; don't chase UI coverage.

## Suggested repo layout
```
plantgpt/
├── README.md  SPEC.md  PLAN.md  DECISIONS.md
├── Dockerfile  docker-compose.yml  .env.example  pyproject.toml
├── app/
│   ├── main.py
│   ├── model/      models.py
│   ├── scheduler/  dispatch.py cpsat.py resolve.py
│   ├── query/      schema.py tools.py
│   ├── propose/    request.py impact.py
│   ├── agent/      ask.py propose.py prompts.py schemas.py
│   ├── data/       plant.py        # synthetic corpus (seeded)
│   └── views.py / templates/ (or web/)
└── tests/ test_model.py test_dispatch.py test_cpsat_constraints.py
          test_query_safety.py test_propose_gate.py
```

## Risk register (project execution)
| Risk | Mitigation |
|---|---|
| Scope is large (flagship) — risk of stalling | Ship in pillars: a working scheduler (M1–M4) is demoable on its own before the AI layer. |
| CP-SAT modeling is unfamiliar | Start flow-shop (fixed order) before full job-shop; lean on OR-Tools job-shop examples; keep the dispatching baseline as a fallback demo. |
| AI appears to control the floor | The solver enforces constraints; the AI only proposes; one approval gate; say it loudly in README + UI. |
| NL query mutates data | Typed read-only tools; no mutation tool exists; test it. |
| OR-Tools won't install/run in the deploy image | Verify in M0; pin versions; test in the container early. |
| Leaking `ANTHROPIC_API_KEY` / employer data | `.env` gitignored; host secrets; synthetic plant only. |
| Skipping M9 because the app "looks done" | M9 *is* the portfolio. The "AI proposes, never commits" story is the whole point. |

## Definition of Done
See `SPEC.md` §8 — all three deliverables (app, decision record, whiteboard recording) exist and are linked from the README; hard constraints are provably enforced (tested); the read-only query and propose→approve gate are tested; and an AI proposal can never produce or commit an infeasible schedule.
