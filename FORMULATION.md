# Elective Surgery Scheduling — Baseline MILP Formulation

This document is the baseline (advance-scheduling, day-granularity) formulation. A
second, production-grade **interval-based Constraint Programming** model that extends
this one is in [PRODUCTION_FORMULATION.md](PRODUCTION_FORMULATION.md). Benchmark
numbers and the baseline-vs-production trade-off are in [RESULTS.md](RESULTS.md).

---

## 1. Problem Statement

A large hospital group needs to decide, for each elective surgical case on its waiting
list, **which procedure happens in which operating room, on which day, and with which
surgeon**, across a **one-week planning horizon** at a single hospital. The hospital
cannot run every waiting-list case this week — room-hours, surgeon-hours and a couple
of shared resources are scarce — so the model must also decide **which cases to leave
for a later week**, and do so in a way that respects clinical urgency.

This is the generic "advance scheduling" problem described in the case study: it
covers case selection, room assignment, and day assignment; it deliberately stops short
of within-day sequencing, staffing rosters, and downstream bed management in full
generality (see §7-8 for exactly what is included and why).

## 2. Why This Structure — Evidence, Not a Specific Country's Law

The priority-tier + maximum-wait-time + escalating-penalty mechanism used below is not
this model's own invention — it mirrors how several public health systems actually
prioritise elective waiting lists, which is good evidence that it is a reasonable
general-purpose mechanism rather than an ad hoc choice:

- **Portugal's SIGIC** (*Sistema Integrado de Gestão de Inscritos para Cirurgia*,
  Portaria n.º 45/2008) defines four clinical priority tiers with maximum wait times of
  270/60/15/3 days, and audited 2016 data showed 16% of ~7,400 waiting-list patients had
  already exceeded their tier's deadline by an average of 147 days (Marques & Captivo,
  2015) — i.e. breach penalties are not a cosmetic detail, they are the thing the
  planner is graded on.
- The **UK NHS Referral-to-Treatment (RTT)** framework and several **Canadian
  provincial wait-time benchmarks** use the same shape (tiered maximum waits, tracked
  breach rates) for the same reason: a single FIFO queue does not reflect clinical risk,
  and an unweighted "shortest job first" heuristic does not either.
- **Cardoen, Demeulemeester & Beliën (2010)**, the standard literature review for this
  problem family, classify "advance scheduling" (assigning cases to a day, without
  necessarily fixing the intra-day sequence) as a distinct, well-studied sub-problem —
  which is the scope this baseline targets.

Every numeric value attached to this mechanism (`max_wait_days`, `priority_multiplier`,
the penalty curve) is an **instance-level, overridable parameter** in the code
(`PlanningInstance`, `src/model/types.py`) — a hospital plugs in its own waiting-list
policy without touching the solver.

## 3. Assumptions and Simplifications

Stated explicitly, as requested — these are deliberate scoping choices, not oversights:

1. **Advance scheduling only.** We assign cases to a (day, room); we do not fix the
   order of cases within a room-day in the baseline (the interval-based production model
   in PRODUCTION_FORMULATION.md does fix exact start times — see that document for why
   that upgrade matters operationally).
2. **Deterministic durations.** Each case has one estimated operative duration (e.g. a
   historical median for that procedure type). Real durations are stochastic; we treat
   the deterministic case as the standard tractable approximation (Denton, Miller,
   Balasubramanian & Huschka, 2010, take the same approach and discuss the stochastic
   extension — see §10).
3. **Fixed turnover/cleaning time** is added to every case's room-occupation time as a
   constant buffer (`t_clean`), not modeled as a separate sequence-dependent activity.
4. **Surgeons are the binding staffing resource.** Nurses and anaesthetists are assumed
   to be allocated by a separate, pre-existing roster that tracks whatever room is
   staffed that day — a common real assumption when the surgeon's calendar, not the
   support staff's, is the actual bottleneck.
5. **One occurrence per patient per week.** A patient with multiple queued procedures
   gets at most one done this week — a conservative default; some services do
   legitimately co-operate same-day, multi-procedure cases, but that is service-specific
   and not assumed here.
