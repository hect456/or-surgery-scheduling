# Results — What the Demo Produces, and Why It Validates §3's Choice

This is the "a few words explaining the results" deliverable. Full formulation in
[FORMULATION.md](FORMULATION.md) / [FORMULATION_CP.md](FORMULATION_CP.md). Reproducible
with `python main.py --instance {demo,medium} --benchmark` (CBC/Gurobi/Hexaly are run
too, for the comparison below — none of them is the primary deliverable; see
FORMULATION.md §12).

**A note on these numbers vs. an earlier draft of this document:** the objective
formula had two bugs (a priority/penalty double-counting and monotonicity inversion,
and a surgeon-interval sizing issue) found and fixed during review — see
[FORMULATION_CP.md §6](FORMULATION_CP.md) for the full derivation with worked numeric
examples. Every number below is from the corrected code; objective values are **not**
comparable to anything computed before the fix (the formula's scale changed).

Environment: Windows, Python 3.12, `ortools` 9.15 (CBC bundled, CP-SAT), `gurobipy`
12.0.2 available but optional. Hexaly: not installed/licensed here — falls back to CBC
automatically, see [hexaly_solver.py](src/solvers/hexaly_solver.py). A note before the
numbers: Gurobi's and CP-SAT's `Optimal` status both mean *"proven within the solver's
configured relative gap"*, not literally a zero gap — the gap is always computed and
shown below, never assumed.

## Demo instance — 20 cases, 5 rooms, 6 surgeons

`python main.py --instance demo --benchmark --gap 0.0001` (tight gap, to make the
zero-gap verification airtight at this size):

| Solver | Status | Objective | Gap | Scheduled | Time |
|---|---|---|---|---|---|
| Greedy | Feasible | 163.0 | — | 20/20 | 0.000s |
| **CP-SAT (primary model)** | **Optimal** | **155.0** | 0.00% | 20/20 | ~0.1s |
| OR-Tools/CBC (alternative MILP) | Optimal | 157.0 | 0.00% | 20/20 | ~0.03s |
| Gurobi (alternative MILP) | Optimal | 157.0 | 0.00% | 20/20 | ~0.06s |
| Hexaly (→ CBC fallback, no license) | Optimal | 157.0 | 0.00% | 20/20 | ~0.02s |

(These specific values are unchanged by the §6 bug fixes — this particular instance's
optimal *value* happens not to move, even though, as noted below, the exact optimal
*schedule* CP-SAT returns can vary run to run among ties.)

Every solver closes to a *verified* zero gap in well under a second at this size, so
this instance is mainly a correctness check. One thing is worth noting, because it's
the whole argument for the primary model, made concrete:

**CP-SAT finds a better schedule (155 vs. 157), not because it searches harder, but
because it models a shared resource correctly.** The demo has one shared C-arm with
capacity 1. The MILP's C10 counts *cases per day* needing it ("capacity 1" reads as "at
most one C-arm case per day, anywhere"). CP-SAT's `AddCumulative` checks *literal time
overlap* instead. In the canonical run captured for `docs/img/demo_cp_sat.png`, CP-SAT's
optimal schedule places **three** different C-arm cases on Monday (sequentially, in the
same room, never exceeding 1 concurrent use) — a placement the MILP's day-count cap
forbids outright (the MILP's own run, `docs/img/demo_baseline_milp.png`, spreads its
four C-arm cases across four *different* days, one per day, exactly as its C10 forces).

**Honesty about reproducibility:** which *exact* arrangement CP-SAT returns (which day,
which room, sequential vs. across two rooms) can vary run to run among tied-optimal
solutions — CP-SAT's parallel portfolio doesn't guarantee the same tie-break twice. What
does **not** vary is the structural fact this demonstrates: any CP-SAT-optimal schedule
that puts 2+ C-arm cases on the same day is something the MILP's day-count cap cannot
express, by construction — the conclusion doesn't depend on which particular tied
optimum was returned. This is FORMULATION.md §3's argument, observed directly rather
than asserted.

## Validating the choice at scale — 200 cases, 12 rooms, 17 surgeons

### Step 1: the *true* optimum of the alternative MILP

`python main.py --instance medium --solver milp-gurobi --time-limit 300 --gap 0.0001`:

| | Status | Objective | Gap | Scheduled | Time |
|---|---|---|---|---|---|
| Gurobi (near-zero gap) | **Optimal** | **74,305.0** | 0.01% | 130/200 | ~14s |

This is the **proven, true optimum of the alternative MILP** on this instance — not a
time-limited approximation. Everything below is measured against this number.

### Step 2: a realistic 30-minute production budget, 1% gap target

`python main.py --instance medium --solver {milp-cbc,cp-sat} --time-limit 1800 --gap
0.01` (run independently per backend, in parallel, to avoid one competing with another
for CPU):

| Solver | Status | Objective | Own Gap | vs. True MILP Optimum | Scheduled | Time |
|---|---|---|---|---|---|---|
| OR-Tools/CBC | Feasible | 74,383.0 | 0.13% | **+0.10%** | 130/200 | 1800.6s |
| **CP-SAT/Interval** | Feasible | **66,471.0** | 1.31% | **−10.54%** | **133/200** | 1801.2s |

Reading this correctly:

- **CBC essentially reaches the alternative MILP's true optimum** (74,383 vs. 74,305 —
  0.10% off) but needs the full 30 minutes to get there; Gurobi proves the same
  formulation's optimum in ~14 seconds — over **100x faster** to a verified answer, on
  identical math, only the backend differs.
