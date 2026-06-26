"""
hexaly_solver.py — Hexaly backend (set-partition formulation of the
baseline model).

What is Hexaly, and why include it?
------------------------------------
Hexaly (https://www.hexaly.com, formerly LocalSolver) is a commercial
optimisation engine combining mathematical programming with a local-search
core. For combinatorial assignment problems like this one, it is often
able to produce strong feasible solutions on large instances faster than
branch-and-bound MILP, at the cost of not proving optimality the way CBC/
Gurobi/CP-SAT can on small-to-medium instances. We include it here as the
third point in the trade-off triangle this repo is built to demonstrate:

    OR-Tools MILP (CBC/Gurobi)  — exact, baseline, day-granularity
    OR-Tools CP-SAT (interval)  — exact, production, time-granularity
    Hexaly (local search)       — anytime, scales past exact-method limits

See RESULTS.md for where each one wins on the demo vs. medium instance.

Installation / academic licence
--------------------------------
    pip install hexaly
    # then register for a (free) academic licence at https://www.hexaly.com/
    # and either drop the licence file where Hexaly expects it, or:
    export HEXALY_LICENSE=/path/to/license.dat        (Linux/Mac)
    $env:HEXALY_LICENSE = "C:\\path\\to\\license.dat"  (PowerShell)

No licence is installed in the environment this repo was built in — the
class below is written against the real Hexaly API (not a placeholder),
but falls back to the OR-Tools MILP baseline with a clear message if the
package or licence is unavailable, so the rest of the demo keeps working.

Model
-----
Decision: for every (day d, room r), a set S_{dr} subseteq C of the cases
assigned to that slot — Hexaly's set-based modelling is a more natural fit
for this "bin assignment" shape than the flat binary x_{cdr} encoding, and
keeps the formulation's spirit (FORMULATION.md) without a sparse big
coefficient matrix.
"""

from __future__ import annotations
from typing import Dict, Tuple

