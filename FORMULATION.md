# Elective Surgery Scheduling — Problem Formulation

**Author:** Hector Bonilla

## 1. Problem context

A hospital group runs a waiting list of elective (planned) surgical cases that is
always longer than what one week of operating-room time can absorb. Every week, someone
has to decide which of those cases actually run — in which room, at what time, on which
day, with which surgeon — and that decision has to satisfy two things at once: it has to
be *feasible* (rooms, surgeons, and the handful of shared resources a hospital has are
all finite), and it has to be *fair* in a clinical sense, so that a patient with a
genuinely urgent condition doesn't sit behind a routine case just because the routine
case happened to reach the top of a first-in-first-out queue first.

This is a real, well-studied operational problem, not a toy one. A few things make it
worth getting right rather than improvising room-by-room:

- **Operating-room time is expensive and inflexible.** A widely cited cost estimate puts
  one minute of OR time at roughly $30–40 in a U.S. hospital, once staffing, equipment,
  and overhead are amortized (Macario, 2010) — and unlike most other hospital capacity,
  an OR-minute that goes unused today cannot be banked for tomorrow. A schedule that
  leaves rooms idle, or that forces overtime to absorb a case that didn't fit, is a real
  cost, not a rounding error.
- **The waiting list itself is the thing patients and regulators watch.** Public health
  systems that run large elective waiting lists publish breach statistics because that's
  the number that gets audited. Marques & Captivo (2015) report that, in one Portuguese
  hospital's 2016 audit, 16% of roughly 7,400 waiting patients had already passed their
  clinically-defined deadline, by 147 days on average — a planner who only optimizes
  total throughput, with no notion of deadline, can hit a good throughput number while
  quietly failing exactly the patients the system is supposed to protect.
- **Cardoen, Demeulemeester & Beliën's (2010) literature review** — the standard survey
  for this problem family — frames "advance scheduling" (deciding which cases run on
  which day, ahead of the day itself) as a distinct sub-problem precisely because it's
  where the case-selection and fairness trade-offs above actually get made; the
  finer-grained "allocation" and "monitoring" sub-problems they describe (exact intraday
  sequencing, same-day disruption) build on top of an advance schedule rather than
  replacing it.
- **Elective and emergency demand compete for the same rooms.** Van Riet &
  Demeulemeester (2015) document the trade-off directly: capacity reserved for
  emergencies is capacity not available for the waiting list, and how a hospital splits
  that capacity is itself a planning decision, not just an emergent property of "leave
  some slack." This project's model doesn't size that reserve explicitly (see §2,
  point 7), but it's the reason an emergent-add-on priority tier exists in the model at
  all.

The case brief names several concrete sources of difficulty that show up in real OR
scheduling — limited room-hours, surgeon availability, shared equipment, turnover
between cases, downstream bed pressure — and explicitly invites simplification rather
than a full hospital simulation. Section 2 below states exactly what this model keeps,
what it leaves out, and why each of those calls was made.

## 2. Assumptions and simplifications

These are deliberate scoping decisions made up front, each with a reason and a note on
what relaxing it would actually require — not omissions discovered after the fact.

1. **Deterministic durations.** Every case carries one estimated operative duration
   (in practice, a historical median for that procedure type) rather than a probability
   distribution. Real surgical durations are genuinely uncertain, and the bias runs in a
   predictable direction — schedules built on optimistic point estimates tend to run
   long, not short, which is exactly the failure mode that produces overtime and
   downstream cancellations. The deterministic case is the standard tractable starting
   point in this literature (Denton, Miller, Balasubramanian & Huschka (2010) use it and
   discuss the stochastic extension directly), and it keeps the model's structure
   legible enough to verify by hand on a 20-case demo. Treating durations as
   distributions instead turns this into a two-stage stochastic program — first-stage
   case placement, second-stage absorption of the realized duration via overtime cost
   or a bumped case — which is real additional machinery, not a parameter tweak; it's
   the first item in §12's extension table for that reason, not something quietly
   folded into this version.

2. **Room turnover depends on the case's own duration, not on which two cases are
   adjacent.** A longer procedure plausibly needs a longer reset — more instruments to
   account for, more drapes, often a bigger room turnover — so turnover time is bucketed
   by the case's own operative duration (§5 has the exact buckets and where they come
   from) rather than fixed at one flat number for every case. What this still leaves out
   is the *sequence*-dependent piece: a genuine deep clean after a contaminated case, or
   a full equipment changeover between two different specialties' cases back to back,
   costs more than the bucket alone captures, and that cost depends on which two cases
   end up adjacent in the room, not on either case in isolation. Modeling that properly
   needs a different primitive — a sequence variable with a transition-cost matrix
   between case types — which is exactly what the optional CP Optimizer backend in
   Appendix B demonstrates. It isn't the primary model because the gain doesn't show up
   structurally in the cases that matter most here (rooms in this project's demo data
   are rostered to one service per day, so a same-room service *switch* never actually
   occurs — see Appendix B.1's honest note on that).

3. **Surgeons are the binding staffing resource; nurses and anaesthetists aren't
   modeled separately.** Support staff are assumed to come bundled with whichever room
   is rostered and staffed that day. This is a real, common simplification exactly when
   it's true that the surgeon's own calendar — not the support team's — is what actually
   constrains the schedule, which tends to hold for hospitals where nursing rosters are
   built around the room/block schedule rather than the other way around. Where it
   isn't true (a hospital genuinely short on scrub nurses or anaesthetists, independent
   of which surgeon is operating), this is the first assumption to drop, and the
   mechanism for dropping it is already in the model: extend $H$ to cover support
   staff and reuse the same NoOverlap/sum pattern already built for surgeons (§12).

