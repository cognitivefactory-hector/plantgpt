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
