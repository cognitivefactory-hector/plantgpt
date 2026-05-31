# PlantGPT

A conversational plant-operations brain with a real **production scheduler** underneath — ask anything about the floor in plain English, and have it *propose* (never silently commit) a re-sequence that **can't violate a hard constraint**.

> **Status:** scaffolded (spec + plan in place). Build follows `PLAN.md` (M0 → M9). Flagship-scale (~4 weeks).
> **Illustrative tool on synthetic data — not connected to any real MES/ERP, not a shop-floor control system.**

Part of [hector-garza.com](https://hector-garza.com)'s portfolio. One of three equal deliverables: the app, a **Decision Record** ([`DECISIONS.md`](./DECISIONS.md)), and a recorded whiteboard session. A working demo no longer proves competence — the judgment behind it does. See [`SPEC.md`](./SPEC.md) §0.

## What it does
**Pillar A — Production scheduler:** sequences parts through their routings across shared lines/tanks and **qualified** workers, honoring hard constraints (routing precedence, capacity, **operator certification**, **time-between-operations** limits, maintenance windows, AOG due dates). Explainable dispatching baseline **+** an OR-Tools CP-SAT solver.

**Pillar B — Conversational layer:** **Ask** (read-only, auditable — it shows the query it runs) and **Propose** (NL intent → re-solve → impact preview → **human Approve/Reject**). The AI can propose but never commit, and can never produce an infeasible schedule.

## Tech stack
- **Backend:** Django + Postgres
- **Scheduler:** Google OR-Tools (CP-SAT) + dispatching baseline (EDD / critical-ratio)
- **AI:** Anthropic SDK (Claude) — tool use (separated read tools vs. one gated propose tool), structured outputs, prompt caching
- **Frontend:** Django templates + HTMX + Plotly (Gantt)
- **Packaging:** Docker · **Quality:** pytest + ruff + GitHub Actions CI

## Deployment
- **Live demo:** Dockerized Django app + Postgres on **Render**, fronted by **Cloudflare** (planned subdomain `plant.hector-garza.com`). Verify OR-Tools installs in the deploy image early (M0).
- Local run: one command via Docker (added in build step M0).

## Links (filled in as the build progresses)
- 🔗 Live demo: _TBD_
- 🧠 Decision record: [`DECISIONS.md`](./DECISIONS.md)
- 🎥 Whiteboard walkthrough: _TBD_

## Build
See [`PLAN.md`](./PLAN.md) — M0 (scaffold) → M9 (decision record + whiteboard). Ships in pillars: the scheduler (M1–M4) is demoable before the AI layer goes on.