6. **One shared resource family is modeled explicitly: equipment.** Real instances often
   list shared equipment (a C-arm/imaging unit, specialist instrument trays) as a
   bottleneck distinct from the room itself. We include it, but — consistent with
   "advance scheduling, no intra-day clock" — only as a **day-level aggregate cap** (see
   C10 below); see §8 and PRODUCTION_FORMULATION.md for the exact, time-based version.
7. **Downstream recovery/ICU beds are excluded from this baseline** (see §8) — multi-day
   bed occupancy genuinely needs a different time granularity than "which day", and we
   would rather model it correctly later than approximate it badly now. It is the
   single biggest planned upgrade in PRODUCTION_FORMULATION.md.
8. **One ad hoc institutional rule is included as a worked example, not a special
   case in the math:** a configurable "pediatric block" carve-out (a given service's
   rooms, on a given day, restricted to patients under some age). Hospitals accumulate
   rules like this constantly; the point of including one is to show it costs nothing
   structurally — it is one more eligibility predicate, not a new variable family.

## 4. Sets and Indices

| Symbol | Description |
|--------|-------------|
| $c \in C$ | Surgical cases (one entry per patient-procedure pair on the waiting list) |
| $d \in D$ | Planning days, $D = \{1,\dots,5\}$ (one work week) |
| $r \in R$ | Operating rooms |
| $h \in H$ | Surgeons |
| $e \in E$ | Shared equipment types (e.g. a mobile imaging unit) |
| $D_c \subseteq D$ | Days on which case $c$ may be scheduled ($D_c=\{1\}$ for priority-4 cases; $D_c = D$ otherwise) |

## 5. Parameters

| Symbol | Description |
|--------|-------------|
| $t_c^{\text{op}}$ | Operative duration of case $c$ (minutes) |
| $t_c^{\text{clean}}$ | Fixed room turnover/cleaning time after case $c$ (minutes; default 20) |
| $t_c^{\text{tot}} = t_c^{\text{op}} + t_c^{\text{clean}}$ | Total room-occupation time |
| $k_{dr}$ | Capacity of room $r$ on day $d$ (minutes open) |
| $k_{hd}$ | Surgeon $h$'s daily operative-time limit on day $d$ (minutes) |
| $k_h$ | Surgeon $h$'s weekly operative-time limit (minutes) |
| $a_{dr}^{s} \in \{0,1\}$ | 1 if room $r$ on day $d$ is rostered to service $s$ |
| $p_c \in \{1,2,3,4\}$ | Clinical priority of case $c$ (4 = must run this week, day 1) |
| $\text{wl}_c$ | Days case $c$ has already waited, as of the planning date |
| $\text{wl}^{\max}_p$ | Maximum clinically-acceptable wait for priority $p$ (default: 270/60/15/3 days) |
| $dd_c = \text{wl}^{\max}_{p_c} - \text{wl}_c$ | Days of slack to deadline (negative = already overdue) |
| $\mu_p$ | Priority-to-priority-1 penalty multiplier (default 1 / 4.5 / 18 / 90) |
| $w_c$ | Non-scheduling penalty weight for case $c$ (§6.3) |
| $\alpha > 1$ | Urgency multiplier applied to overdue cases' day coefficient (default 2.0) |
| $u_{ce} \in \{0,1\}$ | 1 if case $c$ requires equipment $e$ |
| $\kappa_{ed}$ | Day-level cap on the number of equipment-$e$ cases on day $d$ |
| $\text{ped}=(s^\dagger, d^\dagger, i^\dagger)$ | Optional pediatric-block rule: service $s^\dagger$'s rooms on day $d^\dagger$ admit only patients aged $\le i^\dagger$ |

## 6. Model

### 6.1 Decision Variables

$$
x_{cdr} \in \{0,1\} \quad \forall c \in C,\ d \in D_c,\ r \in R
\qquad\text{— 1 if case $c$ is scheduled on day $d$ in room $r$}
$$

$$
z_c \ge 0 \quad \forall c \in C : p_c \ne 4
\qquad\text{— 1 if case $c$ is NOT scheduled this week (forced to \{0,1\} by C3)}
$$