4. **At most one occurrence per patient per week.** A patient with several queued
   procedures gets at most one of them scheduled in a given week's instance. This is the
   conservative default, not a clinical rule — some services legitimately combine
   same-day multi-procedure cases (shared anaesthesia, one recovery period), and that's
   a real efficiency a hospital might want to capture. It's deliberately not assumed
   here because it's service-specific (what counts as safely combinable is a clinical
   judgment, not a scheduling one), and a wrong default in that direction is harder to
   catch than a merely conservative one.

5. **Bed/ICU capacity is constant across the week, with an explicit overflow charge
   rather than a silent approximation.** Recovery and ICU beds are modeled as a shared,
   capacity-limited resource (§9, constraint C11), but that capacity doesn't vary by day
   — a hospital with a real weekend staffing cut, where fewer beds are actually
   available, would need a per-day-segmented version instead. Rather than ignore that
   gap or simply forbid any stay from crossing into it, a stay that runs past the
   modeled week is charged an explicit, configurable overflow penalty (§5,
   `weekend_bed_overflow_penalty`) instead of being silently approximated either as free
   or as impossible.

6. **One ad hoc institutional rule is included as a worked example, not a special case
   bolted onto the math.** A configurable "pediatric block" carve-out — a given
   service's rooms, on a given day, restricted to patients under some age — is in the
   model specifically to demonstrate that real hospitals' accumulated local rules don't
   require new variable families. It's one more eligibility predicate evaluated before
   a candidate slot is even created (§8), the same mechanism as the room-service roster.
   The age threshold itself (8 years, in the demo data) is illustrative, not clinical
   guidance.

7. **Single week, single hospital, no same-day disruption, no explicit emergency
   reserve.** The model produces an offline plan for one week at one site and does not
   re-optimize when an emergency case arrives mid-week, nor does it carve out a separate
   capacity reserve for emergencies the way Van Riet & Demeulemeester (2015) describe
   real hospitals doing (§1). Reacting to a disruption against an existing plan is a
   genuinely different problem from building the plan in the first place — it's the
   second item in §12's extension table, not something this version pretends to handle
   by being silent about it.

## 3. Where the priority/penalty mechanism comes from

Cases are ranked into four clinical priority tiers, each with a maximum acceptable wait,
and the objective penalizes a case the longer it sits past that deadline. This isn't
invented for this exercise — it's how several public health systems actually manage
elective waiting lists:

- Portugal's SIGIC system (Portaria n.º 45/2008) sets four priority tiers with maximum
  waits of 270/60/15/3 days. The 2016 audit cited in §1 — 16% of roughly 7,400 patients
  already past their tier's deadline, by 147 days on average (Marques & Captivo, 2015)
  — is exactly why breach penalties in this model aren't cosmetic: it's the number a
  planner using this kind of system is actually graded on.
- The UK NHS's Referral-to-Treatment targets and several Canadian provincial wait-time
  benchmarks use the same shape: tiered maximum waits, tracked breach rates. A single
  FIFO queue doesn't reflect clinical risk, and "shortest job first" doesn't either.
- Cardoen, Demeulemeester & Beliën's (2010) literature review treats case-to-day
  assignment under a priority/deadline structure as a distinct, well-studied
  sub-problem ("advance scheduling") — the scope this model targets, extended with
  exact intra-day timing (§4).

Every number attached to this mechanism — maximum wait per tier, the priority
multipliers, the penalty curve — is a field on `PlanningInstance`
(`src/model/types.py`), not a constant buried in solver code. A hospital adopting this
plugs in its own policy without touching the model; §6 below explains exactly how those
defaults were chosen and what a real deployment should replace.

## 4. Why constraint programming, not a bigger MILP

This is the central modeling decision in the project, so it's worth arguing rather than
asserting.

The problem is disjunctive resource-constrained scheduling: cases competing for rooms,
surgeons, and a shared piece of equipment, each of which can hold exactly one thing at a
time (or, for the equipment, a small fixed number of things). That's precisely the
structure CP's global constraints — `NoOverlap`, `Cumulative` — exist for, and it's
exactly the structure a linear capacity-sum constraint gets wrong in one specific way:

A constraint like "total minutes of equipment use today ≤ capacity" certifies that a set
of cases' durations *fit* inside the day. It does not certify they can be placed
*without colliding*. For a single, non-shared room those two statements happen to
coincide — any set of durations that fits a day can always be laid out sequentially. They
stop coinciding the moment a resource is shared across more than one room, which is
exactly the shape of this project's C-arm: a sum can forbid two genuinely
non-overlapping uses just because they land on the same day, while in other configurations
it can be too permissive in the other direction. This isn't a theoretical nuance —
RESULTS.md shows the demo instance's day-bucket equipment cap forbidding a schedule
that's perfectly legal once you check actual clock times.

