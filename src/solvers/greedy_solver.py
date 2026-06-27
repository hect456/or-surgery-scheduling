"""
greedy_solver.py — Priority-first greedy heuristic.

Purpose
-------
1. Provides a fast feasible solution for warm-starting/benchmarking the
   exact solvers.
2. Demonstrates that even a simple heuristic captures the core priority +
   antiquity logic without mathematical programming.
3. Gives an upper bound on the objective for gap reporting.

Algorithm
---------
1. Sort cases by (priority DESC, days_waiting DESC) — most urgent first.
2. For each case (in order), find the first (day, room) slot that:
   a. Has sufficient remaining room capacity.
   b. Matches the room-service roster.
   c. Respects surgeon daily/weekly limits and availability.
   d. Satisfies the pediatric-block rule and shared-equipment capacity.
3. Assign to that slot; update residual capacities.

Complexity: O(|C| * |D| * |R|) — negligible vs. any exact solver's time.
"""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, Tuple

from ..model.types import (
    PlanningInstance, Assignment, SolverResult, Priority,
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
        surg_map = instance.surgeons_by_id
        penalties = compute_all_penalties(instance)
        alpha    = instance.alpha

        # Residual capacities
        room_cap:  Dict[Tuple[str, str], int] = {}
        surg_day:  Dict[Tuple[str, str], int] = {}
        surg_week: Dict[str, int] = {}
        equip_day: Dict[Tuple[str, str], int] = dict(instance.equipment_capacity)

        for r in rooms:
            for d in days:
                room_cap[d, r.id] = r.capacity_min.get(d, 0)

        for s in instance.surgeons:
            surg_week[s.id] = s.weekly_limit_min
            for d in days:
                surg_day[s.id, d] = s.daily_limit_min

        # Sort: priority EMERGENT_ADDON first, then by days_waiting DESC
        sorted_cases = sorted(cases, key=lambda c: (-c.priority.value, -c.days_waiting))

        assignments = []
        scheduled_ids: set = set()
        scheduled_patients: set = set()
        day_index = {d: i for i, d in enumerate(days)}

        for c in sorted_cases:
            if c.patient_id in scheduled_patients:
                continue   # C1: one occurrence per patient per week

            assigned = False
            for d in instance.valid_days(c):
                for r in rooms:
                    if not instance.room_service_match(r, c, d):
                        continue
                    if r.ambulatory_only and c.scope.value != 2:
                        continue
                    if instance.violates_pediatric_block(c, d):
                        continue
                    s = surg_map[c.surgeon_id]
                    if not s.availability.get(d, True):
                        continue
                    if room_cap[d, r.id] < c.t_tot:
                        continue
                    if surg_day[s.id, d] < c.t_cir:
                        continue
                    if surg_week[s.id] < c.t_cir:
                        continue
                    if c.equipment is not None:
                        key = (c.equipment, d)
                        if equip_day.get(key, 1) < 1:
                            continue

                    # Assign!
                    assignments.append(Assignment(case_id=c.id, day=d, room_id=r.id))
                    scheduled_ids.add(c.id)
                    scheduled_patients.add(c.patient_id)
                    room_cap[d, r.id]  -= c.t_tot
                    surg_day[s.id, d]  -= c.t_cir
                    surg_week[s.id]    -= c.t_cir
                    if c.equipment is not None:
                        key = (c.equipment, d)
                        if key in equip_day:
                            equip_day[key] -= 1
                    assigned = True
                    break
                if assigned:
                    break

        unscheduled = [c.id for c in cases if c.id not in scheduled_ids]

        # Compute objective value (same formula as the exact solvers)
        case_map = instance.cases_by_id
        obj = 0.0
        for a in assignments:
            c   = case_map[a.case_id]
            dtd = instance.days_to_deadline(c)
            d_val = day_index[a.day] + 1
            coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
            obj += coeff

        for cid in unscheduled:
            c = case_map[cid]
            if c.priority != Priority.EMERGENT_ADDON:
                # penalties[cid] already includes the priority multiplier.
                obj += penalties[cid]

        return SolverResult(
            status="Feasible",
            objective_value=obj,
            assignments=assignments,
            unscheduled_case_ids=unscheduled,
            solve_time_sec=0.0,
            solver_name=self.name,
        )