> **Pre-filtering.** In code, $x_{cdr}$ is only created for triples that pass the
> room-service roster, ambulatory-only, pediatric-block and surgeon-availability checks
> — the same role as eliminating $a_{dr}^{s_c}=0$ terms analytically. This is the main
> variable-count reduction mechanism (see `_feasible_triples` in
> `src/solvers/milp_baseline_solver.py`).

### 6.2 Objective Function

$$
\min \quad
\underbrace{\sum_{c:\,dd_c \ge 0}\ \sum_{d \in D_c, r \in R} \big[dd_c + d\big]\, x_{cdr}}_{\text{Term 1 — on-time cases, prefer earlier days}}
\ +\
\underbrace{\sum_{c:\,dd_c < 0}\ \sum_{d \in D_c, r \in R} \big[dd_c + \alpha d\big]\, x_{cdr}}_{\text{Term 2 — overdue cases, urgency multiplier }\alpha}
\ +\
\underbrace{\sum_{c:\,p_c \ne 4} p_c\, w_c\, z_c}_{\text{Term 3 — non-scheduling penalty}}
$$

(here $d \in \{1,\dots,5\}$ is the numeric index of the day, i.e. $d=1$ for the first
day of the horizon — matching `d_val` in the code.)

**Reading it:** Term 1 makes the model prefer to schedule cases with little slack left
sooner rather than later; Term 2 does the same for already-overdue cases but multiplies
the day coefficient by $\alpha>1$, so deferring an overdue case to later in the week is
disproportionately expensive. Term 3's weight $w_c$ is calibrated (§6.3) to always
exceed any Term-1/2 coefficient, so the model only leaves a case unscheduled when no
feasible slot exists — never as a cheaper alternative to scheduling it late.

### 6.3 Non-scheduling penalty $w_c$

$$
w_c = \text{PenaltyCurve}\big(dd_c \cdot \mu_{p_c}\big) + 1.2 \cdot \max_{c' \in C} dd_{c'}
$$

`PenaltyCurve` is a piecewise-increasing function of (priority-normalised) days to
deadline — sharp escalation as the deadline approaches and is breached (see
`src/model/penalty.py`; shape adapted from Marques & Captivo, 2015, §5.1). The
displacement term `1.2 * max(dd)` guarantees $w_c$ dominates every Term-1/2
coefficient, which is what makes Term 3 a true last resort.

### 6.4 Constraints

**C1 — at most one scheduled occurrence per patient per week**
$$
\sum_{\substack{c \in C:\\ \text{patient}(c)=n}} \sum_{d,r} x_{cdr} \le 1 \qquad \forall n
$$

**C2 — priority-4 cases must run on day 1**
$$
\sum_{r \in R} x_{c,1,r} = 1 \qquad \forall c \in C : p_c = 4
$$

**C3 — every other case is scheduled exactly once, or penalised**
$$
\sum_{d \in D,\, r \in R} x_{cdr} + z_c = 1 \qquad \forall c \in C : p_c \ne 4
$$

**C4 — room-service roster** (enforced by the pre-filter, not a separate row)
$$
x_{cdr} = 0 \quad \text{whenever } a_{dr}^{\,\text{service}(c)} = 0
$$

**C5 — ambulatory-only rooms admit only day-case scopes** (pre-filter)

**C6 — pediatric-block rule** (pre-filter): on day $d^\dagger$, service $s^\dagger$'s
rooms admit no case with patient age $> i^\dagger$.

**C7 — room capacity (no overtime)**
$$
\sum_{c \in C} t_c^{\text{tot}}\, x_{cdr} \le k_{dr} \qquad \forall d \in D,\, r \in R
$$

**C8 — surgeon daily time limit**
$$
\sum_{\substack{c:\,\text{surgeon}(c)=h}} \sum_{r} t_c^{\text{op}}\, x_{cdr} \le k_{hd} \qquad \forall h \in H,\, d \in D
$$

**C9 — surgeon weekly time limit**
$$
\sum_{\substack{c:\,\text{surgeon}(c)=h}} \sum_{d,r} t_c^{\text{op}}\, x_{cdr} \le k_h \qquad \forall h \in H
$$

**C10 — shared equipment, day-level aggregate cap**
$$
\sum_{\substack{c:\,u_{ce}=1}} \sum_{r} x_{cdr} \le \kappa_{ed} \qquad \forall e \in E,\, d \in D
$$

