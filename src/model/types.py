"""
types.py — Core data structures for the Elective Surgery Scheduling problem.

Based on the CHLN formulation (Marques & Captivo, 2015) and adapted for the
generic OR scheduling context requested by the interview problem.

Design decision: plain dataclasses (no ORM, no external deps) so the model
layer is solver-agnostic and testable in isolation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────

class Priority(IntEnum):
    """
    SIGIC clinical priority levels (SNS Portugal).
    Lower numeric = less urgent from a scheduling perspective
    (but higher weight in the objective when the deadline is missed).
    """
    NORMAL            = 1   # wl_max = 270 days
    PRIORITY          = 2   # wl_max = 60  days
    VERY_PRIORITY     = 3   # wl_max = 15  days
    DEFERRED_URGENT   = 4   # wl_max = 3   days  → must schedule on day 1


class SurgeryScope(IntEnum):
    CONVENTIONAL = 1   # inpatient overnight
    AMBULATORY   = 2   # day-case, same-day discharge


# ──────────────────────────────────────────────────────────────
# Parameters (read-only after construction)
# ──────────────────────────────────────────────────────────────

# Maximum waiting days per priority (SIGIC Portaria n.º 45/2008)
MAX_WAIT_DAYS: Dict[Priority, int] = {
    Priority.NORMAL:          270,
    Priority.PRIORITY:         60,
    Priority.VERY_PRIORITY:    15,
    Priority.DEFERRED_URGENT:   3,
}

# Relative penalty multipliers (Tabela 5.1, Marques & Captivo 2015)
# Interpretation: 1 day overdue in priority p ≡ MULTIPLIER[p] days overdue in priority 1.
PRIORITY_MULTIPLIER: Dict[Priority, float] = {
    Priority.NORMAL:         1.0,
    Priority.PRIORITY:       4.5,
    Priority.VERY_PRIORITY: 18.0,
    Priority.DEFERRED_URGENT: 90.0,
}

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]   # D = {1..5}


# ──────────────────────────────────────────────────────────────
# Core entities
# ──────────────────────────────────────────────────────────────

@dataclass
class Surgeon:
    """
    h ∈ H.  A surgeon is identified by ID and constrained by daily/weekly
    operative time limits (k_{hd}^{dia} and k_h^{sem} in the formulation).

    k_{hd}^{dia} = min(surgeon daily limit, max room capacity that day)
    — the smaller of the two prevents scheduling the same surgeon in two
    rooms simultaneously (Marques & Captivo constraint 5.8 rationale).
    """
    id: str
    name: str
    service: str                          # s_c — surgical service
    daily_limit_min: int   = 240          # k_{hd}^{dia} (minutes)
    weekly_limit_min: int  = 960          # k_h^{sem}   (minutes)
    # availability[day] = True if surgeon available that day
    availability: Dict[str, bool] = field(default_factory=lambda: {d: True for d in DAYS})


@dataclass
class OperatingRoom:
    """
    r ∈ R_b for block b ∈ B.
    k_{dbr} = capacity in minutes on day d.
    service_assignment[day] = service code that owns the room that day (from MSS).
    Only ambulatory-capable rooms may host ambulatory cases.
    """
    id: str
    block: str                        # b ∈ B
    service_assignment: Dict[str, str]   # day → service code ("" = unassigned)
    capacity_min: Dict[str, int]         # day → minutes available
    ambulatory_only: bool = False        # Bloco Ambulatório de Urologia rule (5.5)


@dataclass
class SurgicalCase:
    """
    c ∈ C — one patient-surgery pair on the waiting list (LIC).

    Key parameters from the formulation:
      t_c^{cir}  = operative time (surgeon presence required)
      t_c^{lim}  = cleaning/turnover time after case
      t_c^{tot}  = t_c^{cir} + t_c^{lim}  (room occupation time)
      dd_c       = deadline = wl_c^{dia} + wl_c^{max}
                   negative → already overdue on planning day d_1
    """
    id: str
    patient_id: str
    service: str
    surgeon_id: str
    priority: Priority
    scope: SurgeryScope
    patient_age: int                  # relevant for ORL paediatric circuit (5.6)

    # Time parameters (minutes)
    t_cir: int                        # t_c^{cir}: operative duration
    t_clean: int = 20                 # t_c^{lim}: room cleaning time

    # Waiting-list entry (days before planning horizon d_1, positive = already waiting)
    days_waiting: int = 0

    def __post_init__(self):
        wl_max = MAX_WAIT_DAYS[self.priority]
        # dd_c - d_1: positive → days remaining before deadline
        #             negative → already overdue
        self.days_to_deadline: int = wl_max - self.days_waiting

    @property
    def t_tot(self) -> int:
        """Total room occupation: t_c^{cir} + t_c^{lim}."""
        return self.t_cir + self.t_clean

    @property
    def is_overdue(self) -> bool:
        return self.days_to_deadline < 0

    @property
    def must_schedule_day1(self) -> bool:
        """Priority 4 must be scheduled on the first planning day."""
        return self.priority == Priority.DEFERRED_URGENT


@dataclass
class PlanningInstance:
    """
    Complete problem instance: all sets and parameters needed by any solver.
    Mirrors the mathematical sets C, D, B, R_b, S, N, H from Chapter 5.
    """
    name: str
    cases: List[SurgicalCase]
    surgeons: List[Surgeon]
    rooms: List[OperatingRoom]
    days: List[str] = field(default_factory=lambda: list(DAYS))

    # Special rules (can be overridden per instance)
    paediatric_age_limit: int = 8      # ORL Friday paediatric circuit (5.6)
    paediatric_service: str = "ORL"
    paediatric_day: str = "Fri"

    alpha: float = 2.0                 # α > 1: urgency multiplier for overdue cases

    def __post_init__(self):
        self._validate()

    def _validate(self):
        surgeon_ids = {s.id for s in self.surgeons}
        for c in self.cases:
            assert c.surgeon_id in surgeon_ids, \
                f"Case {c.id}: unknown surgeon {c.surgeon_id}"
        assert self.alpha > 1.0, "α must be > 1"

    # ── Convenience lookups ──────────────────────
    @property
    def cases_by_id(self) -> Dict[str, SurgicalCase]:
        return {c.id: c for c in self.cases}

    @property
    def surgeons_by_id(self) -> Dict[str, Surgeon]:
        return {s.id: s for s in self.surgeons}

    @property
    def rooms_by_id(self) -> Dict[str, OperatingRoom]:
        return {r.id: r for r in self.rooms}

    def valid_days(self, case: SurgicalCase) -> List[str]:
        """D_c: days on which case c may be scheduled."""
        if case.must_schedule_day1:
            return [self.days[0]]
        return list(self.days)

    def room_service_match(self, room: OperatingRoom, case: SurgicalCase, day: str) -> bool:
        """a_{dbr}^s: True if room r is assigned to the service of case c on day d."""
        svc = room.service_assignment.get(day, "")
        return svc == case.service

    def is_paediatric_day(self, case: SurgicalCase, day: str) -> bool:
        """Rule 5.6: on the paediatric day, only young patients may use ORL rooms."""
        return (
            day == self.paediatric_day
            and case.service == self.paediatric_service
            and case.patient_age > self.paediatric_age_limit
        )


# ──────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────

@dataclass
class Assignment:
    """A scheduled surgery: case c → day d, room r."""
    case_id: str
    day: str
    room_id: str


@dataclass
class SolverResult:
    status: str                              # "Optimal", "Feasible", "Infeasible", etc.
    objective_value: Optional[float]
    assignments: List[Assignment]
    unscheduled_case_ids: List[str]
    solve_time_sec: float
    solver_name: str
    gap: Optional[float] = None              # MIP gap (if available)

    def is_optimal(self) -> bool:
        return self.status.lower() in {"optimal", "feasible"}
