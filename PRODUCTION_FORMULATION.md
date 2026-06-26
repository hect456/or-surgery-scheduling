# Production Formulation — Interval-Based Constraint Programming (CP-SAT)

This document extends [FORMULATION.md](FORMULATION.md). It is not a different problem —
every set, parameter and objective term below is the baseline's, carried over unchanged.
What changes is the **time representation**: the baseline reasons at day+room
granularity (a capacity bucket); this model gives every case an exact start time and
reasons about literal overlap. Read this alongside
`src/solvers/cp_sat_interval_solver.py`, which mirrors it constraint-for-constraint.

## 1. Why Interval-Based CP-SAT for Production

The baseline's room-capacity constraint (C7) is `sum(durations) <= room-minutes`. That's
an aggregate relaxation: it can tell you the day's cases *fit*, but not that they don't
*collide* in time, and it cannot express "this shared device is in use right now" — only
"N cases needing it happened to land on the same day." Interval variables
(`start, size, end`, optionally present) plus `AddNoOverlap` / `AddCumulative` are the
standard tool for exactly this class of problem — disjunctive / resource-constrained
project scheduling (RCPSP), the same family job-shop scheduling belongs to. Three
concrete reasons this is the right production upgrade, not just a different encoding:

1. **No big-M.** A time-indexed MILP encoding of "case A and case B don't overlap"
   needs a disjunctive big-M constraint per pair, which is both numerically fragile and
   grows quadratically in the case count. CP-SAT's `NoOverlap` expresses the same fact
   natively, without that blow-up.
2. **Exact resource concurrency, not a daily headcount.** `AddCumulative` checks how many
   intervals genuinely overlap *in time* — recovering schedules the baseline's
   day-bucket equipment cap (C10) needlessly forbids (see RESULTS.md for the measured
   effect: a shared device that's free for half the day can serve a second case in the
   other half, which a same-day headcount cap cannot see).
3. **CP-SAT's search is purpose-built for this.** OR-Tools' CP-SAT (lazy-clause
   generation over a SAT core) is consistently the strongest open-source solver on
   RCPSP/job-shop-family benchmarks — exactly this problem's combinatorial shape — which
   is the practical reason to reach for it once the model needs real timing, rather than
   re-deriving a disjunctive MILP by hand.

Hexaly (local search/hybrid) is the third point of the trade-off triangle this repo
demonstrates — see `src/solvers/hexaly_solver.py` and RESULTS.md for where each of the
three (exact MILP, exact CP-SAT, local search) wins.

## 2. Mapping From the Baseline

Same sets ($C, D, R, H, E$), same parameters, same objective philosophy. Only the
variables and three constraint rows change:

| Baseline (MILP, FORMULATION.md) | Production (this file) |
|---|---|
| $x_{cdr} \in \{0,1\}$ | $\text{pr}_{cdr}\in\{0,1\}$ (presence) + $\text{start}_{cdr}, \text{end}_{cdr}$ |
| *(implicit, no timing)* | $\text{iv}_{cdr} = [\text{start}_{cdr},\, \text{start}_{cdr}+t_c^{\text{tot}})$, present iff $\text{pr}_{cdr}=1$ |
| C7 room capacity: $\sum t_c^{\text{tot}} x_{cdr} \le k_{dr}$ | `AddNoOverlap` over $\{\text{iv}_{cdr}\}$ per $(d,r)$ — exact, not aggregate |
| C8 surgeon daily sum $\le k_{hd}$ | `AddNoOverlap` over $\{\text{iv}_{cdr}\}$ per $(h,d)$ **plus** the same linear sum bound (kept, for the workload cap — NoOverlap alone doesn't bound total hours) |
| C9 surgeon weekly sum $\le k_h$ | unchanged — still a linear sum bound |
| C10 equipment day-count $\le \kappa_{ed}$ | `AddCumulative` over real start/end times, capacity $\kappa_{ed}$ — exact concurrency |
| *(excluded from baseline — §8)* | `AddCumulative` over downstream recovery/ICU beds, day-granularity (new — §4 below) |
| Objective (3-term tardiness + penalty) | identical formula, evaluated over $\text{pr}_{cdr}$ instead of $x_{cdr}$ |

Everything else — priority-4 lock-in (C2), schedule-or-penalise (C3), room-service
roster (C4), ambulatory/pediatric-block eligibility (C5-C6), one-case-per-patient (C1) —
is the *same* constraint, just written over `pr` instead of `x`.

## 3. Variables

For every $(c,d,r)$ that survives the same eligibility pre-filter as the baseline
(room-service roster, ambulatory-only, pediatric block, surgeon availability):

$$
\text{pr}_{cdr} \in \{0,1\}, \quad
\text{start}_{cdr} \in [0, k_{dr}], \quad
\text{end}_{cdr} \in [0, k_{dr}]
$$
$$
\text{iv}_{cdr} = \texttt{NewOptionalIntervalVar}(\text{start}_{cdr},\, t_c^{\text{tot}},\, \text{end}_{cdr},\, \text{pr}_{cdr})
$$

For non-priority-4 cases, $u_c \in \{0,1\}$ (unscheduled indicator) with
$\sum_{d,r} \text{pr}_{cdr} + u_c = 1$ — the direct analogue of C3.

## 4. New constraint: downstream recovery/ICU beds

Excluded from the baseline (§8 of FORMULATION.md) because it needs day-granularity
multi-day occupancy, which the day-bucket model has no clean way to express. Once
intervals exist, it's a small, natural addition — which is itself the argument for why
this is the right place to add it, not the baseline:

For each case $c$ that needs a recovery bed of type $\rho(c)$ for $\text{los}_c$ days,
let $\text{dayof}_c \in \{0,\dots,|D|-1\}$ be channeled to whichever $(d,r)$ slot is
actually chosen:
$$
\text{dayof}_c = d_{\text{idx}} \quad \text{whenever } \text{pr}_{cdr}=1, \text{ for each candidate } (d,r)
$$
$$
\text{bed}_c = \texttt{NewOptionalIntervalVar}(\text{dayof}_c,\, \text{los}_c,\, \text{dayof}_c+\text{los}_c,\, \text{is\_scheduled}_c)
$$
$$
\texttt{AddCumulative}\big(\{\text{bed}_c : \rho(c)=\rho\},\ \text{demands}=1,\ \text{capacity}=\beta_\rho\big) \quad \forall \rho
$$

where $\beta_\rho$ is the (constant-per-week, in our instances) bed count for pool
$\rho$. This is exactly the kind of "downstream constraint" the case prompt flags as
optional — included here, deliberately, to show the scaling path rather than leave it
purely hypothetical.

## 5. Constraints carried over unchanged (same formula, `pr` instead of `x`)

- **C1** one scheduled occurrence per patient per week
- **C2** priority-4 cases: $\sum_r \text{pr}_{c,1,r} = 1$ (and all other slots forced to 0)
- **C3** schedule-or-penalise (see §3 above)
- **C4-C6** room-service roster, ambulatory-only, pediatric block — enforced by the same
  eligibility pre-filter that builds the candidate $(c,d,r)$ set in the first place
- **C9** surgeon weekly sum $\le k_h$

## 6. Objective

Identical to FORMULATION.md §6.2-6.3, with $x_{cdr} \to \text{pr}_{cdr}$ and
$z_c \to u_c$. CP-SAT requires integer objective coefficients, so each coefficient is
rounded to the nearest integer at model-build time (negligible at this objective's
scale — see `src/solvers/cp_sat_interval_solver.py`).

## 7. What this buys you operationally

Besides the resource-fidelity gains in §1, the solver now reports **exact clock times**
per case (`start_min`/`end_min` on every `Assignment`) — a schedule a charge nurse can
actually post, not just "Tuesday, Room 3." `reporter.py` prints these and runs an exact
no-overlap sweep-line check as part of its consistency report whenever a solver provides
them, which is itself a useful regression check that the production model is honoring
its own NoOverlap constraints.

## 8. References

See FORMULATION.md §12 for the modeling-evidence citations. CP-SAT specific:

- Perron, L., & Furnon, V. *OR-Tools* (Google). CP-SAT solver documentation —
  https://developers.google.com/optimization/cp
- Cardoen, B., Demeulemeester, E., & Beliën, J. (2010). Operating room planning and
  scheduling: A literature review. *EJOR*, 201(3), 921-932. (Classifies this problem
  family; motivates the advance-scheduling vs. exact-timing distinction this document is
  built around.)