This counts *how many* equipment-$e$ cases land on day $d$, not whether their actual
clock times overlap — a deliberately coarse approximation consistent with this model's
day-only granularity. It is the one constraint where the production CP-SAT model's
upgrade (exact concurrency via `AddCumulative`) measurably changes what's achievable —
see RESULTS.md, where it is the single largest source of the baseline/production
objective gap on the medium instance.

## 7. What We Include and Why

| Included | Rationale |
|---|---|
| Priority + waiting-time penalty in the objective | Evidence-based across multiple real systems (§2); without it the model is clinically blind to urgency |
| Room capacity (C7) | Core feasibility — a room cannot run over its opening hours |
| Surgeon daily + weekly limits (C8-C9) | Prevents overwork; at the daily-aggregate level also approximates "can't be in two rooms at once" |
| Room-service roster (C4) | Rooms are equipped/staffed for one specialty at a time in practice |
| One case per patient per week (C1) | Conservative default; avoids double-booking the same patient |
| Priority-4 locked to day 1 (C2) | These cases' clinical deadline is inside the current planning cycle — there is no "later this week" |
| Shared equipment, day-level (C10) | Explicitly named in the case prompt as a realistic bottleneck; modeled at the granularity this baseline supports |
| One ad hoc rule worked example (C6) | Demonstrates the model absorbs institution-specific carve-outs without new variable families |
| Deterministic durations | Standard tractable approximation (Denton et al., 2010); stochastic extension noted in §10 |

## 8. What We Exclude and Why

| Excluded | Rationale |
|---|---|
| Within-day sequencing / exact start times | Out of scope for *advance* scheduling (Cardoen et al., 2010); see PRODUCTION_FORMULATION.md, which adds it |
| Exact (time-based) equipment concurrency | Needs a clock; the baseline doesn't have one — see C10 above and the production model |
| Downstream recovery/ICU beds | Multi-day occupancy needs a different time unit than "day of surgery"; modeling it as a day-bucket would likely be wrong in either direction. Included properly in PRODUCTION_FORMULATION.md once interval/cumulative machinery is available |
| Nurses / anaesthetists as separate resources | Assumed pre-allocated by a roster tied to the room, not the case — a common simplification when they aren't the binding constraint |
| Stochastic durations | Adds real value (robustness) but also real complexity; flagged as the top extension in §10, not attempted here |
| Patient day-of-week preference | Not part of any clinical-priority system we used as evidence; a natural patient-centred extension |

## 9. Testing Against Real and Literature Instances

Two demo-scale instances ship in `src/data/instances.py`:

- `demo_instance()` — ~20 cases, sized to read by eye, exercising every constraint
  family (priority lock-in, equipment contention, pediatric block).
- `medium_instance()` — ~200 cases / 12 rooms / 5 services, structurally modeled on the
  multi-service, multiple-rooms-per-service shape used in the OR-scheduling benchmark
  literature (Cardoen, Demeulemeester & Beliën, 2010), used for the scaling trade-off in
  RESULTS.md.

