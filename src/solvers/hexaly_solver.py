"""
hexaly_solver.py — Hexaly (formerly LocalSolver) backend.

What is Hexaly?
---------------
Hexaly (https://www.hexaly.com) is a commercial black-box optimisation engine
that combines mathematical programming, constraint programming, and local search.
It handles mixed-integer programmes natively but excels on large combinatorial
problems where MILP solvers struggle with branch-and-bound.

Why consider Hexaly for this problem?
--------------------------------------
At real CHLN scale (~130,000 binary variables after pre-filtering), Gurobi and
CPLEX reach near-optimal solutions in < 5 minutes.  But for a rolling-horizon
multi-week extension, or when ICU/bed downstream constraints are added, the
search space grows significantly.  Hexaly's local-search backbone can provide
good feasible solutions in seconds, then improve them gradually — making it
suitable for real-time rescheduling (intra-day disruptions).

Reference: Hexaly technical documentation; Vanhoucke et al. (2007) comparison
of MIP vs local search for OR scheduling.

Installation
------------
    pip install hexaly   # requires a Hexaly licence key
    export LS_LICENSE_PATH=/path/to/licence

Usage
-----
    python main.py --solver hexaly

Model translation
-----------------
The MILP model (x_{cdbr} binary, linear constraints) maps naturally to Hexaly's
set-based modelling:
  - Decision: a set S_r ⊆ C for each room r on each day (cases assigned to r,d).
  - Constraints: |S_r| bounded by room capacity sum; disjoint across rooms/days.
  - Objective: same weighted tardiness formula.

The set-partition formulation is more natural for Hexaly than the flat binary
x_{cdbr} encoding, and avoids the large sparse coefficient matrix that can slow
MILP solvers on infeasible sub-trees.
"""

from __future__ import annotations
from typing import Optional

