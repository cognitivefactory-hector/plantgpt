# Whiteboard Drill — PlantGPT (design-stage, M2-onward)

> Rehearsal for the recorded whiteboard session. **The push** is me playing tough reviewer; **Defense** is the position that survives; **⚠ Your move** is what only you can answer once you've built/measured it. Fold the survivors into `DECISIONS.md`, then record.
> Scope: you're past M1 (domain model), so this drills the decisions in **M2–M6** — the scheduler core, CP-SAT constraint enforcement, the read-only query layer, and the gated propose loop. Re-run a second drill after **M6** with a real "expedite that backfired" example.

## Q0 (the killer) — "If the CP-SAT solver guarantees feasibility, what is the LLM even adding?"
**The push:** The solver does the hard work. The LLM is decoration.
**Defense (survives):** Exactly — and that's the point. The solver owns *correctness*; the LLM owns *access*. Today a planner who wants "what's late and why" or "expedite 4471 for AOG" needs SQL skills or a scheduling engineer. The LLM turns intent into either an auditable read query or a **scheduler request the solver then validates** — it never decides feasibility. I deliberately made the LLM the thin, replaceable layer and the solver the trustworthy core. If that sounds like the LLM is doing little, good: in a regulated shop the *less* the language model decides, the better.

## Q1 — "Scheduling is solved (OR-Tools) and NL-to-SQL is a demo. What's novel?"
**The push:** You glued two tutorials together.
**Defense (survives):** The novelty isn't the solver or the parser — it's encoding the constraints that make a plant schedule *feasible*: operator **certifications**, **time-between-operations** limits, maintenance windows, AOG weighting. An AI-only engineer ships a scheduler that emits a beautiful, infeasible plan because they've never heard of a time-between-ops limit. The integration + the safe human-in-the-loop layer on top is the work.
**⚠ Your move:** Have one concrete constraint story ready (a real time-between-ops or cert rule from your experience) — that's the part nobody else can fake.

## Q2 — "Your NL query layer will run a wrong query and a planner trusts it."
**The push:** One bad join and someone makes a bad call.
**Defense (survives):** Reads are **constrained to typed query tools over a documented schema** (not free-form SQL), the agent **surfaces the query it ran** plus a confidence signal, and it's **read-only** — it physically cannot mutate the schedule. An unauditable answer is worse than no answer, so I made every answer traceable.
**⚠ Your move:** Decide typed-tools vs. text-to-SQL-over-a-view and record why (typed tools are the safer default).

## Q3 — "Letting AI re-sequence a regulated floor is reckless — one bad move scraps a lot."
**The push:** This is dangerous automation.
**Defense (survives):** The AI can only *propose*. A proposal is a scheduler **request** (priority bump / resource block) that the CP-SAT solver re-solves under — so a proposed change **cannot violate a hard constraint** (the solver would return infeasible instead). Every change shows an **impact preview** (what slips) and waits for human approval. The AI cannot generate an infeasible plan and cannot commit one. That's the opposite of reckless.

## Q4 — "OR-Tools gives one 'optimal' schedule, but the planner has tacit knowledge it lacks."
**The push:** Your solver will overrule the human who actually knows the floor.
**Defense (survives):** Hard constraints are in the solver; *soft* preferences and tacit knowledge stay with the planner, who can override and re-solve. The solver advises and enforces safety; it doesn't dictate. The propose-approve loop exists precisely so the human's judgment is the last word.
**⚠ Your move:** Decide which constraints are hard vs. soft — and be ready to defend a case where you'd override the "optimal" plan.

## Q5 — "Synthetic plant data again — real routings change, machines break, data is dirty."
**The push:** Why believe any of it?
**Defense (survives):** The synthetic plant proves the *mechanism* (feasible scheduling + safe AI proposals), not field-readiness. The disruption re-solve already models "machine down / hot job." First real-data validation: confirm the constraint model matches actual routings and certs before trusting a single proposal.
**⚠ Your move:** Name what would break first on real data (dirty timestamps for time-between-ops?) from your experience.

## Q6 — "Show me a proposed change you recommended *against*."
**The push:** Anyone can show a successful expedite.
**Defense (survives):** The strongest output is the expedite the tool let me *decline*: the AOG pull-forward that looked free but the impact preview showed slipped two other due dates past their limit — so I didn't approve it, or I approved it knowing the cost. The judgment is surfacing the tradeoff so a human chooses with eyes open.
**⚠ Your move:** Build the "tight scenario" from the spec (§5) so you have a real declined-expedite to walk through. This is the money moment of the recording.

## Verdict — SDRC after the drill
- **Holds:** the whole propose-not-commit / solver-enforces-feasibility thesis; the constraint-knowledge edge.
- **Sharpen:** lead the recording with **Q0** (it reframes "the LLM does little" from a weakness into the design); lock hard-vs-soft constraints (Q4); build the declined-expedite scenario (Q6).
- **Land this line in the room:** *"The solver owns correctness; the language model owns access; the human owns the decision — and the AI can't produce an infeasible plan even if it tries."*
