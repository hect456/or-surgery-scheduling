"""
cp_sat_interval_solver.py — Interval-Based Constraint Programming model,
solved with Google OR-Tools CP-SAT. This is the PRODUCTION formulation.

Why interval-based CP-SAT for production?
-------------------------------------------
The baseline MILP (milp_baseline_solver.py) reasons at day+room granularity:
it sums durations against a daily capacity bucket. That's an aggregate
relaxation — it cannot express "these two cases don't overlap in time" or
"this shared device is in use at this exact moment", only "their durations
fit in the day". CP-SAT's interval variables (start, size, end, optional
presence) plus AddNoOverlap / AddCumulative are the textbook tool for this
class of problem (job-shop / RCPSP-family disjunctive scheduling): they
give exact, branch-and-bound-free disjunctive reasoning with no big-M
constants, and CP-SAT's lazy-clause-generation search is the best-known
open-source approach for these problem shapes (Perron & Furnon, "CP-SAT: a
constraint programming solver", OR-Tools documentation; it is also the
backbone of many published RCPSP/scheduling benchmarks). That is the
concrete "how would this scale to production" answer this file gives.

How this maps onto the baseline (FORMULATION.md), element by element —
see PRODUCTION_FORMULATION.md for the full table:

  Baseline (MILP)                         Production (this file)
  --------------------------------------  -----------------------------------
  x_{cdr} in {0,1}                        presence_{cdr} in {0,1} + start_{cdr}
  (implicit, none)                        interval_{cdr} = [start, start+t_tot)
  C7 room capacity: sum t_tot*x <= k_dr   AddNoOverlap over intervals in (d,r)
  C8 surgeon daily sum <= limit           AddNoOverlap over intervals for (h,d)
                                           PLUS the same linear daily-sum bound
  C9 surgeon weekly sum <= limit          same linear weekly-sum bound (kept)
  C10 equipment day-count <= units        AddCumulative over real start/end,
                                           capacity = units (exact concurrency)
  (excluded in baseline)                  AddCumulative over downstream
                                           recovery/ICU beds (day-granularity)
  Objective (3-term tardiness+penalty)    identical, evaluated on presence_{cdr}

Everything else (priority EMERGENT_ADDON lock-in, schedule-or-penalise,
room-service eligibility, pediatric block, one-case-per-patient) is the
same constraint, just expressed over `presence` instead of `x`.
"""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, Tuple

from ortools.sat.python import cp_model