The textbook MILP alternative — a continuous-time disjunctive formulation with one
binary "A-before-B" variable per potentially-conflicting pair of cases, tied together
with big-M constraints — works, but has two costs that are well documented (Baptiste, Le
Pape & Nuijten, *Constraint-Based Scheduling*, 2001): the variable count grows
quadratically in the number of conflicting pairs, and the big-M constants weaken the LP
relaxation as that count grows, so branch-and-bound spends real time re-discovering
structure a propagation-based method gets for free. It also can't express a resource
with capacity greater than one (a 2-bed pool, say) without yet more pairwise variables.

`NoOverlap` and `Cumulative` are global constraints with their own specialized,
polynomial-time propagation — `NoOverlap` via an O(n log n) sweep (Vilím, 2004),
`Cumulative` via timetabling/edge-finding (Schutt, Feydy, Stuckey & Wallace, 2009). They
prune the search directly from the problem's time/resource structure instead of making
the solver rediscover it pair by pair through branching. That's the actual mechanism
behind "CP scales better here" — not a vague claim that one solver is smarter than
another.

**Why CP-SAT specifically.** It runs a parallel portfolio of search strategies — several
complete-search workers plus large-neighborhood-search workers improving an incumbent,
sharing learned information through a common core (Perron & Furnon, Google OR-Tools
documentation). The implementation doesn't hand-roll a branching strategy on top of
this; OR-Tools' own guidance is that the default portfolio beats a hand-tuned single
strategy unless you have structural insight the model isn't already exposing through
its `NoOverlap`/`Cumulative` calls, and this project doesn't.

A day-bucket MILP was also built (`src/solvers/milp_baseline_solver.py`) — not as a
second deliverable, but as the empirical check on the argument above: same sets, same
objective, same priority/eligibility constraints, but room and equipment capacity
expressed as linear sums instead of exact non-overlap. RESULTS.md reports the
head-to-head run; the result is what the argument predicts.

## 5. Sets and parameters

| Symbol | Meaning |
|---|---|
| $c \in C$ | Surgical cases — one entry per patient-procedure pair on the waiting list |
| $d \in D$ | Planning days, $D = \{1,\dots,5\}$, one work week |
| $r \in R$ | Operating rooms |
| $h \in H$ | Surgeons |
| $e \in E$ | Shared equipment types (e.g. a mobile imaging unit) |
| $D_c \subseteq D$ | Days case $c$ may run on — $\{1\}$ for must-run-today cases, all of $D$ otherwise |

| Parameter | Meaning |
|---|---|
| $t_c^{op}$ | Operative duration of case $c$ (minutes) |
| $t_c^{clean}$ | Room turnover after case $c$ — set from $t_c^{op}$ (§6.1), not a flat constant |
| $t_c^{tot} = t_c^{op} + t_c^{clean}$ | Total room-occupation time |
| $k_{dr}$ | Opening minutes of room $r$ on day $d$ |
| $k_{hd}$ | Surgeon $h$'s daily operative-time limit on day $d$ |
| $k_h$ | Surgeon $h$'s weekly operative-time limit |
| $p_c \in \{1,2,3,4\}$ | Clinical priority of $c$ — 4 means "must run today" |
| $\text{wl}_c$ | Days $c$ has already waited as of the planning date |
| $\text{wl}^{max}_p$ | Maximum acceptable wait for priority $p$ (default 270 / 60 / 15 / 3 days, §6.3) |
| $dd_c = \text{wl}^{max}_{p_c} - \text{wl}_c$ | Slack to deadline (negative = already overdue) |
| $\mu_p$ | Priority multiplier (default 1 / 4.5 / 18 / 90, §6.3) |
| $w_c$ | Non-scheduling penalty for $c$ (§7) |
| $\alpha > 1$ | Urgency multiplier applied to overdue cases (default 2.0, §6.4) |
| $u_{ce} \in \{0,1\}$ | 1 if case $c$ needs equipment $e$ |
| $\kappa_{ed}$ | Capacity of equipment $e$ on day $d$ (§6.5) |
| $\rho(c)$ | Recovery/bed pool case $c$ needs ("none" if not applicable) |
| $\text{los}_c$ | Length of stay in that pool, in days |
| $\beta_\rho$ | Bed count for pool $\rho$ (constant across the week — §2, point 5) |
| $\pi^{ovf}$ | Per-day penalty for a bed stay crossing the horizon boundary (§6.5) |

A room is also tied to one service per day (its roster), may be ambulatory-only, and may
fall under an optional pediatric-block rule restricting it to patients under some age on
a given day. These are eligibility predicates, not extra variables — see §8.

## 6. How the parameters were calibrated

Every default below lives on `PlanningInstance` (`src/model/types.py`,
`src/data/instances.py`), not hardcoded in solver logic, specifically so a hospital can
override its own policy without touching the model. This section is the honest
breakdown of where each default actually comes from — literature, a derivable rule, a
deliberate choice to make the demo data exercise a constraint, or a placeholder a real
deployment must replace — because those four categories call for very different levels
of trust.

### 6.1 Room turnover (15 / 25 / 40 minutes, by duration)