- **CP-SAT does not just fail to beat the MILP's bound — it finds a legitimately
  better, differently-structured schedule that is 10.54% *below* the MILP's true
  optimum**, while scheduling **3 more cases** (133 vs. 130). This is the same
  mechanism as the demo instance's C-arm story, at production scale: the MILP's
  day-bucket equipment cap (C10) and its room/surgeon aggregate sums (C7/C8) structurally
  forbid schedules CP-SAT's exact `NoOverlap`/`Cumulative` constraints correctly allow.
  CP-SAT's own reported gap (1.31%) is relative to *its own* feasible region's bound —
  not fully closed in 30 minutes either, meaning **even better schedules than 66,471
  likely exist**.
- **This is the concrete answer to "how would this scale to a real environment":** at a
  30-minute batch-planning budget (a realistic cadence for a weekly OR plan), the
  primary model is not merely "fast enough" — it is finding meaningfully better,
  legitimately different schedules than the comparison MILP's mathematical optimum,
  because it is solving a more faithful version of the actual resource-sharing problem,
  now backed by a corrected, audited objective formula (FORMULATION_CP.md §6).

### Why the gap comparison (1.31% vs. 0.13%) doesn't favor CBC

A smaller feasible region is *easier* to fully close — the same way it's easier to prove
there's no number larger than 5 in $\{1,\ldots,5\}$ than in $\{1,\ldots,100\}$. CBC's
tighter own-gap is a property of how constrained its search space already is, not
evidence its answer is better; CP-SAT's looser own-gap reflects a genuinely larger
search space it hasn't fully exhausted in 30 minutes, not search inefficiency.

## Optional, license-gated extension: Hexaly

[`hexaly_solver.py`](src/solvers/hexaly_solver.py) is a real (non-stub) integration
against Hexaly's local-search API, written as a set-partition formulation of the same
problem. No academic license was available while building this, so every run above
falls back to the alternative MILP automatically, with setup instructions printed at
runtime. It is included as a pointed-at extension path for very large instances or
real-time re-optimization (FORMULATION.md §14) — not benchmarked here, and not part of
this deliverable's core claim.

## Visual schedule

`python main.py --instance <name> --solver cp-sat --plot out.png`
(`src/utils/visualizer.py`). Per the case prompt, "a plain terminal output or a simple
image of the schedule is plenty" — three are included in `docs/img/`, all regenerated
against the corrected (post-§6-fix) code:

- `demo_baseline_milp.png` — the alternative MILP's schedule: no exact clock times (it
  doesn't model any, FORMULATION.md Appendix A), and its four C-arm cases spread one
  per day across four different days, exactly as its day-count cap forces.
- `demo_cp_sat.png` — the primary model's schedule, with real start/end times; three
  C-arm cases land on Monday alone, sequentially — the placement the MILP's cap
  forbids outright (see the demo-instance discussion above for the honest caveat about
  run-to-run tie variance in exactly *which* arrangement appears).
- `medium_cp_sat.png` — the 200-case instance, exact per-case timing across 12 rooms.

## Testing against real and literature data

`literature_chln_instance()` is calibrated, not just inspired, to published CHLN
waiting-list statistics (Marques & Captivo, 2015) — see FORMULATION.md §13 for the exact
figures and an honest discussion of sampling variance, and for pointers to two public,
real hospital OR-log datasets (Akbarzadeh & Maenhout, 2023) that are a structural fit
for a follow-up pilot beyond this demo's scope.
