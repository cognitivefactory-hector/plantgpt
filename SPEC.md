# PlantGPT — Design Spec

**Project 5 of the Hector Garza portfolio.** Self-contained: everything needed to start this as its own repository is in this file and its companion `PLAN.md`. You do not need any other file from the `career/` folder to build this.

- **Owner:** Hector Garza · hectorg@smartxchain.com · hector-garza.com
- **Status:** Spec — ready to build
- **Suggested repo name:** `plantgpt`
- **Scale:** Flagship (~4 weeks) — this is two substantial systems wired together.
- **One-liner:** A conversational plant-operations brain with a real production scheduler underneath — ask it anything about the floor in plain English, and have it *propose* (never silently commit) a re-sequence that can't violate a hard constraint.

> **Illustrative tool on synthetic data.** Not connected to any real MES/ERP; not a shop-floor control system. No employer data, ever.

---

## 0. Read this first — what this project is *really* for

This is a job-search portfolio project, but it is **not** a "look, an LLM wrote SQL" demo, nor a "look, OR-Tools made a Gantt chart" demo. Both of those are individually easy now. The hireable signal is **how you put AI on top of a constrained operational system safely**: what you let the agent answer, what you let it *propose*, what it can never do, and the plant constraints you encoded that an AI-only engineer doesn't know exist.

So this project has **three deliverables of equal weight**:

1. **The working app** (hosted, clickable).
2. **A Decision Record** (`DECISIONS.md`) structured around the four questions below.
3. **A recorded whiteboard session** (5–8 min) where you defend the human-in-the-loop scheduling design against push-back.

A hiring manager who opens this repo should learn that you understand both the AI *and* the floor — and you designed for the floor.

---

## 1. The spine — four questions that make judgment portable

Every project in this portfolio is organized around these four questions. They appear here, in `DECISIONS.md`, and on the project's page at hector-garza.com. Fill them in *as you build*, while the reasoning is still alive.

> **1 · Situation** — What's happening, who's involved, the constraints, the facts you have and the facts that are *missing*. Context is where judgment begins.
>
> **2 · Decision** — The plausible paths, the one you took, and the credible options you *rejected*. Rejection shows what you refused to hand-wave.
>
> **3 · Risk** — What could go wrong, what you removed, and what you *consciously accepted*. Prevented losses count — name the bad outcome that didn't happen.
>
> **4 · Change** — What's different now: clearer, safer, faster. Connect the judgment to a real change in the work, not a diary entry.

### 1.1 First-draft answers for PlantGPT (defend/revise these on camera)

Your starting position. The whiteboard session (§3) exists to pressure-test these — and you've run real wet-process lines, so these constraints are *yours*.