Real OR turnover is reported anywhere from about 15 to 60 minutes depending on
procedure complexity and infection-control needs — a single flat number for every case
understates that spread in one direction (overcharging quick cases) without correcting
it in the other (undercharging long ones). The three buckets used here —
$t_c^{clean} = 15$ for $t_c^{op}\le60$, $25$ for $60<t_c^{op}\le150$, $40$ for
$t_c^{op}>150$ — are a deliberately simple proxy for that spread: short cases need less
to reset (fewer instruments, less drape area), long cases plausibly need more. This is
a heuristic, not a measured rule — it captures the part of real turnover variation that
correlates with how long the case itself ran, but not the part that depends on *which
two cases* are adjacent (point 2 in §2; Appendix B has the more expressive alternative).
A real deployment should replace these three numbers with a hospital's own measured
turnover times, bucketed however its data actually clusters.

### 6.2 Room hours and surgeon time budgets

Room opening minutes ($k_{dr}$) in the demo data range from 360 to 660 minutes/day (6
to 11 hours) across the three services, chosen to give the instance a mix of tight and
generous rooms rather than one uniform block — this is an instance-design choice to
exercise both a binding and a non-binding room-capacity constraint in the same demo, not
a number taken from any one hospital's actual published hours.

Surgeon limits are more structurally grounded: 240 minutes/day in the demo data is one
standard half-day theatre session, a common scheduling unit in the block-scheduling
literature (Cardoen et al., 2010); 960 minutes/week (four such sessions) reflects a
typical surgical job plan where a consultant's week splits across theatre time, clinics,
ward rounds, and on-call duties, rather than being theatre time five days straight. The
`medium_instance()` generator uses 300/1300 instead — a "larger hospital group, higher
throughput" framing for that specific synthetic instance, an explicit modeling choice
for testing at scale, not a second citation. Either way, this is the first number a real
deployment should swap for the receiving hospital's actual published session length and
job-plan structure.

### 6.3 Maximum waits and priority multipliers

The maximum-wait defaults (270 / 60 / 15 / 3 days) are taken directly from Portugal's
SIGIC policy (§3) — they're used as a credible, evidence-based starting point precisely
because they're a real system's actual policy, not because this model targets the
Portuguese system specifically. A hospital with its own published wait-time targets
should use those instead; the field exists on `PlanningInstance` for exactly that
substitution.

The priority multipliers $\mu_p$ (1 / 4.5 / 18 / 90) aren't a separately invented set of
numbers — they're built directly from the same maximum-wait figures, as the ratio of
priority-1's allowance to each tier's own:

$$\mu_p = \frac{\text{wl}^{max}_1}{\text{wl}^{max}_p} \qquad\Rightarrow\qquad
\mu_2=\tfrac{270}{60}=4.5,\quad \mu_3=\tfrac{270}{15}=18,\quad \mu_4=\tfrac{270}{3}=90$$

The reasoning behind that specific rule: a tier that's only allowed a twelfth of
priority-1's wait before breaching (priority-3's 15 days vs. priority-1's 270) is, by
the policy's own design, treated as roughly twelve times more wait-sensitive — so
weighting a day of breach at that tier twelve times as heavily as a day of breach at
priority-1 is consistent with the same policy that set the wait targets in the first
place, rather than a second, independent judgment call. That's a real starting point,
but it is still ultimately a modeling choice, not an empirical fact — see §6.6 for how a
hospital would actually calibrate it for its own risk tolerance, and the equity caveat
that comes with doing that calibration uniformly across tiers.

### 6.4 The urgency multiplier $\alpha$ and the displacement margin

$\alpha=2.0$ scales the day coefficient for already-overdue cases in the objective's
Term 2, so the model prefers to front-load an overdue case earlier in the week once it's
decided to schedule it at all. $\alpha$ appears nowhere else in the model — not in Term
3 (the non-scheduling penalty), not in any constraint — so it can provably only change
*which day* an overdue case lands on, never *how many* cases get scheduled or *which*
ones; that's governed by capacity and by Term 3's relative size, and neither involves
$\alpha$. A hospital tuning this value is deciding how hard to front-load already-late
cases, not how many late cases get served.

The non-scheduling penalty $w_c$ (§7) needs to dominate every Term-1/2 coefficient a
scheduled case could accrue, or the model could prefer dropping a schedulable case
purely to dodge a tardiness charge. The largest such coefficient is bounded by
$\max_c dd_c + \alpha\cdot n_{days}$ (a maximally-slack case, evaluated on the last day,
in the overdue branch), so the minimum safe displacement margin is

$$\text{margin}_{\min} = 1 + \frac{\alpha \cdot n_{days}}{\max_c dd_c}$$

With this project's defaults ($\alpha=2$, $n_{days}=5$, $\max_c dd_c\approx270$ for a
priority-1 case at its policy's maximum wait), $\text{margin}_{\min}\approx1.037$ — so
the 1.2 used in $w_c$'s formula (§7) clears it with real margin to spare, which matters
because $\max_c dd_c$ shrinks on an instance with only short-horizon, high-priority
cases, and a fixed margin has to stay safe across that range, not just on this one
instance.

### 6.5 Equipment and bed capacity

The demo instance gives the shared C-arm a capacity of exactly 1, deliberately tight
enough to force real contention among the four cases that need it — the point of this
parameter in the demo data is to make the CP-vs-MILP gap in §4 actually visible, not to
model one specific hospital's actual imaging-unit inventory. `medium_instance()` scales
this to 2, loosely tracking the larger case volume rather than any particular
inventory count.

