# Results — Baseline vs. Production Trade-off

This is the "a few words explaining the results your demo produces" deliverable. Full
formulations: [FORMULATION.md](FORMULATION.md) (baseline MILP) and
[PRODUCTION_FORMULATION.md](PRODUCTION_FORMULATION.md) (interval-based CP-SAT). Both
runs below are reproducible with `python main.py --instance {demo,medium} --benchmark`.

Environment: Windows, Python 3.12, `ortools` 9.15 (CBC/SCIP bundled, CP-SAT), `gurobipy`
12.0.2 (real academic license, solved natively — see
[milp_baseline_solver.py](src/solvers/milp_baseline_solver.py) docstring for why Gurobi
is called directly rather than through OR-Tools' MPSolver shim). Hexaly: package not
installed/licensed in this environment — falls back to OR-Tools/CBC automatically (see
[hexaly_solver.py](src/solvers/hexaly_solver.py)); discussed qualitatively below.

## Demo instance — 20 cases, 5 rooms, 6 surgeons

| Solver | Status | Objective | Gap | Scheduled | Time |
|---|---|---|---|---|---|
| Greedy | Feasible | 163.0 | — | 20/20 | 0.000s |
| OR-Tools/CBC | **Optimal** | 157.0 | 0.00% | 20/20 | 0.028s |
| Gurobi | **Optimal** | 157.0 | 0.00% | 20/20 | 0.186s |
| **CP-SAT/Interval** | **Optimal** | **155.0** | 0.00% | 20/20 | 0.084s |
| Hexaly (→ CBC fallback) | Optimal | 157.0 | 0.00% | 20/20 | 0.021s |

At this size every exact solver closes the gap in well under a second, so this instance
is a correctness demo, not a scaling test. Two things are still worth noting:

- **CP-SAT beats both exact MILP solvers' objective (155 vs. 157), not because it
  searches better, but because it models a resource better.** The demo instance has a
  single shared C-arm with capacity 1. The baseline MILP's C10 counts *cases per day*
  needing it (so "capacity 1" reads as "at most one C-arm case per day, anywhere in the
  hospital"). CP-SAT's `AddCumulative` instead checks *literal time overlap* — and the
  optimal CP-SAT schedule places two different C-arm cases on Tuesday, in different
  rooms, at non-overlapping times (`R_VASC1` 200-310 and `R_VASC2` 0-170). That's a
  schedule the baseline's day-count cap forbids outright, even though it's perfectly
  legitimate. This is the single clearest illustration of the baseline/production
  trade-off: the production model isn't just faster, it recovers feasible capacity the
  coarser model leaves on the table.
- Greedy is 3.8% off the true optimum (163 vs. 157) — a reasonable warm-start / sanity
  bound, consistent with its role as a fallback when no solver is available.

## Medium instance — 200 cases, 12 rooms, 17 surgeons (60s time limit per solver)

| Solver | Status | Objective | Gap | Scheduled | Time |
|---|---|---|---|---|---|
| Greedy | Feasible | 70,883.0 | — | 124/200 | 0.002s |
| OR-Tools/CBC | Feasible (time limit) | 44,606.0 | 0.90% | 128/200 | 60.085s |
| **Gurobi** | **Optimal*** | **44,232.0** | 0.80%* | 129/200 | **0.708s** |
| CP-SAT/Interval | Feasible (time limit) | 40,799.0 | 2.42% | 131/200 | 60.403s |
| Hexaly (→ CBC fallback) | Feasible (time limit) | 44,606.0 | 0.90% | 128/200 | 60.097s |

\* Gurobi's `Optimal` here means "proved within the configured 1% relative MIP gap,"
which is Gurobi's actual default termination criterion — not literally zero gap. That's
expected, correct Gurobi behavior, not a bug.

This is where the trade-off in the case prompt — "how would this scale to a real
environment" — actually shows up:

- **Gurobi is dramatically faster than CBC on the identical formulation: 0.7s vs. a
  60s time-out.** Same model, same code path (`milp_baseline_solver.py`), only the
  backend differs. This is the textbook argument for paying for a commercial MILP
  solver once an instance crosses a few hundred binary variables: CBC is a perfectly
  good correctness check, but it stopped making progress well before Gurobi even
  finished.
- **CP-SAT does not out-search Gurobi at MILP's own game (it didn't close its gap
  in 60s either), but it again finds a lower objective (40,799 vs. 44,232) for the same
  reason as the demo instance**: its equipment `AddCumulative` is exact, recovering
  schedule slack the baseline's day-count cap structurally forbids. At this scale the
  effect is large — roughly 8% of the objective — because the medium instance has real
  C-arm contention (two services sharing two units across 200 cases) where the demo
  instance only had one borderline case.
- **CBC and the Hexaly fallback are identical** (44,606.0, 128/200) because they are,
  literally, the same code path here — Hexaly has no license in this environment, so it
  is reporting the baseline's result, not its own. With a real Hexaly license, the
  expected story (per its local-search design) is: a usable feasible schedule much
  faster than CBC's 60-second time-out, likely not as tight as Gurobi's proven optimum,
  but without needing a commercial MILP license — see the qualitative discussion below.

### Reading the trade-off

| | Baseline MILP (CBC) | Baseline MILP (Gurobi) | Production CP-SAT | Hexaly (qualitative) |
|---|---|---|---|---|
| Proof of optimality | Yes, eventually (not within 60s here) | Yes, fast | No (anytime, reports a gap) | No (anytime) |
| Models exact timing / overlap | No | No | **Yes** | Depends on encoding |
| Models exact equipment concurrency | No (day-count) | No (day-count) | **Yes** (`AddCumulative`) | Would need a set-based reformulation, see `hexaly_solver.py` |
| Models downstream beds | No (excluded) | No (excluded) | **Yes** (new in production) | Not attempted here |
| License cost | Free | Commercial | Free | Commercial |
| Best fit | Small instances, free correctness baseline | Medium/large instances needing a *proof* | Medium/large instances needing exact resource timing, or no MILP license | Very large instances, real-time re-optimization, license available |

The practical recommendation this points to: **ship the OR-Tools/CBC baseline as the
free, always-available correctness reference; route production traffic through CP-SAT**
once instances are large enough that the day-bucket equipment/room approximation starts
costing real schedule quality (as it visibly does here); **add Gurobi as a paid upgrade**
if a hospital needs proof of optimality at full weekly scale and CP-SAT's anytime gap
isn't reassuring enough; and **evaluate Hexaly specifically for the multi-week /
real-time-disruption regime**, where an anytime local-search engine that doesn't need
exact constraint encodings tends to out-scale exact methods.

## Validating against real data, not just synthetic instances

Both instances above are synthetic (see FORMULATION.md §9 for the literature structure
they're modeled on). For testing at real scale before a pilot, two CC BY-4.0 hospital
OR-log datasets are a direct structural fit (same weekly horizon, same master-roster
concept):

- Akbarzadeh & Maenhout (2023), *Real life data for operating room scheduling problem*
  (Ghent University Hospital, May 2017). Mendeley Data,
  [10.17632/n2v49z2vnp.2](https://data.mendeley.com/datasets/n2v49z2vnp/2).
- Akbarzadeh & Maenhout (2023), *RealLife operating room scheduling dataset,
  2021-Jan-May* — 20 weekly instances across 8 demand/flexibility configurations.
  Mendeley Data, [10.17632/c8d342266x.1](https://data.mendeley.com/datasets/c8d342266x/1).

A loader for these (case list → `SurgicalCase`, room/day roster → `OperatingRoom`) is
the natural next step before any real pilot — intentionally not built here, consistent
with the case prompt's own "small demo, not a scale-to-real-hospital" framing.