For testing against **real hospital data** at production scale, two public,
CC BY-4.0-licensed datasets are a direct fit for this exact problem (same horizon, same
"Master Surgery Schedule" structure as §6.4's room roster):

- **Akbarzadeh & Maenhout, "Real life data for operating room scheduling problem"**
  (Ghent University Hospital OR log, May 2017) — Mendeley Data, DOI
  [10.17632/n2v49z2vnp.2](https://data.mendeley.com/datasets/n2v49z2vnp/2).
- **Akbarzadeh & Maenhout, "RealLife operating room scheduling dataset, 2021-Jan-May"**
  — 20 weekly-planning instances across 8 demand/flexibility configurations, Mendeley
  Data, DOI [10.17632/c8d342266x.1](https://data.mendeley.com/datasets/c8d342266x/1).

Both are real hospital logs released for exactly this kind of benchmarking, and their
schema (a master roster + per-case waiting-list records) maps directly onto
`PlanningInstance`: a loader would parse their case list into `SurgicalCase` rows and
their room/day roster into `OperatingRoom.service_assignment`, with no formulation
changes needed. This repo does not ship a parser for them (out of scope for a small
demo, per the case's own framing), but they are the right next step before any pilot
with a real hospital's data.

## 10. Extensions and Future Work

| Extension | Approach |
|---|---|
| Stochastic durations | Two-stage stochastic program: first stage selects/places cases, second stage absorbs duration realisations via overtime cost or case bump |
| Exact equipment + downstream beds | Already done — see PRODUCTION_FORMULATION.md |
| Nurse/anaesthetist rostering | Extend $H$ to cover support staff; add team-level NoOverlap/sum constraints, same pattern as surgeons |
| Multi-week rolling horizon | Solve weekly; carry forward unscheduled cases with an increased priority weight |
| Robust scheduling | Min-max regret or chance-constrained room capacity, buffer proportional to duration variance |
| Real-time rescheduling | Large Neighbourhood Search seeded from the current schedule, for same-day disruptions |

## 11. Open Questions

### Q1 — Passing the Torch

I'd hand a developer four things, not just the math: **(1)** this file plus
`src/model/types.py` — the dataclasses *are* the data dictionary (sets/parameters above
map 1:1 to fields), so there's one source of truth for "what is a case/room/surgeon",
not two. **(2)** the solver code itself, since every constraint here is labeled (C1…C10)
and the matching code block carries the same label as a comment — read side by side,
there's no ambiguity about which line implements which formula. **(3)**
`tests/test_model.py` as the acceptance contract: any reimplementation must pass the
same hard-constraint checks (`_assert_hard_constraints`) on the same demo instance, and
I'd ask them to add a test per new constraint before writing the constraint. **(4)** a
short glossary of the few domain terms that aren't self-explanatory (e.g. "MSS"/room
roster, "ambulatory", priority tiers) — most miscommunication on these projects is
vocabulary, not math.

### Q2 — A Library of Models

I'd structure it in four layers, solver-agnostic at every layer except the bottom one.
First, core data abstractions — typed dataclasses like `PlanningInstance`, with no
solver imports — that any model is built on top of. Second, a small set of reusable
*constraint patterns* (capacity-sum, no-double-booking via NoOverlap, tiered-priority
tardiness objective, eligibility pre-filter) that recur across scheduling problems,
since nurse rostering and bed allocation need the same shapes, not the same model.
Third, problem templates that compose those patterns into a specific formulation —
this repo's baseline and production models are two such templates. Fourth, a thin
solver-adapter layer, one file per backend family (MILP, CP, local search), so a new
problem picks a backend without rewriting how its constraints are expressed. The
baseline-vs-production-vs-local-search trade-off this repo demonstrates is itself a
template for that last layer: profile the instance sizes you'll actually see, then pick
the cheapest model that meets the latency/quality bar at that scale.

## 12. References

1. Cardoen, B., Demeulemeester, E., & Beliën, J. (2010). Operating room planning and
   scheduling: A literature review. *European Journal of Operational Research*, 201(3),
   921-932.
2. Marques, I., & Captivo, M.E. (2015). *Planeamento de cirurgias eletivas no Centro
   Hospitalar Lisboa Norte*. MSc thesis, Universidade de Lisboa. (Evidence source for
   the priority/penalty mechanism shape — not the literal subject of this model.)
3. Denton, B.T., Miller, A.J., Balasubramanian, H.J., & Huschka, T.R. (2010). Optimal
   allocation of surgery blocks to operating rooms under uncertainty. *Operations
   Research*, 58(4), 802-816.
4. SIGIC — Sistema Integrado de Gestão de Inscritos para Cirurgia, Portaria n.º 45/2008,
   Diário da República, Portugal. (Evidence source for tiered max-wait policy design.)
5. Van Riet, C., & Demeulemeester, E. (2015). Trade-offs in operating room planning for
   electives and emergencies. *OR Spectrum*, 37(1), 59-87.
6. Akbarzadeh, B., & Maenhout, B. (2023). Real life data for operating room scheduling
   problem [Data set]. Mendeley Data, V2. https://doi.org/10.17632/n2v49z2vnp.2
7. Akbarzadeh, B., & Maenhout, B. (2023). RealLife operating room scheduling dataset,
   2021-Jan-May [Data set]. Mendeley Data, V1. https://doi.org/10.17632/c8d342266x.1
