# Scheduler — the safety core (PLAN.md M2–M4).
#   dispatch.py  EDD / critical-ratio / SPT explainable baseline (M2)
#   cpsat.py     OR-Tools CP-SAT solver; hard-constraint enforcement lives HERE (M3)
#   resolve.py   disruption re-solve + diff (M4)
# No schedule (including AI-proposed) is ever presented as feasible unless it came
# from this package. See CLAUDE.md "safety invariants".