ICU bed capacity (2/day in the demo instance, 6/day in the medium instance) follows the
same logic: tight enough that a couple of long-stay cases create real pressure on the
pool, without making the instance infeasible outright. The overflow penalty
$\pi^{ovf}=50$ per day (§2, point 5) is sized to sit between the two things it has to
balance: large enough relative to a typical Term-1/2 day-coefficient swing that the
model actually avoids pushing a stay past the horizon when there's a same-quality
alternative, but small enough relative to $w_c$ (which runs from the hundreds into the
low thousands once the priority multiplier and displacement are applied) that the model
never prefers leaving a case off the schedule entirely just to avoid one overflow day.
None of these three numbers — C-arm capacity, bed capacity, overflow penalty — are
measured from a real hospital; they're sized to make the demo instance exercise the
constraint they attach to, and should be replaced with a hospital's actual equipment
inventory and bed census before this touches a real planning cycle.

The 12% ICU-admission probability used inside `medium_instance()`'s random case
generator is a notch further removed even than that: it only controls how the synthetic
test data is generated and is never seen by the optimizer as a parameter at all. It
should be replaced with real admission-rate data for the relevant procedures, not tuned
as if it were a policy knob.

### 6.6 Calibrating $\mu_p$ for a real hospital, and an equity caveat worth flagging early