- **Situation.** A plant runs many parts through shared wet-process lines (clean → etch → anodize → seal → inspect), each with hard constraints: tank/line capacity, **certified operators only** (NADCAP), **time-between-operations limits** (a part can't sit too long between steps), maintenance windows, and **AOG due dates** that jump the queue. Scheduling lives in spreadsheets and people's heads. When something slips, nobody can quickly answer *"what's late and why"* — and a hasty re-sequence to expedite one lot can quietly violate a constraint and scrap another. Facts you have: jobs, routings, resources, due dates. Facts you're missing: a single queryable model of the floor, and a safe way to test a schedule change before committing it.
- **Decision.** Build (A) a **constraint-based production scheduler** that produces a feasible schedule honoring routing precedence, resource capacity, worker shifts & certifications, time-between-operations, and due dates; and (B) a **conversational layer** that can **answer questions with auditable, read-only queries (it shows its query)** and **propose schedule changes that a human reviews and approves.** **You rejected** (1) a free-form chatbot answering from memory (unauditable), (2) letting the AI **auto-commit** schedule changes (reckless on a regulated floor), and (3) a purely heuristic scheduler with no feasibility guarantees — though you keep an explainable dispatching baseline alongside the solver.
- **Risk.** Two killers: (a) the NL layer silently runs a *wrong* query and a planner trusts a wrong "what's late" answer; (b) an AI-proposed re-sequence **violates a hard constraint** — an uncertified operator, an exceeded time-between-ops window — and creates a nonconformance or scraps a lot. Mitigations: queries are **read-only, constrained to a known schema, and shown with a confidence signal**; the **scheduler enforces hard constraints so no proposed change can ever violate one**; every change is a **human-approved proposal with an impact preview (what slips, what it costs)**; full audit trail. You **consciously accept** that the system is advisory and a touch slower than full automation — that's the right call on a floor that scraps real parts.
- **Change.** Anyone can ask the plant a question and get an *auditable* answer in seconds; a planner can test an expedite and see exactly what it costs *before* committing; AOG jobs get pulled forward **safely**, because re-sequencing can't break certifications or time-between-ops. Prevented loss: the wrong-data decision and the constraint-violating expedite that would have scrapped a lot.

---

## 2. Why this project (market fit)

- **Production scheduling is a named 2026 AI frontier:** 40%+ of manufacturers with a scheduling system are upgrading it with AI; the pattern everyone wants is **agent-driven workflows that adjust schedules and update work orders with a human keeping approval.** This project is exactly that, done responsibly.
- It combines three hot, separately-hireable skills: **agentic AI, operations research / scheduling, and data engineering** — in one coherent system.
- It's your **deepest domain flex.** The hard part of plant scheduling isn't the solver — it's the constraints (certs, time-between-ops, tank chemistry windows, AOG). You know them cold. An AI-only engineer will build a scheduler that produces an *infeasible* plan because they've never heard of a time-between-operations limit.
- Backs the resume's "data pipelines unifying production and quality data" and "AI-assisted tooling" claims with something a manager can drive.

---

## 3. The staged whiteboard session (recorded deliverable)

**Format.** 5–8 minutes. Screen + voice (Loom, or OBS → MP4), at the "whiteboard" (the Gantt board / a constraint diagram, or the running app), defending the design while an adversary pushes back. Use a strong ops/AI-literate friend, or answer the scripted challenges below on camera. Preserve the surviving reasoning in `DECISIONS.md`.

### 3.1 Adversarial challenge script (the push-back)

1. **"Scheduling is solved (OR-Tools) and NL-to-SQL is a demo. What's actually hard or novel here?"**
   *(Defend the integration: encoding real domain constraints — certs, time-between-ops — that make the difference between a feasible and an infeasible plan; and the safe human-in-the-loop AI layer on top.)*
2. **"Your NL query layer will run a wrong query and someone trusts it. Defend it."**
   *(Read-only, constrained schema, shows the query + confidence, verifiable — an unauditable answer is worse than no answer.)*
3. **"Letting AI re-sequence a regulated floor is reckless — one bad move scraps a lot. Why isn't this dangerous?"**
   *(The scheduler enforces hard constraints; the AI can only *propose*; the human approves; the impact preview shows what slips. The AI literally cannot generate an infeasible plan.)*
4. **"OR-Tools gives one 'optimal' schedule, but the planner has tacit knowledge it lacks. How do you handle that?"**
   *(Soft vs. hard constraints; planner overrides; the human stays the decider; the solver advises.)*
5. **"Synthetic data again — real routings change, machines break, data is dirty. Why believe it?"**
   *(Honest gap; re-solve on disruption; what you'd validate first on real data.)*
6. **"Show me a proposed change you recommended *against*."**
   *(The core thesis — the expedite you declined because the downstream slippage wasn't worth it; the trade-off you surfaced so a human could choose.)*

### 3.2 What the recording must show
- The **Situation → Decision → Risk → Change** arc (§1.1), in your words.
- A clear statement of **what the AI can never do** (commit a change; violate a hard constraint).
- At least one place you **revised** under push-back (or a crisp reason you held).
- A pointer to where the surviving reasoning lives (`DECISIONS.md`).

---

## 4. Product specification

Two pillars, one app.

### Pillar A — Production scheduler
4.A.1 **Part workflow (job-shop) scheduling.** Sequence each part through its **routing** (ordered operations) across shared resources, producing a feasible, time-phased schedule (a Gantt).
4.A.2 **Resource scheduling.** Lines/tanks have capacity (rack/load size) and can perform only certain operations; honor maintenance windows.
4.A.3 **Worker scheduling.** Assign **qualified** workers (certifications) to operations within their **shifts**; no uncertified assignment, ever.
4.A.4 **Hard constraints (must never be violated):** routing precedence; resource capacity; operator certification; **time-between-operations** max; maintenance windows; shift availability.
4.A.5 **Soft objectives (optimize):** minimize total tardiness / hit due dates (AOG weighted highest); maximize utilization; minimize changeovers/setups.
4.A.6 **Two solvers:** an explainable **dispatching baseline** (EDD / critical-ratio / SPT rules) and a **constraint solver** (OR-Tools CP-SAT) for a feasible, optimized plan. Show both so the value of the solver is visible — and so the baseline keeps it honest.
4.A.7 **Disruption re-solve.** "Machine down / hot job arrives" → re-solve and show the delta.

### Pillar B — Conversational layer (PlantGPT)
4.B.1 **Ask (read-only, auditable).** Plain-English questions over the plant + schedule model — *"which jobs will miss their due date?"*, *"what's the bottleneck tank tomorrow?"*, *"show anodize-line utilization this week."* The agent produces a **constrained query** (text-to-SQL over a known schema, or typed tool calls), **shows the query**, returns a chart + a narrative, and flags **confidence**. Read-only — it cannot mutate the schedule.
4.B.2 **Propose (write, but gated).** Plain-English intents — *"expedite lot 4471 for AOG"*, *"free up the seal tank Thursday afternoon."* The agent translates intent into a **scheduler request** (a priority bump / added constraint), **re-solves**, and returns a **proposed schedule with an impact preview** (what slips, the tardiness delta). **Nothing is applied until the human approves.**
4.B.3 **Audit trail.** Every query (with its SQL) and every proposed/approved change is logged.

### 4.3 Screens
- **Schedule board** (default): Gantt by resource and by job; due-date / AOG flags; baseline-vs-solver toggle.
- **Ask** : the query box, the shown query, chart + narrative + confidence.
- **Propose** : intent → proposed schedule diff + impact → Approve / Reject.
- **About / Decision Record** (or link to hector-garza.com): the SDRC story + embedded whiteboard recording.

### 4.4 Explicit non-goals (YAGNI)
- No real MES/ERP/PLC integration; synthetic plant only.
- **The AI never auto-commits a schedule change.** By design.
- **The AI cannot produce an infeasible schedule** — all changes go through the constraint-enforcing scheduler, never raw LLM output.
- No real-time second-by-second floor control; planning-horizon scheduling (shifts/days) is the scope.
- No accounts/multi-tenant; one planner session.
- No NL *write* to arbitrary tables — the agent's only write path is "propose a scheduler request," never direct SQL mutation.

---

## 5. Synthetic data (no employer IP — ever)

A small, obviously-fictional plant model. **No TAT/MSI routings, parts, capacities, or names.**

- **Resources:** 4–6 lines/tanks (e.g., Clean, Etch, Anodize, Seal, Inspect) with capacity and a maintenance window each.
- **Operations & routings:** 3–5 part types, each with an ordered routing across resources, per-step process & dwell times, and a **time-between-operations** limit on at least one transition.
- **Workers:** 4–6 with shifts and **certifications** (e.g., only some are anodize-certified).
- **Jobs:** ~15–25 jobs with quantities, due dates, and **1–2 AOG hot jobs**.
- Include a deliberately **tight scenario** where an obvious expedite *looks* free but actually slips two other jobs — the trade you'll surface.
- Fixed seed; clearly synthetic numbers.

> Authoring a realistic routing with a time-between-ops limit and cert constraints is itself a domain-expertise display — note it in `DECISIONS.md`.

---

## 6. Architecture & stack

Matches the owner's stack (Django · Postgres · Docker) with OR-Tools for scheduling and Claude for the conversational layer.

```
┌───────────────────────────────────────────────────────────────┐
│  Browser — Schedule board / Ask / Propose                        │
│   • Plotly Gantt (resource & job views), utilization charts       │
│   • Ask: query box → shown query + chart + narrative + confidence │
│   • Propose: intent → schedule diff + impact → Approve/Reject      │
└───────────────▲──────────────────────────────┬───────────────────┘
                │ JSON                           │
┌───────────────┴──────────────────────────────▼───────────────────┐
│  Backend — Django + Postgres                                       │
│   • model/      Job, Operation, Routing, Resource, Worker, Cert,   │
│                 Shift, Schedule, AuditEvent                         │
│   • scheduler/  dispatching baseline + OR-Tools CP-SAT solver       │
│                 (hard-constraint enforcement lives HERE)            │
│   • query/      NL → constrained read-only query (shows SQL)        │
│   • propose/    NL intent → scheduler request → re-solve → diff      │
│   • agent/      Claude tool-use: ask-tools (read) + propose-tool     │
│   • data/       synthetic plant corpus (seeded)                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Scheduler:** **Google OR-Tools CP-SAT** is the right tool for job-shop/flow-shop scheduling with resource and precedence constraints; model operations as interval variables with no-overlap per resource, precedence + time-between-ops as linear constraints, and a weighted-tardiness objective. The **dispatching baseline** (EDD / critical ratio) is the explainable foil.

**Claude integration (decide details at build, then record them):**
- Current frontier model — **`claude-opus-4-8`** or **`claude-sonnet-4-6`** (record cost/quality reasoning).
- **Tool use** with two clearly separated tool sets: **read tools** (run a constrained query, get schedule) and a **single propose tool** (submit a scheduler request) — there is **no tool that mutates the schedule directly.**
- **Structured output** for the query (the SQL/typed query it intends to run, surfaced to the user) and for proposals.
- **Prompt caching** for the system prompt + schema description.
- When building the Claude layer, follow Anthropic SDK best practices; in Claude Code, invoke the `claude-api` skill.

**Libraries:** `ortools`, Django, `psycopg`, `pandas`, `plotly`, `anthropic`.

---

## 7. Scheduling & agent substance (get it right — you'll be asked)

- **CP-SAT model:** each operation = an interval (start, duration, end); `NoOverlap` per resource (respecting capacity); precedence (`op[i+1].start >= op[i].end`); **time-between-ops** (`op[i+1].start <= op[i].end + maxGap`); worker assignment booleans constrained to certified+on-shift workers; objective = minimize Σ weight·tardiness (AOG weight high).
- **Feasibility guarantee:** the solver returns either a feasible schedule or "infeasible" — **the UI/agent never present a hand-built or LLM-built schedule as feasible.** This is the safety core.
- **Dispatching baseline:** EDD (earliest due date), Critical Ratio, SPT — fast, explainable, and a sanity check on the solver's value.
- **NL query (read-only):** constrain the agent to a documented schema; it emits the query it will run; execute read-only; render result + narrative + confidence; never mutate.
- **NL propose (gated write):** the only write path is a *scheduler request* (e.g., `priority(job=4471)=AOG` or `block(resource=Seal, Thu PM)`). The scheduler re-solves under the new request; if infeasible or worse, that's shown. The human approves before anything persists.
- **Audit trail:** persist each query (+SQL) and each proposal (requested change, resulting diff, approver).

---

## 8. Definition of Done

Portfolio-ready when **all three** exist and are linked together:

- [ ] **App** deployed at a public URL: see a feasible Gantt for the synthetic plant (baseline vs. CP-SAT); **Ask** a question and see the query + chart + answer; **Propose** an expedite and see the impact preview, then approve it and watch the schedule update — and see an example where the proposal makes things worse and you reject it.
- [ ] **Hard constraints provably enforced:** no schedule (including AI-proposed) ever violates certification or time-between-ops — demonstrated and tested.
- [ ] **`README.md`** — what/why, one-command local run (Docker), screenshots/GIF, links to live demo + `DECISIONS.md` + whiteboard video, synthetic-data + not-a-control-system disclaimers.
- [ ] **`DECISIONS.md`** — the §1 template completed, including the rejected auto-commit/free-form options and the accepted advisory-not-autonomous trade.
- [ ] **Whiteboard recording** (5–8 min) linked from README and on hector-garza.com, including the recommended-against change.
- [ ] Tests pass for the scheduler constraints, infeasibility handling, read-only query safety, and the propose→approve gate (see `PLAN.md`).

---

## 9. Hosting / deployment
- Containerize (`Dockerfile` + `docker-compose.yml` with Postgres). OR-Tools installs via pip wheels — verify the base image has them.
- Host on Render / Railway / Fly.io / VPS; `ANTHROPIC_API_KEY` as a host secret (**never committed**).
- Optional subdomain: `plant.hector-garza.com`; link from the resume's future "Selected Work" section.
- Cost guard: the agent runs on demand (button), prompt-cached, token-capped.

---

## 10. Repo bootstrap (how to start this as its own repo)

```bash
mkdir plantgpt && cd plantgpt
cp /path/to/05-plantgpt/SPEC.md .
cp /path/to/05-plantgpt/PLAN.md .
# seed: README.md, DECISIONS.md (paste template below), .gitignore (python + .env!), LICENSE (MIT)

git init && git add -A && git commit -m "chore: scaffold plantgpt (spec + plan)"
git branch -M main
gh repo create cognitivefactory-hector/plantgpt --public --source=. --remote=origin --push
```

> PUBLIC repo. **Never commit `ANTHROPIC_API_KEY`** (`.env` gitignored). Synthetic plant only.

### `DECISIONS.md` starter (paste into the new repo)

```markdown
# Decision Record — PlantGPT

## Situation
<shared wet-process lines; hard constraints (certs, time-between-ops, AOG); no queryable model; unsafe ad-hoc re-sequencing>

## Decision
<constraint-based scheduler + auditable read-only NL query + gated NL proposals; auto-commit you REJECTED; free-form chatbot you REJECTED; heuristic-only scheduler you REJECTED>

## Risk
<wrong silent query; constraint-violating expedite; read-only+shown-query+confidence; solver-enforced hard constraints; human-approved proposals w/ impact preview; the advisory-not-autonomous trade you ACCEPTED>

## Change
<auditable answers in seconds; test an expedite before committing; AOG pulled forward safely; the prevented scrap>

## Whiteboard session
- Recording: <link>
- The change I recommended against (and why): <…>
- What the AI can never do: <…>
- What I revised under push-back / held the line on: <…>
```

---

## 11. Open questions to resolve in the plan
- CP-SAT scope first pass: flow-shop (fixed line order) is simpler than full job-shop — start there, note it.
- NL query mechanism: text-to-SQL over a read-only view vs. a set of typed query tools (typed tools are safer/easier to constrain — lean that way).
- Plant size for the demo (jobs/resources) that solves fast enough to feel live.
- Django templates/HTMX vs. a small JS front end for the Gantt + review UI.
