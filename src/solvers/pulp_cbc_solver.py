"""
pulp_cbc_solver.py — PuLP/CBC implementation of the MILP formulation.

This is the PRIMARY demo solver (no commercial licence required).
It mirrors the mathematical formulation exactly:
  - Decision variables  : x_{cdbr} ∈ {0,1}  and  z_c ≥ 0
  - Objective           : (5.12) three-term weighted sum
  - Constraints         : (5.1)–(5.9) as labelled in FORMULATION.md

Reference: Marques & Captivo (2015), Chapters 4–5; CHLN operational data.
"""

from __future__ import annotations
from typing import Dict, Tuple

import pulp

from ..model.types import (
    PlanningInstance, SurgicalCase, OperatingRoom,
    Assignment, SolverResult, Priority,
)
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class PuLPCBCSolver(BaseSolver):
    """
    Mixed-Integer Linear Programme solved with CBC via PuLP.

    Variables
    ---------
    x[c, d, r]  : binary — case c scheduled on day d in room r
    z[c]        : continuous ≥ 0 — 1 if case c is NOT scheduled
                  (takes value in {0,1} by force of constraint 5.3)

    Note: the formulation indexes rooms within blocks (b, r ∈ R_b).
    Here we flatten to (r) since each room belongs to exactly one block
    and the service-assignment constraint (5.4) already encodes the
    block membership implicitly.
    """

    name = "PuLP/CBC"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        prob = pulp.LpProblem("ElectiveSurgeryScheduling", pulp.LpMinimize)

        cases   = instance.cases
        rooms   = instance.rooms
        days    = instance.days
        alpha   = instance.alpha

        case_ids  = [c.id for c in cases]
        room_ids  = [r.id for r in rooms]
        case_map  = instance.cases_by_id
        room_map  = instance.rooms_by_id
        surg_map  = instance.surgeons_by_id

        penalties = compute_all_penalties(cases)

        # ── Build feasible (c, d, r) triples ────────────────────────────
        # Pre-filtering eliminates x_{cdbr} where a_{dbr}^{s_c} = 0
        # (constraint 5.4 renders them zero; removing them speeds up solve).
        feasible: set[Tuple[str, str, str]] = set()
        for c in cases:
            for d in instance.valid_days(c):
                for r in rooms:
                    if not instance.room_service_match(r, c, d):
                        continue
                    if r.ambulatory_only and c.scope.value != 2:
                        continue                              # constraint 5.5
                    if instance.is_paediatric_day(c, d):
                        continue                              # constraint 5.6
                    if not surg_map[c.surgeon_id].availability.get(d, True):
                        continue                              # surgeon absent
                    feasible.add((c.id, d, r.id))

        # ── Decision variables ───────────────────────────────────────────
        x: Dict[Tuple[str, str, str], pulp.LpVariable] = {}
        for (cid, d, rid) in feasible:
            x[cid, d, rid] = pulp.LpVariable(
                f"x_{cid}_{d}_{rid}", cat="Binary"
            )

        # z_c only for non-urgent cases (p_c ≠ 4); urgent must be scheduled
        z: Dict[str, pulp.LpVariable] = {}
        for c in cases:
            if c.priority != Priority.DEFERRED_URGENT:
                z[c.id] = pulp.LpVariable(f"z_{c.id}", lowBound=0)

        # ── Objective function (5.12) ────────────────────────────────────
        obj_terms = []
        for c in cases:
            dtd = c.days_to_deadline   # dd_c - d_1
            for d_idx, d in enumerate(instance.valid_days(c)):
                d_val = d_idx + 1      # numeric day value 1..5
                for r in rooms:
                    key = (c.id, d, r.id)
                    if key not in x:
                        continue
                    # Term 1 (on-time cases) or Term 2 (overdue cases, multiply d by α)
                    coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
                    obj_terms.append(coeff * x[key])

        # Term 3: penalty for non-scheduling
        for c in cases:
            if c.id in z:
                obj_terms.append(c.priority * penalties[c.id] * z[c.id])

        prob += pulp.lpSum(obj_terms), "Objective_5_12"

        # ── Constraint (5.1): one procedure per patient per week ─────────
        from collections import defaultdict
        patient_cases: Dict[str, list] = defaultdict(list)
        for c in cases:
            patient_cases[c.patient_id].append(c.id)

        for pid, cids in patient_cases.items():
            terms = [
                x[cid, d, rid]
                for (cid, d, rid) in feasible
                if cid in set(cids)
            ]
            if terms:
                prob += (pulp.lpSum(terms) <= 1, f"OnePerPatient_{pid}")

        # ── Constraint (5.2): priority-4 cases must be on day 1 ─────────
        for c in cases:
            if c.priority == Priority.DEFERRED_URGENT:
                d1 = days[0]
                terms_d1 = [x[cid, d, rid] for (cid, d, rid) in feasible
                             if cid == c.id and d == d1]
                if terms_d1:
                    prob += (pulp.lpSum(terms_d1) == 1, f"MustScheduleDay1_{c.id}")

        # ── Constraint (5.3): non-urgent cases: scheduled or penalised ───
        for c in cases:
            if c.priority != Priority.DEFERRED_URGENT:
                terms_all = [x[cid, d, rid] for (cid, d, rid) in feasible if cid == c.id]
                prob += (pulp.lpSum(terms_all) + z[c.id] == 1,
                         f"ScheduleOrPenalise_{c.id}")

        # ── Constraint (5.7): room capacity ─────────────────────────────
        for d in days:
            for r in rooms:
                cap = r.capacity_min.get(d, 0)
                terms = [
                    case_map[cid].t_tot * x[cid, d2, rid]
                    for (cid, d2, rid) in feasible
                    if d2 == d and rid == r.id
                ]
                if terms:
                    prob += (pulp.lpSum(terms) <= cap, f"RoomCap_{d}_{r.id}")

        # ── Constraint (5.8): surgeon daily limit ───────────────────────
        for s in instance.surgeons:
            for d in days:
                if not s.availability.get(d, True):
                    continue
                # Build term list explicitly to avoid generator scoping issues
                terms = []
                for (cid, d2, rid) in feasible:
                    if d2 == d and case_map[cid].surgeon_id == s.id:
                        terms.append(case_map[cid].t_cir * x[cid, d2, rid])
                if terms:
                    prob += (pulp.lpSum(terms) <= s.daily_limit_min, f"SurgDay_{s.id}_{d}")

        # ── Constraint (5.9): surgeon weekly limit ───────────────────────
        for s in instance.surgeons:
            terms = []
            for (cid, d, rid) in feasible:
                if case_map[cid].surgeon_id == s.id:
                    terms.append(case_map[cid].t_cir * x[cid, d, rid])
            if terms:
                prob += (pulp.lpSum(terms) <= s.weekly_limit_min, f"SurgWeek_{s.id}")

        # ── Solve ────────────────────────────────────────────────────────
        solver = pulp.PULP_CBC_CMD(
            msg=0,
            timeLimit=self.time_limit_sec,
            gapRel=self.mip_gap,
        )
        prob.solve(solver)

        # ── Extract results ──────────────────────────────────────────────
        status = pulp.LpStatus[prob.status]
        obj_val = pulp.value(prob.objective)

        assignments = []
        for (cid, d, rid), var in x.items():
            if pulp.value(var) is not None and pulp.value(var) > 0.5:
                assignments.append(Assignment(case_id=cid, day=d, room_id=rid))

        unscheduled = [
            cid for cid, var in z.items()
            if pulp.value(var) is not None and pulp.value(var) > 0.5
        ]

        return SolverResult(
            status=status,
            objective_value=obj_val,
            assignments=assignments,
            unscheduled_case_ids=unscheduled,
            solve_time_sec=0.0,          # filled by base class
            solver_name=self.name,
        )