from ..model.types import PlanningInstance, SolverResult, Assignment, Priority
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class HexalySolver(BaseSolver):
    """
    Hexaly backend for large-instance surgery scheduling.

    Falls back gracefully to PuLP/CBC if hexaly is not installed,
    so the codebase runs correctly in environments without a Hexaly licence.
    """

    name = "Hexaly"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        try:
            import hexaly.optimizer as hx
        except ImportError:
            return self._fallback(instance)

        return self._solve_with_hexaly(instance, hx)

    def _solve_with_hexaly(self, instance, hx) -> SolverResult:
        """
        Hexaly set-partition formulation.

        Variables
        ---------
        For each (day d, room r): a set S_{dr} ⊆ C of cases assigned to that slot.

        Constraints
        -----------
        1. Disjoint cover: each case appears in at most one S_{dr}.
        2. Priority-4: case c must be in some S_{d1, r} (Monday).
        3. Room capacity: sum_{c ∈ S_{dr}} t_c^tot ≤ k_{dbr}.
        4. Surgeon daily/weekly: sum over cases in surgeon h's sets.
        5. Service assignment: only cases with s_c = service(r) in S_{dr}.

        Objective
        ---------
        Same three-term formula as the MILP, evaluated on the assignment.
        """
        optimizer = hx.HexalyOptimizer()
        m = optimizer.model

        cases    = instance.cases
        rooms    = instance.rooms
        days     = instance.days
        case_map = instance.cases_by_id
        surg_map = instance.surgeons_by_id
        penalties = compute_all_penalties(cases)
        alpha    = instance.alpha
        day_index = {d: i+1 for i, d in enumerate(days)}

        n_cases = len(cases)
        case_idx = {c.id: i for i, c in enumerate(cases)}

        # ── Variables: sets of case indices ───────────────────────────
        # S[d][r_idx] = set of case indices assigned to (day d, room r)
        S = {}
        for d_idx, d in enumerate(days):
            for r_idx, r in enumerate(rooms):
                S[d_idx, r_idx] = m.set(n_cases)

        # ── Constraint: each case in at most one slot ──────────────────
        # (Also implements service-room assignment: add only eligible cases)
        for d_idx, d in enumerate(days):
            for r_idx, r in enumerate(rooms):
                eligible = [
                    case_idx[c.id] for c in cases
                    if instance.room_service_match(r, c, d)
                    and not (r.ambulatory_only and c.scope.value != 2)
                    and not instance.is_paediatric_day(c, d)
                    and surg_map[c.surgeon_id].availability.get(d, True)
                    and (not c.must_schedule_day1 or d == days[0])
                ]
                m.constraint(m.is_subset(S[d_idx, r_idx], m.set_of(eligible)))

        # Partition: case appears in at most one set
        all_sets = [S[k] for k in S]
        m.constraint(m.partition(*all_sets))

        # ── Constraint: room capacity ──────────────────────────────────
        t_tot_array = m.array([c.t_tot for c in cases])
        for d_idx, d in enumerate(days):
            for r_idx, r in enumerate(rooms):
                cap = r.capacity_min.get(d, 0)
                load = m.sum(S[d_idx, r_idx], lambda i: t_tot_array[i])
                m.constraint(load <= cap)

        # ── Constraint: priority-4 on day 1 ───────────────────────────
        d1_idx = 0
        for c in cases:
            if c.must_schedule_day1:
                ci = case_idx[c.id]
                in_d1 = m.or_(*[m.contains(S[d1_idx, r_idx], ci) for r_idx in range(len(rooms))])
                m.constraint(in_d1)

        # ── Constraint: surgeon limits ────────────────────────────────
        t_cir_array = m.array([c.t_cir for c in cases])
        surg_idx_map = {s.id: [case_idx[c.id] for c in cases if c.surgeon_id == s.id]
                        for s in instance.surgeons}

        for s in instance.surgeons:
            sc_indices = surg_idx_map[s.id]
            if not sc_indices:
                continue
            surg_set = m.set_of(sc_indices)
            # Weekly
            total_cir = m.sum(
                [m.sum(m.and_(S[d_idx, r_idx], surg_set), lambda i: t_cir_array[i])
                 for d_idx, d in enumerate(days)
                 for r_idx in range(len(rooms))]
            )
            m.constraint(total_cir <= s.weekly_limit_min)
            # Daily
            for d_idx, d in enumerate(days):
                if not s.availability.get(d, True):
                    continue
                day_cir = m.sum(
                    [m.sum(m.and_(S[d_idx, r_idx], surg_set), lambda i: t_cir_array[i])
                     for r_idx in range(len(rooms))]
                )
                m.constraint(day_cir <= s.daily_limit_min)

        # ── Objective ─────────────────────────────────────────────────
        obj_terms = []
        for d_idx, d in enumerate(days):
            d_val = day_index[d]
            for r_idx in range(len(rooms)):
                for c in cases:
                    ci = case_idx[c.id]
                    dtd = c.days_to_deadline
                    coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
                    in_slot = m.contains(S[d_idx, r_idx], ci)
                    obj_terms.append(coeff * in_slot)

        # Penalty term
        scheduled_mask = m.or_(*[m.contains(S[k], case_idx[c.id]) for k in S])
        for c in cases:
            if c.priority != Priority.DEFERRED_URGENT:
                ci = case_idx[c.id]
                not_scheduled = m.not_(m.or_(*[m.contains(S[k], ci) for k in S]))
                obj_terms.append(c.priority * penalties[c.id] * not_scheduled)

        m.minimize(m.sum(obj_terms))
        m.close()

        optimizer.param.time_limit = self.time_limit_sec
        optimizer.solve()

        # Extract solution
        assignments = []
        scheduled_ids = set()
        for d_idx, d in enumerate(days):
            for r_idx, r in enumerate(rooms):
                for ci in S[d_idx, r_idx].value:
                    cid = cases[ci].id
                    assignments.append(Assignment(case_id=cid, day=d, room_id=r.id))
                    scheduled_ids.add(cid)

        unscheduled = [c.id for c in cases if c.id not in scheduled_ids
                       and c.priority != Priority.DEFERRED_URGENT]

        obj_val = float(optimizer.solution.objective_value)

        return SolverResult(
            status="Feasible",
            objective_value=obj_val,
            assignments=assignments,
            unscheduled_case_ids=unscheduled,
            solve_time_sec=0.0,
            solver_name=self.name,
        )

    def _fallback(self, instance: PlanningInstance) -> SolverResult:
        """Graceful fallback when Hexaly is not installed."""
        print(
            "  [HexalySolver] hexaly not installed (pip install hexaly + licence).\n"
            "  Falling back to PuLP/CBC."
        )
        from .pulp_cbc_solver import PuLPCBCSolver
        fallback = PuLPCBCSolver(time_limit_sec=self.time_limit_sec, mip_gap=self.mip_gap)
        fallback.name = "Hexaly→PuLP/CBC (fallback)"
        return fallback._build_and_solve(instance)