§6.3's $\mu_p=\text{wl}^{max}_1/\text{wl}^{max}_p$ rule is a defensible starting point,
not a substitute for an actual policy conversation, because the multiplier ultimately
encodes a hospital's own risk tolerance for breaching each tier — and that's a clinical
and institutional judgment, not something a formula can derive on its own. In practice,
calibrating it means structured elicitation with service chiefs, anchored on concrete
trade-offs ("a priority-2 patient 30 days over target versus a priority-1 patient 200
days over theirs — which is worse, by roughly what factor?") rather than asking for
multiplier values directly, since clinicians reason fluently in scenarios and rarely in
objective-function coefficients.

One thing worth flagging *before* that conversation, not after: because $\mu_p$ is keyed
to priority *tier*, not to overdue severity directly, raising it uniformly protects
high-tier cases generally, not specifically the most-overdue ones. If one specialty's
case mix happens to skew toward lower tiers and longer overdue stretches at the same
time, a uniform increase in $\mu_p$ does nothing for it. The right fix for that, if it
shows up in practice, is a per-service tracked target or a fairness constraint layered
on top (§12), not a bigger global multiplier.

## 7. Objective

$$
\min \quad
\underbrace{\sum_{c:\,dd_c \ge 0}\sum_{d \in D_c,\,r} [dd_c + d]\,\text{pr}_{cdr}}_{\text{on-time cases, prefer earlier days}}
\;+\;
\underbrace{\sum_{c:\,dd_c < 0}\sum_{d \in D_c,\,r} [dd_c + \alpha d]\,\text{pr}_{cdr}}_{\text{overdue cases, urgency-weighted}}
\;+\;
\underbrace{\sum_{c:\,p_c \ne 4} w_c\,u_c}_{\text{non-scheduling penalty}}
\;+\;
\underbrace{\pi^{ovf}\sum_{c:\,\rho(c)\ne\text{none}} \text{overflow}_c}_{\text{bed-overflow penalty}}
$$

The first two terms reward scheduling a case early within the week, with overdue cases
getting their day coefficient scaled by $\alpha$ so the model front-loads them. The
third term is what actually decides who gets left off this week's list:

$$w_c = \mu_{p_c}\cdot\text{PenaltyCurve}(dd_c) + 1.2\cdot\max_{c'\in C} dd_{c'}$$

`PenaltyCurve` (`src/model/penalty.py`) is flat while a case still has slack, then
escalates sharply once it crosses its deadline and keeps climbing the longer it stays
overdue — the shape several of the systems cited in §3 use to make breaches expensive
rather than just "less preferred." $\mu_{p_c}$ scales that curve's output once, by
priority tier, per §6.3. The $1.2\times\max dd_{c'}$ term is the displacement derived in
§6.4, sized so $w_c$ always exceeds any Term-1/2 coefficient a scheduled case could
accrue — the model only ever drops a case when there genuinely isn't room for it, never
as a cheap way to dodge a tardiness charge.

The fourth term only applies to cases needing a recovery/ICU bed and is explained
alongside the constraint it pairs with, C11, in FORMULATION_CP.md §4.

## 8. Decision variables

For every $(c, d, r)$ that survives eligibility filtering (right service, right scope,
not blocked by the pediatric rule, surgeon available that day):

$$\text{pr}_{cdr} \in \{0,1\} \qquad \text{start}_{cdr} \in [0, k_{dr}]$$

a presence flag and a start time, plus an unscheduled flag for every case that isn't
priority-4:

$$u_c \in \{0,1\}, \qquad \sum_{d,r} \text{pr}_{cdr} + u_c = 1$$

CP-SAT additionally turns each candidate slot into two interval variables of different
sizes — one sized $t_c^{tot}$ for room occupancy, one sized $t_c^{op}$ for the surgeon's
own time — because a room needs to stay blocked through cleaning while the surgeon is
free as soon as the operation ends. FORMULATION_CP.md §2 has the exact CP-SAT objects;
this section states the model independently of how any one solver represents it.

## 9. Constraints, summarized

Full math for each is in FORMULATION_CP.md §4, with the same numbering used in the
solver's code comments.

- **C1.** At most one scheduled occurrence per patient this week.
- **C2.** Priority-4 cases must run on day 1 — by the time a case is flagged this
  urgent, "later this week" isn't a real option.
- **C3.** Every other case is either scheduled exactly once or counted as unscheduled.
- **C4–C6.** Eligibility: room-service roster, ambulatory-only rooms, the optional
  pediatric block. These are pre-filters on which $(c,d,r)$ triples even get a variable,
  not constraint rows.
- **C7.** A room runs one case at a time — exact non-overlap, not a capacity sum.
- **C8.** A surgeon is in one room at a time, on their own time window (not the room's
  cleaning buffer) — plus a daily-minutes cap, since non-overlap alone bounds
  concurrency, not total hours.
- **C9.** Surgeon weekly time limit.
- **C10.** Shared equipment capacity, checked against actual time overlap rather than a
  daily headcount — the constraint family §4's argument is built on.
- **C11.** Recovery/ICU bed capacity. A bed stay starts on the day of surgery and runs
  for `los_c` days; this needs a real notion of "day of surgery" to even state, which is
  the concrete reason this model is interval-based at all rather than a day-bucket sum.

## 10. Two carve-outs worth calling out

**Room-service roster (C4).** In practice an OR is set up and staffed for one specialty
at a time, not shared minute-by-minute across services — this is captured as a
room/day → service assignment, checked before a case is even offered that room.

**Pediatric block.** A configurable rule restricts a given service's rooms on a given
day to patients under some age. Hospitals accumulate rules like this constantly, and the
point of including one is that it costs nothing structurally — it's one more eligibility
predicate evaluated during candidate generation, not a new variable family or a special
case in the objective.

## 11. Testing instances

Two instances ship in `src/data/instances.py`:

- `demo_instance()` — 20 cases, 5 rooms, 6 surgeons. Small enough to read by eye, and
  exercises every constraint family: priority-4 lock-in, the shared C-arm, the
  pediatric block, recovery beds, room and surgeon capacity.
- `medium_instance()` — ~200 cases, 12 rooms, 17 surgeons, modeled loosely on the
  multi-service benchmark structure in Cardoen, Demeulemeester & Beliën (2010). Used to
  check the model still solves in reasonable time once it's too big to eyeball, and
  where the CP-vs-MILP gap from §4 actually shows up at scale (RESULTS.md).

For testing against real hospital logs rather than synthetic data, two CC BY-4.0
datasets are a direct structural fit (same horizon, same master-roster shape as §10):

- Akbarzadeh & Maenhout (2023), *Real life data for operating room scheduling problem*
  (Ghent University Hospital, May 2017). Mendeley Data.
- Akbarzadeh & Maenhout (2023), *RealLife operating room scheduling dataset,
  2021-Jan-May* — 20 weekly instances across 8 demand/flexibility configurations.

Their schema maps onto `PlanningInstance` without any formulation change — what's
missing is a loader, intentionally not built here given the brief's "small demo" scope.

## 12. Extensions

| Extension | Approach |
|---|---|
| Stochastic durations | Two-stage stochastic program: first stage places cases, second stage absorbs duration draws via overtime cost or a bumped case |
| Same-day rescheduling | Large-neighbourhood search seeded from the current plan, re-optimizing only around the disruption |
| Explicit emergency reserve | Carve out a per-day capacity block (room-minutes or a dedicated room) the elective model can't touch, sized from observed emergency demand |
| Nurse/anaesthetist rostering | Extend $H$ to cover support staff with the same NoOverlap/sum pattern used for surgeons |
| Multi-week rolling horizon | Solve weekly, carry forward unscheduled cases at a bumped priority |
| Day-varying bed capacity | Replace the constant $\beta_\rho$ with a per-day-segmented cumulative resource |
| Per-specialty fairness | A secondary objective or constraint bounding each service's overdue share (§6.6) |
| Sequence-dependent turnover everywhere | Generalize Appendix B's transition-matrix approach beyond the single-service-per-room-per-day roster assumption (§2, point 2) |

## 13. Passing this off to a developer

The four things I'd hand over: this file plus FORMULATION_CP.md, since together they're
the math and there's nothing to negotiate about variable meaning that isn't already
written down; `src/model/types.py`, because the dataclasses are the data dictionary —
every symbol above maps to a field there, so there's one source of truth instead of two
that can drift apart; the solver itself, where every constraint carries the same C-number
as the math (read them side by side and there's no ambiguity about which code implements
which formula); and `tests/test_model.py` as the acceptance bar — any reimplementation
has to pass the same hard-constraint checks on the same demo instance, and I'd ask for a
new test alongside any new constraint, not after it. Most of the actual confusion on
projects like this turns out to be vocabulary (what's a "room roster," what does
"ambulatory" restrict, what does priority 4 actually mean operationally) rather than the
math itself, so a short glossary of those terms is worth more than it sounds like it
should.

## 14. A reusable library of models

Four layers, solver-agnostic except the bottom one. Core data types first — plain
dataclasses like `PlanningInstance`, no solver imports — since every model in the
library sits on top of some typed representation of its problem. Above that, a small set
of constraint *patterns* that recur across scheduling problems regardless of domain:
capacity sums, no-double-booking via NoOverlap, a tiered-priority tardiness objective,
an eligibility pre-filter. Nurse rostering and bed allocation need the same shapes, not
the same model, so the patterns belong in a shared layer and the models don't. Above
that, problem templates that compose those patterns into something specific — this
project's formulation is one template. And a thin solver-adapter layer at the bottom,
one file per backend family (MILP, CP, local search), so a new problem picks a backend
without rewriting how its constraints are expressed. The CP-vs-MILP comparison this
project runs end to end is itself the template for that last layer: argue the backend
choice from the problem's structure, then check it empirically on a small instance,
rather than defaulting to whichever backend the team happens to know best.

## 15. References

1. Cardoen, B., Demeulemeester, E., & Beliën, J. (2010). Operating room planning and
   scheduling: A literature review. *European Journal of Operational Research*, 201(3),
   921–932.
2. Marques, I., & Captivo, M.E. (2015). *Planeamento de cirurgias eletivas no Centro
   Hospitalar Lisboa Norte*. MSc thesis, Universidade de Lisboa.
3. Denton, B.T., Miller, A.J., Balasubramanian, H.J., & Huschka, T.R. (2010). Optimal
   allocation of surgery blocks to operating rooms under uncertainty. *Operations
   Research*, 58(4), 802–816.
4. SIGIC — Sistema Integrado de Gestão de Inscritos para Cirurgia, Portaria n.º 45/2008,
   Diário da República, Portugal.
5. Van Riet, C., & Demeulemeester, E. (2015). Trade-offs in operating room planning for
   electives and emergencies. *OR Spectrum*, 37(1), 59–87.
6. Macario, A. (2010). What does one minute of operating room time cost? *Journal of
   Clinical Anesthesia*, 22(4), 233–236.
7. Akbarzadeh, B., & Maenhout, B. (2023). Real life data for operating room scheduling
   problem [Data set]. Mendeley Data, V2. https://doi.org/10.17632/n2v49z2vnp.2
8. Akbarzadeh, B., & Maenhout, B. (2023). RealLife operating room scheduling dataset,
   2021-Jan-May [Data set]. Mendeley Data, V1. https://doi.org/10.17632/c8d342266x.1
9. Perron, L., & Furnon, V. *CP-SAT: a Constraint Programming Solver* (Google OR-Tools
   documentation). https://developers.google.com/optimization/cp
10. Baptiste, P., Le Pape, C., & Nuijten, W. (2001). *Constraint-Based Scheduling:
    Applying Constraint Programming to Scheduling Problems*. Kluwer Academic Publishers.
11. Vilím, P. (2004). O(n log n) filtering algorithms for unary resource constraints.
    *CPAIOR 2004*.
12. Schutt, A., Feydy, T., Stuckey, P.J., & Wallace, M.G. (2009). Why cumulative
    decomposition is not as bad as it sounds. *CP 2009*.
13. Laborie, P. (2009). IBM ILOG CP Optimizer for detailed scheduling illustrated on
    three problems. *CPAIOR 2009*.

---

## Appendix A — the comparison MILP, in detail

§4 introduces this as the empirical check on the CP-over-MILP argument, not a second
deliverable. Implemented in `src/solvers/milp_baseline_solver.py`; runnable via
`--solver milp-cbc` (bundled, no install needed), `--solver milp-gurobi`, or
`--solver milp-cplex` (both need a license OR-Tools/gurobipy can see).

Same sets and parameters as §5, minus the CP-only ones ($\pi^{ovf}$, $\rho(c)$,
$\text{los}_c$, $\beta_\rho$ — beds aren't expressible in this formulation at all, see
A.4).

### A.1 Decision variables

$$x_{cdr}\in\{0,1\}\ \forall c,d\in D_c,r \qquad z_c\in[0,1]\ \forall c: p_c\ne4$$

$z_c$ is relaxed to a continuous bound rather than declared binary; C3 below forces it
to $\{0,1\}$ at the optimum anyway, and the relaxation is free since nothing else in the
formulation benefits from declaring it binary up front. $x_{cdr}$ exists only for
triples surviving the same C4–C6 eligibility filter as the primary model.

### A.2 Objective

$$
\min \sum_{c:dd_c\ge0}\sum_{d,r}[dd_c+d]\,x_{cdr}
+ \sum_{c:dd_c<0}\sum_{d,r}[dd_c+\alpha d]\,x_{cdr}
+ \sum_{c:p_c\ne4} w_c\,z_c
$$

Identical in shape to §7's Terms 1–3, over $x_{cdr}/z_c$ instead of
$\text{pr}_{cdr}/u_c$, evaluated by the same `penalty.py` function every backend shares.

### A.3 Constraints

C1–C6 and C9 are unchanged from §9. C7 and C10 are where this formulation diverges from
the primary model:

**C7 — room capacity as a sum:**
$$\sum_c t_c^{tot}\,x_{cdr} \le k_{dr} \qquad \forall d,r$$

For a single room this is equivalent to exact non-overlap — any set of non-colliding
durations can always be packed sequentially — which is why C7 alone doesn't cost this
formulation anything by itself.

**C8 — surgeon, daily minutes only (no non-overlap variable exists in a MILP without a
big-M reformulation, §4):**
$$\sum_{c:\,\text{surgeon}(c)=h}\sum_r t_c^{op}\,x_{cdr} \le k_{hd} \qquad \forall h,d$$

**C10 — shared equipment, a day-level headcount:**
$$\sum_{c:u_{ce}=1}\sum_r x_{cdr} \le \kappa_{ed} \qquad \forall e,d$$

This counts how many equipment-$e$ cases land on a day, not whether their clock times
actually overlap — the single largest source of the objective gap measured in
RESULTS.md.

**No C11.** Recovery/ICU beds need a multi-day interval that starts on the day of
surgery. A day-bucket model has no variable that represents "day of surgery" as a value
— only as a fixed index a binary happens to be attached to — so there's no way to write
"occupy a bed for `los_c` days starting on whichever day this case lands" without first
becoming interval-based. This, more than the equipment gap, is the structural reason
this project ended up CP-based rather than MILP-based.

---

## Appendix B — IBM ILOG CP Optimizer, an alternative CP engine

This is an optional, license-gated backend (`src/solvers/cp_optimizer_solver.py`, run
with `--solver cp-optimizer`) included for one specific reason: it can model
sequence-dependent room turnover, something the primary CP-SAT model can't without
restructuring its interval variables. It is not a replacement for CP-SAT in this
project — see B.4 for the honest comparison.

### B.1 What's different

CP-SAT buckets cleaning time by the case's own duration (§6.1): every candidate's room
interval is sized $t_c^{tot} = t_c^{op}+t_c^{clean}$, so turnover is a property of one
case alone. CP Optimizer instead sizes the interval at $t_c^{op}$ alone and charges
turnover as a transition cost between whichever two cases end up adjacent in a room's
chosen sequence, via a `sequence_var` plus a transition matrix on `no_overlap`:

| | Same service, back to back | Different service, back to back |
|---|---|---|
| CP-SAT (duration-bucketed, §6.1) | charged on the case alone, not the pair | same |
| CP Optimizer (transition matrix) | 15 min — same equipment setup | 35 min — full changeover |

Neither number is "more correct" in the abstract — both are instance-configurable
defaults (`same_service_turnover_min` / `cross_service_turnover_min` in
`PlanningInstance`). What changed is expressiveness: CP-SAT's room interval has no
variable a turnover rule could attach to *which two cases* are adjacent; CP Optimizer's
sequence variable does.

### B.2 Sets, variables, constraints

Same $C,D,R,H,E$ and shared parameters as the primary model, plus a service index
$\sigma(c)$ and a transition table $\tau_{\sigma\sigma'}$. Per case, one master interval
`task_c` (mandatory iff $p_c=4$) tied via `alternative()` to one candidate interval per
eligible $(d,r)$, sized $t_c^{op}$ only. Room turnover (C7) becomes a `sequence_var` per
room-day with `no_overlap(seq, transition_matrix)`; surgeon non-overlap (C8) uses the
same idiom without a transition matrix, since a surgeon doesn't need "cleaning time"
between cases the way a room does. Equipment (C10) and beds (C11) use the same additive
`pulse`-sum pattern instead of one `Cumulative` call — mechanically equivalent here, but
the additive form is what would let a later baseline-usage term get added without
changing the constraint's shape.

### B.3 Status

A CP Optimizer engine (IBM CPLEX Optimization Studio Community Edition, `docplex`) was
available while building this, so the backend has been run and checked, not just
written against documentation. On the demo instance it returns the same objective as
CP-SAT (155.0, 20/20 scheduled) — expected, since the objective only depends on which
day a case lands on, not on intra-day timing, and both engines pick the same days here.
The turnover gaps in its returned schedule were checked directly: every same-service
gap between adjacent cases equals exactly 15 minutes, confirming the transition matrix
is actually binding rather than a no-op.

An honest limit of this demonstration: every room in `demo_instance()`/
`medium_instance()` is rostered to exactly one service per day (§10), so within any
room-day every candidate case is automatically the same service — the matrix's
cross-service branch (35 min) is correctly implemented but never actually exercised on
either shipped instance. It would engage the moment a room is rostered to more than one
service in a day.

### B.4 The honest comparison

| Solver | Status | Objective | Gap | Scheduled | Time |
|---|---|---|---|---|---|
| CP-SAT | Optimal | 155.0 | 0.00% | 20/20 | ~0.1s |
| CP Optimizer | Optimal | 155.0 | 0.00% | 20/20 | ~1.1s |

At the 200-case scale, CP Optimizer's own gap closes far more slowly than CP-SAT's at
the same time budget — likely a search-tuning difference (no custom search phase or
warm start was applied to it here) rather than a modeling one. The honest conclusion
this appendix supports is narrower than "CP Optimizer is better": it demonstrates that
*within* the CP paradigm, the choice of primitive still matters (a transition matrix is
a real answer to a real gap in the primary model's turnover assumption), while CP-SAT
remains the better-tuned, better-performing engine for this project at every scale
actually tested. That's why it's an appendix, not the model.
