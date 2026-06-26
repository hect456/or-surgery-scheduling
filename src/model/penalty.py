"""
penalty.py — Penalty weight computation w_c for the objective function.

  w_c = PenaltyFactor(p_c, dd_c)  +  1.2 * max_{c in C}(dd_c)

The PenaltyFactor is a piecewise function of the days-remaining-to-deadline
(dd_c, from PlanningInstance.days_to_deadline), scaled by the instance's
priority multiplier. The curve's shape (sharp escalation as the deadline
is missed, then a steep linear tail) is the standard way OR-scheduling
models penalise breaches of a clinical waiting-time target — see e.g.
Marques & Captivo (2015) for one concrete, evidence-based instantiation
of this curve; the breakpoints below are a generic default, not a
universal law.

The displacement term 1.2 * max(dd_c) guarantees the non-scheduling
penalty exceeds the scheduling-cost coefficient, so the model always
prefers to schedule a case over leaving it unscheduled whenever feasible.
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
    """Compute w_c for case c under this instance's priority policy."""
    mult = instance.priority_multiplier[case.priority]
    dtd = instance.days_to_deadline(case)

    # Scale days-to-deadline by the priority multiplier so all priorities
    # share the same PenaltyFactor curve (e.g. 1 overdue day at priority 2
    # behaves like `mult` overdue days at priority 1).
    adjusted_days = dtd * mult

    fp = penalty_factor_curve(int(round(adjusted_days)))
    displacement = 1.2 * max_days_to_deadline
    return fp + displacement


def compute_all_penalties(instance: PlanningInstance) -> Dict[str, float]:
    """Return {case_id: w_c} for every case in the instance."""
    cases = instance.cases
    if not cases:
        return {}
    max_dtd = max(instance.days_to_deadline(c) for c in cases)
    return {c.id: compute_penalty(instance, c, max_dtd) for c in cases}
