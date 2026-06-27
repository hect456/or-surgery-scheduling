"""
penalty.py — Penalty weight computation w_c for the objective function.

  w_c = multiplier[p_c] * PenaltyFactor(dd_c)  +  1.2 * max_{c in C}(dd_c)

PenaltyFactor is a piecewise function of the REAL days-remaining-to-deadline
(dd_c, from PlanningInstance.days_to_deadline) — its breakpoints always mean
"this many real days overdue", for every priority. The priority multiplier
scales the curve's OUTPUT, applied once, here, and nowhere else.

Bug this fixes (previously): an earlier version computed
`PenaltyFactor(dd_c * mult)` — scaling the curve's INPUT by the priority
multiplier instead of its output — and every caller of compute_all_penalties
*also* multiplied the result by `case.priority.value` when building the
objective. That combination (a) double-counted priority (once via the
scaled curve input, once via the extra `priority.value` factor in every
solver's objective) and (b) could invert the intended ordering: scaling
`dd_c` by a large multiplier before a piecewise, saturating curve does not
preserve "more days overdue at the same priority is worse", because the
curve's breakpoints no longer refer to real elapsed days once the input is
pre-scaled per case. Fixed by (1) evaluating the curve on the unscaled
`dd_c` here, (2) applying `mult` once to the curve's output, and
(3) removing the redundant `priority.value *` factor from every solver's
objective (cp_sat_interval_solver.py, milp_baseline_solver.py,
hexaly_solver.py, greedy_solver.py) — `penalties[cid]` is now the complete,
final w_c.

The curve's shape (sharp escalation as the deadline is missed, then a
steep linear tail) is the standard way OR-scheduling models penalise
breaches of a clinical waiting-time target — see e.g. Marques & Captivo
(2015) for one concrete, evidence-based instantiation of this curve; the
breakpoints below are a generic default, not a universal law (see
FORMULATION.md's parameter-justification appendix for an honest discussion
of which constants here are literature-grounded vs. policy knobs).

The displacement term 1.2 * max(dd_c) guarantees the non-scheduling
penalty exceeds the scheduling-cost coefficient, so the model always
prefers to schedule a case over leaving it unscheduled whenever feasible.
It is deliberately NOT scaled by the priority multiplier: it only needs to
dominate Term-1/2 coefficients, which don't depend on priority, so an
unscaled, priority-independent displacement already does that for every
case, and scaling it would just be additional unjustified inflation.
"""

from __future__ import annotations
from typing import Dict, List

from .types import SurgicalCase, PlanningInstance


def penalty_factor_curve(days_to_deadline: int) -> float:
    """
    Piecewise PenaltyFactor, expressed in "priority-1-equivalent overdue
    days". Increases sharply as the deadline approaches and is breached.
    """
    d = days_to_deadline
    if d >= 90:
        return 50
    elif d >= 60:
        return 100
    elif d >= 45:
        return 200
    elif d >= 30:
        return 250
    elif d >= 15:
        return 550
    elif d >= 0:
        return 800
    elif d >= -15:
        return 1000
    elif d >= -30:
        return 1500
    elif d >= -45:
        return 2000
    else:
        return 2000 + 20 * abs(d + 45)


def compute_penalty(
    instance: PlanningInstance,
    case: SurgicalCase,
    max_days_to_deadline: float,
) -> float:
    """Compute w_c for case c under this instance's priority policy.

    w_c = mult * PenaltyFactor(dd_c_real) + displacement — see module
    docstring for why the multiplier is applied to the curve's output, not
    its input, and why this is the ONLY place the priority multiplier is
    applied (no solver should multiply penalties[cid] by anything priority-
    related again).
    """
    mult = instance.priority_multiplier[case.priority]
    dtd = instance.days_to_deadline(case)

    fp = penalty_factor_curve(int(round(dtd)))
    displacement = 1.2 * max_days_to_deadline
    return mult * fp + displacement


def compute_all_penalties(instance: PlanningInstance) -> Dict[str, float]:
    """Return {case_id: w_c} for every case in the instance."""
    cases = instance.cases
    if not cases:
        return {}
    max_dtd = max(instance.days_to_deadline(c) for c in cases)
    return {c.id: compute_penalty(instance, c, max_dtd) for c in cases}