from ..model.types import PlanningInstance, SolverResult, Assignment, Priority
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class HexalySolver(BaseSolver):
    """
    Hexaly backend. Falls back to the OR-Tools MILP baseline if `hexaly`
    is not importable or no licence is configured, so the codebase keeps
    running end to end in environments without a Hexaly licence.
    """

    name = "Hexaly"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        try:
            import hexaly.optimizer as hxopt
        except ImportError:
            return self._fallback(instance, reason="package 'hexaly' not installed")

        try:
            return self._solve_with_hexaly(instance, hxopt)
        except Exception as exc:
            # Typically a licence error (e.g. no HEXALY_LICENSE configured).
            return self._fallback(instance, reason=f"{type(exc).__name__}: {exc}")

    def _solve_with_hexaly(self, instance: PlanningInstance, hxopt) -> SolverResult:
        with hxopt.HexalyOptimizer() as optimizer:
            m = optimizer.model

            cases = instance.cases
            rooms = instance.rooms
            days = instance.days
            case_map = instance.cases_by_id
            surg_map = instance.surgeons_by_id
            penalties = compute_all_penalties(instance)
            alpha = instance.alpha

            n_cases = len(cases)
            case_idx = {c.id: i for i, c in enumerate(cases)}

            # ── Variables: S[d,r] = set of case indices in that slot ──────
            S = {}
            for d_idx, d in enumerate(days):
                for r_idx, r in enumerate(rooms):
                    S[d_idx, r_idx] = m.set(n_cases)

            # ── Eligibility per slot (mirrors the baseline's feasible set) ─
            eligible_idx: Dict[Tuple[int, int], list] = {}
            for d_idx, d in enumerate(days):
                for r_idx, r in enumerate(rooms):
                    elig = [
                        case_idx[c.id] for c in cases
                        if instance.room_service_match(r, c, d)
                        and not (r.ambulatory_only and c.scope.value != 2)
                        and not instance.violates_pediatric_block(c, d)
                        and surg_map[c.surgeon_id].availability.get(d, True)
                        and (not c.must_schedule_day1 or d == days[0])
                    ]
                    eligible_idx[d_idx, r_idx] = elig
                    m.constraint(m.is_subset(S[d_idx, r_idx], m.set_of(*elig) if elig else m.set_of()))

            # ── Partition: each case appears in at most one slot ──────────
            all_sets = list(S.values())
            m.constraint(m.disjoint(*all_sets) if hasattr(m, "disjoint")
                         else m.partition(*all_sets))

            # ── C7: room capacity ─────────────────────────────────────────
            t_tot_array = m.array([c.t_tot for c in cases])
            for d_idx, d in enumerate(days):
                for r_idx, r in enumerate(rooms):
                    cap = r.capacity_min.get(d, 0)
                    load = m.sum(S[d_idx, r_idx], lambda i: t_tot_array[i])
                    m.constraint(load <= cap)

            # ── C2: priority EMERGENT_ADDON must be in some Monday slot ───
            d1_idx = 0
            for c in cases:
                if c.must_schedule_day1:
                    ci = case_idx[c.id]
                    in_d1 = m.or_(*[m.contains(S[d1_idx, r_idx], ci)
                                    for r_idx in range(len(rooms))])
                    m.constraint(in_d1)

            # ── C8/C9: surgeon daily + weekly limits ───────────────────────
            t_cir_array = m.array([c.t_cir for c in cases])
            for s in instance.surgeons:
                sc_indices = [case_idx[c.id] for c in cases if c.surgeon_id == s.id]
                if not sc_indices:
                    continue
                surg_set = m.set_of(*sc_indices)

                total_cir = m.sum(
                    m.sum(m.and_(S[d_idx, r_idx], surg_set), lambda i: t_cir_array[i])
                    for d_idx in range(len(days)) for r_idx in range(len(rooms))
                )
                m.constraint(total_cir <= s.weekly_limit_min)

                for d_idx, d in enumerate(days):
                    if not s.availability.get(d, True):
                        continue
                    day_cir = m.sum(
                        m.sum(m.and_(S[d_idx, r_idx], surg_set), lambda i: t_cir_array[i])
                        for r_idx in range(len(rooms))
                    )
                    m.constraint(day_cir <= s.daily_limit_min)

            # ── C10: shared equipment, day-level aggregate (as baseline) ──
            if instance.has_equipment_limits():
                equip_ids = {e for (e, _d) in instance.equipment_capacity}
                for e in equip_ids:
                    equip_indices = [case_idx[c.id] for c in cases if c.equipment == e]
                    if not equip_indices:
                        continue
                    equip_set = m.set_of(*equip_indices)
                    for d_idx, d in enumerate(days):
                        cap = instance.equipment_capacity.get((e, d))
                        if cap is None:
                            continue
                        count = m.sum(
                            m.count(m.and_(S[d_idx, r_idx], equip_set))
                            for r_idx in range(len(rooms))
                        )
                        m.constraint(count <= cap)

            # ── Objective: same three-term formula ─────────────────────────
            day_index = {d: i + 1 for i, d in enumerate(days)}
            obj_terms = []
            for d_idx, d in enumerate(days):
                d_val = day_index[d]
                for r_idx in range(len(rooms)):
                    for c in cases:
                        ci = case_idx[c.id]
                        dtd = instance.days_to_deadline(c)
                        coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
                        obj_terms.append(coeff * m.contains(S[d_idx, r_idx], ci))

            scheduled_indicator = {}
            for c in cases:
                if c.priority != Priority.EMERGENT_ADDON:
                    ci = case_idx[c.id]
                    any_slot = m.or_(*[m.contains(S[k], ci) for k in S])
                    not_scheduled = m.not_(any_slot)
                    scheduled_indicator[c.id] = not_scheduled
                    obj_terms.append(c.priority.value * penalties[c.id] * not_scheduled)

            m.minimize(m.sum(obj_terms))
            m.close()

            optimizer.param.time_limit = self.time_limit_sec
            optimizer.solve()

            assignments, scheduled_ids = [], set()
            for d_idx, d in enumerate(days):
                for r_idx, r in enumerate(rooms):
                    for ci in S[d_idx, r_idx].value:
                        cid = cases[ci].id
                        assignments.append(Assignment(case_id=cid, day=d, room_id=r.id))
                        scheduled_ids.add(cid)

            unscheduled = [c.id for c in cases
                           if c.id not in scheduled_ids and c.priority != Priority.EMERGENT_ADDON]

            obj_val = float(optimizer.solution.objective_value)

            return SolverResult(
                status="Feasible",
                objective_value=obj_val,
                assignments=assignments,
                unscheduled_case_ids=unscheduled,
                solve_time_sec=0.0,
                solver_name=self.name,
            )

    def _fallback(self, instance: PlanningInstance, reason: str) -> SolverResult:
        print(
            f"  [HexalySolver] unavailable ({reason}).\n"
            f"  Install with `pip install hexaly` and configure an academic\n"
            f"  licence (see module docstring) to run this backend for real.\n"
            f"  Falling back to the OR-Tools/CBC baseline."
        )
        from .milp_baseline_solver import MILPBaselineSolver
        fallback = MILPBaselineSolver(backend="CBC", time_limit_sec=self.time_limit_sec,
                                       mip_gap=self.mip_gap)
        result = fallback._build_and_solve(instance)
        result.solver_name = "Hexaly -> OR-Tools/CBC (fallback)"
        return result