from ..model.types import PlanningInstance, Assignment, SolverResult, Priority
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class CPSATIntervalSolver(BaseSolver):
    """
    Interval-based CP-SAT production model.

    Variables (per feasible case/day/room slot, same eligibility filter as
    the baseline: room-service match, ambulatory-only, pediatric block,
    surgeon availability):
      presence[c,d,r] : bool — case c assigned to (d, r)
      start[c,d,r]    : int  — start time in minutes from room opening
      end[c,d,r]      : int  — end time (= start + t_tot when present)
      interval[c,d,r] : optional interval, present iff presence[c,d,r]

    unscheduled[c] : bool — case c not scheduled (non-emergent cases only)
    day_of[c]      : int  — day index of c's surgery (only built for cases
                     that consume a downstream recovery bed)
    """

    name = "CP-SAT/Interval"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        model = cp_model.CpModel()

        cases = instance.cases
        rooms = instance.rooms
        days = instance.days
        alpha = instance.alpha
        case_map = instance.cases_by_id
        surg_map = instance.surgeons_by_id
        penalties = compute_all_penalties(instance)
        day_index = {d: i for i, d in enumerate(days)}

        # ── Feasible (c, d, r) candidate slots — same filter as baseline ──
        candidates = []
        for c in cases:
            for d in instance.valid_days(c):
                for r in rooms:
                    if not instance.room_service_match(r, c, d):
                        continue
                    if r.ambulatory_only and c.scope.value != 2:
                        continue
                    if instance.violates_pediatric_block(c, d):
                        continue
                    if not surg_map[c.surgeon_id].availability.get(d, True):
                        continue
                    candidates.append((c.id, d, r.id))

        # ── Interval variables ───────────────────────────────────────────
        presence: Dict[Tuple[str, str, str], object] = {}
        start: Dict[Tuple[str, str, str], object] = {}
        end: Dict[Tuple[str, str, str], object] = {}
        interval: Dict[Tuple[str, str, str], object] = {}
        room_caps = {r.id: r.capacity_min for r in rooms}

        for (cid, d, rid) in candidates:
            c = case_map[cid]
            cap = room_caps[rid].get(d, 0)
            key = (cid, d, rid)
            presence[key] = model.NewBoolVar(f"pr_{cid}_{d}_{rid}")
            start[key] = model.NewIntVar(0, max(cap, 0), f"st_{cid}_{d}_{rid}")
            end[key] = model.NewIntVar(0, max(cap, 0), f"en_{cid}_{d}_{rid}")
            interval[key] = model.NewOptionalIntervalVar(
                start[key], c.t_tot, end[key], presence[key], f"iv_{cid}_{d}_{rid}"
            )

        # ── is_scheduled / unscheduled bookkeeping ───────────────────────
        is_scheduled: Dict[str, object] = {}
        unscheduled: Dict[str, object] = {}
        for c in cases:
            slots = [presence[k] for k in candidates if k[0] == c.id]
            if c.priority == Priority.EMERGENT_ADDON:
                d1 = days[0]
                d1_slots = [presence[(c.id, d, rid)] for (cid, d, rid) in candidates
                            if cid == c.id and d == d1]
                if d1_slots:
                    model.Add(sum(d1_slots) == 1)
                # also forbid any non-day-1 slot for this case
                other_slots = [presence[k] for k in candidates
                               if k[0] == c.id and k[1] != d1]
                for s in other_slots:
                    model.Add(s == 0)
                is_scheduled[c.id] = 1  # constant: always scheduled
            else:
                u = model.NewBoolVar(f"unsched_{c.id}")
                unscheduled[c.id] = u
                if slots:
                    model.Add(sum(slots) + u == 1)
                else:
                    model.Add(u == 1)
                sched = model.NewBoolVar(f"sched_{c.id}")
                model.Add(sched == 1 - u)
                is_scheduled[c.id] = sched

        # ── C1: at most one scheduled occurrence per patient per week ───
        patient_cases: Dict[str, list] = defaultdict(list)
        for c in cases:
            patient_cases[c.patient_id].append(c.id)
        for pid, cids in patient_cases.items():
            slots = [presence[k] for k in candidates if k[0] in set(cids)]
            if slots:
                model.Add(sum(slots) <= 1)

        # ── C7: room capacity via exact NoOverlap (replaces day-aggregate) ─
        by_room_day: Dict[Tuple[str, str], list] = defaultdict(list)
        for k in candidates:
            cid, d, rid = k
            by_room_day[d, rid].append(interval[k])
        for ivs in by_room_day.values():
            if len(ivs) > 1:
                model.AddNoOverlap(ivs)

        # ── C8: surgeon — exact NoOverlap (no double-booking) + daily cap ─
        by_surgeon_day: Dict[Tuple[str, str], list] = defaultdict(list)
        for k in candidates:
            cid, d, rid = k
            by_surgeon_day[case_map[cid].surgeon_id, d].append(interval[k])
        for ivs in by_surgeon_day.values():
            if len(ivs) > 1:
                model.AddNoOverlap(ivs)

        for s in instance.surgeons:
            for d in days:
                if not s.availability.get(d, True):
                    continue
                terms = [case_map[cid].t_cir * presence[(cid, d2, rid)]
                         for (cid, d2, rid) in candidates
                         if d2 == d and case_map[cid].surgeon_id == s.id]
                if terms:
                    model.Add(sum(terms) <= s.daily_limit_min)

        # ── C9: surgeon weekly time limit (unchanged from baseline) ──────
        for s in instance.surgeons:
            terms = [case_map[cid].t_cir * presence[(cid, d, rid)]
                     for (cid, d, rid) in candidates if case_map[cid].surgeon_id == s.id]
            if terms:
                model.Add(sum(terms) <= s.weekly_limit_min)

        # ── C10: shared equipment — exact AddCumulative (replaces day-count) ─
        if instance.has_equipment_limits():
            equip_ids = {e for (e, _d) in instance.equipment_capacity}
            for e in equip_ids:
                for d in days:
                    cap = instance.equipment_capacity.get((e, d))
                    if cap is None:
                        continue
                    ivs = [interval[k] for k in candidates
                           if k[1] == d and case_map[k[0]].equipment == e]
                    if ivs:
                        model.AddCumulative(ivs, [1] * len(ivs), cap)

        # ── New in production: downstream recovery/ICU bed AddCumulative ──
        # Day-granularity resource: a case occupies a bed from its surgery
        # day for `recovery_los_days` days. Excluded from the baseline (see
        # FORMULATION.md "what we exclude and why"); this is the concrete
        # extension path for it once the model is interval-based.
        if instance.has_bed_limits():
            self._add_recovery_bed_constraints(model, instance, candidates, presence, is_scheduled)

        # ── Objective: identical three-term formula, over `presence` ────
        objective_terms = []
        for c in cases:
            dtd = instance.days_to_deadline(c)
            for d_idx, d in enumerate(instance.valid_days(c)):
                d_val = d_idx + 1
                for r in rooms:
                    key = (c.id, d, r.id)
                    if key not in presence:
                        continue
                    coeff = (dtd + d_val) if dtd >= 0 else (dtd + alpha * d_val)
                    objective_terms.append(int(round(coeff)) * presence[key])
        for cid, u in unscheduled.items():
            c = case_map[cid]
            objective_terms.append(int(round(c.priority.value * penalties[cid])) * u)
        model.Minimize(sum(objective_terms))

        # ── Solve ─────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.time_limit_sec)
        solver.parameters.relative_gap_limit = self.mip_gap
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)

        status_map = {
            cp_model.OPTIMAL: "Optimal",
            cp_model.FEASIBLE: "Feasible",
            cp_model.INFEASIBLE: "Infeasible",
            cp_model.MODEL_INVALID: "ModelInvalid",
            cp_model.UNKNOWN: "Unknown",
        }
        status_str = status_map.get(status, "Unknown")

        assignments, unscheduled_ids = [], []
        obj_val = None
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            obj_val = solver.ObjectiveValue()
            for k in candidates:
                if solver.Value(presence[k]) == 1:
                    cid, d, rid = k
                    assignments.append(Assignment(
                        case_id=cid, day=d, room_id=rid,
                        start_min=solver.Value(start[k]),
                        end_min=solver.Value(end[k]),
                    ))
            for cid, u in unscheduled.items():
                if solver.Value(u) == 1:
                    unscheduled_ids.append(cid)

        gap = None
        if status == cp_model.FEASIBLE:   # OPTIMAL means gap is 0 by definition
            try:
                best = solver.BestObjectiveBound()
                if obj_val is not None and obj_val != 0:
                    gap = abs(obj_val - best) / max(abs(obj_val), 1e-9)
            except Exception:
                pass

        return SolverResult(
            status=status_str,
            objective_value=obj_val,
            assignments=assignments,
            unscheduled_case_ids=unscheduled_ids,
            solve_time_sec=0.0,   # filled by BaseSolver
            solver_name=self.name,
            gap=gap,
        )

    @staticmethod
    def _add_recovery_bed_constraints(model, instance, candidates, presence, is_scheduled):
        days = instance.days
        case_map = instance.cases_by_id
        n_days = len(days)

        beds_by_type: Dict[str, list] = defaultdict(list)
        for c in instance.cases:
            if not c.needs_recovery_bed:
                continue
            day_of = model.NewIntVar(0, n_days - 1, f"dayof_{c.id}")
            for (cid, d, rid) in candidates:
                if cid != c.id:
                    continue
                model.Add(day_of == instance.days.index(d)).OnlyEnforceIf(presence[(cid, d, rid)])

            sched = is_scheduled[c.id]
            bed_start = day_of
            bed_end = model.NewIntVar(0, n_days - 1 + c.recovery_los_days, f"bedend_{c.id}")
            model.Add(bed_end == bed_start + c.recovery_los_days)
            bed_iv = model.NewOptionalIntervalVar(
                bed_start, c.recovery_los_days, bed_end, sched, f"bed_{c.id}"
            ) if not isinstance(sched, int) else model.NewIntervalVar(
                bed_start, c.recovery_los_days, bed_end, f"bed_{c.id}"
            )
            beds_by_type[c.recovery_type].append(bed_iv)

        for rtype, ivs in beds_by_type.items():
            caps = [cap for (t, d), cap in instance.bed_capacity.items() if t == rtype]
            if not caps or not ivs:
                continue
            capacity = min(caps)  # constant-capacity assumption (see module docstring)
            model.AddCumulative(ivs, [1] * len(ivs), capacity)
