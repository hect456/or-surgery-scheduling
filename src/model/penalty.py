"""
penalty.py — Penalty weight computation w_c for the objective function.

From Marques & Captivo (2015), Section 5.1 and Figure 5.1:

  w_c = PenaltyFactor(p_c, dd_c - d_1)  +  1.2 · max_{c∈C}(dd_c - d_1)

The PenaltyFactor is a piecewise function of the days-remaining-to-deadline,
scaled by the priority multiplier from Table 5.1.

The second term guarantees that the penalty for NOT scheduling any case
exceeds the scheduling-cost coefficient (ensuring the model prefers to
schedule rather than leave cases unscheduled whenever feasible).
"""

from __future__ import annotations
from typing import Dict, List
import math

from .types import SurgicalCase, Priority, PRIORITY_MULTIPLIER


def penalty_factor_priority1(days_to_deadline: int) -> float:
    """
    Piecewise PenaltyFactor for Priority-1 cases (Figure 5.1, Marques & Captivo).

    Shape: increases sharply as deadline approaches and beyond.
    The negative domain covers already-overdue cases (dd_c - d_1 < 0).

    This is the BASE curve; other priorities are obtained by multiplying
    the adjusted days by the PRIORITY_MULTIPLIER (Table 5.1).
    """
    d = days_to_deadline
    # Breakpoints from Figure 5.1 (reproduced from thesis)
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
        # Very overdue: linear extrapolation
        return 2000 + 20 * abs(d + 45)


def compute_penalty(case: SurgicalCase, max_days_to_deadline: float) -> float:
    """
    Compute w_c for case c.

    Parameters
    ----------
    case                : the surgical case
    max_days_to_deadline: max_{c'∈C}(dd_{c'} - d_1) — needed for the
                          displacement term 1.2 · max(...)
    """
    mult = PRIORITY_MULTIPLIER[case.priority]

    # Scale the days-to-deadline by the priority multiplier so that
    # priorities 2–4 use the same PenaltyFactor curve as priority 1.
    # Example: 1 overdue day for P2 ≡ 4.5 overdue days for P1.
    adjusted_days = case.days_to_deadline * mult   # keeps sign

    fp = penalty_factor_priority1(int(round(adjusted_days)))

    # Displacement term: guarantees penalty > scheduling cost
    displacement = 1.2 * max_days_to_deadline

    return fp + displacement


def compute_all_penalties(cases: List[SurgicalCase]) -> Dict[str, float]:
    """Return {case_id: w_c} for all cases in the instance."""
    if not cases:
        return {}
    max_dtd = max(c.days_to_deadline for c in cases)
    return {c.id: compute_penalty(c, max_dtd) for c in cases}
