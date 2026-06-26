"""
greedy_solver.py — Priority-first greedy heuristic.

Purpose
-------
1. Provides a fast feasible solution for warm-starting the MILP solvers.
2. Demonstrates that even a simple heuristic captures the core SIGIC
   logic (priority + antiquity) without mathematical programming.
3. Gives an upper bound on the objective for gap reporting.

Algorithm
---------
1. Sort cases by (priority DESC, days_waiting DESC) — most urgent first.
2. For each case (in order), find the first (day, room) slot that:
   a. Has sufficient remaining capacity.
   b. Matches service assignment (MSS).
   c. Respects surgeon daily/weekly limits.
   d. Satisfies special rules (5.2, 5.5, 5.6).
3. Assign to that slot; update residual capacities.

Complexity: O(|C| · |D| · |R|) — negligible vs. MILP solve time.
"""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, Tuple

from ..model.types import (
    PlanningInstance, SurgicalCase, Assignment, SolverResult, Priority,
)
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class GreedySolver(BaseSolver):
    """Fast constructive heuristic — no solver required."""

    name = "Greedy"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        cases    = instance.cases
        rooms    = instance.rooms
        days     = instance.days
        case_map = instance.cases_by_id
        surg_map = instance.surgeons_by_id
        penalties = compute_all_penalties(cases)
        alpha    = instance.alpha

        # Residual capacities
        room_cap:  Dict[Tuple[str, str], int] = {}
        surg_day:  Dict[Tuple[str, str], int] = {}
        surg_week: Dict[str, int] = {}

        for r in rooms:
            for d in days:
                room_cap[d, r.id] = r.capacity_min.get(d, 0)

        for s in instance.surgeons:
            surg_week[s.id] = s.weekly_limit_min
            for d in days:
                surg_day[s.id, d] = s.daily_limit_min

        # Sort: priority-4 first, then by days_waiting DESC within priority
        sorted_cases = sorted(
            cases,
            key=lambda c: (-c.priority.value, -c.days_waiting),
        )

        assignments = []
        scheduled_ids: set = set()
        # Track one surgery per patient
        scheduled_patients: set = set()

        day_index = {d: i for i, d in enumerate(days)}

        for c in sorted_cases:
            if c.patient_id in scheduled_patients:
                continue   # constraint 5.1

            assigned = False
            for d in instance.valid_days(c):
                for r in rooms:
                    # Service match (5.4)
                    if not instance.room_service_match(r, c, d):
                        continue
                    # Ambulatory only (5.5)
                    if r.ambulatory_only and c.scope.value != 2:
                        continue
                    # Paediatric circuit (5.6)
                    if instance.is_paediatric_day(c, d):
                        continue
                    # Surgeon availability
                    s = surg_map[c.surgeon_id]
                    if not s.availability.get(d, True):
                        continue
                    # Room capacity (5.7)
                    if room_cap[d, r.id] < c.t_tot:
                        continue
                    # Surgeon daily limit (5.8)
                    if surg_day[s.id, d] < c.t_cir:
                        continue
                    # Surgeon weekly limit (5.9)
                    if surg_week[s.id] < c.t_cir:
                        continue

                    # Assign!
                    assignments.append(Assignment(case_id=c.id, day=d, room_id=r.id))
                    scheduled_ids.add(c.id)
                    scheduled_patients.add(c.patient_id)
                    room_cap[d, r.id]  -= c.t_tot
                    surg_day[s.id, d]  -= c.t_cir
                    surg_week[s.id]    -= c.t_cir
                    assigned = True
                    break
                if assigned:
                    break

        unscheduled = [c.id for c in cases if c.id not in scheduled_ids]

        # Compute objective value (same formula as MILP)
        obj = 0.0
        for a in assignments:
            c   = case_map[a.case_id]
            dtd = c.days_to_deadline
            d_val = day_index[a.day] + 1
            coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
            obj += coeff

        for cid in unscheduled:
            c = case_map[cid]
            if c.priority != Priority.DEFERRED_URGENT:
                obj += c.priority.value * penalties[cid]

        return SolverResult(
            status="Feasible",
            objective_value=obj,
            assignments=assignments,
            unscheduled_case_ids=unscheduled,
            solve_time_sec=0.0,
            solver_name=self.name,
        )
