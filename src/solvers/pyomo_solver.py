"""
pyomo_solver.py — Pyomo implementation supporting CBC, GLPK, CPLEX, and Gurobi.

Why Pyomo?
----------
Pyomo provides a solver-agnostic algebraic modelling layer.  The same
ConcreteModel compiles to any solver executable via a string flag.
This lets us demonstrate the identical formulation on:
  - CBC  (open-source, always available)
  - GLPK (open-source, fast for medium instances)
  - Gurobi / CPLEX (commercial, best performance at scale)
  - HiGHS (via highspy, free, state-of-the-art open solver)

The model structure mirrors FORMULATION.md exactly, with Pyomo Set /
Param / Var / Constraint objects named after the mathematical notation.
"""

from __future__ import annotations
import math
from typing import Optional

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from ..model.types import (
    PlanningInstance, Assignment, SolverResult, Priority,
)
from ..model.penalty import compute_all_penalties
from .base_solver import BaseSolver


class PyomoSolver(BaseSolver):
    """
    Pyomo MILP solver.  Specify backend via solver_name parameter.

    Supported solver_name values:
        "cbc"    — CBC via command-line (requires coinor-cbc)
        "glpk"   — GLPK (requires glpk)
        "gurobi" — Gurobi (requires licence + gurobipy)
        "cplex"  — CPLEX (requires licence)
        "highs"  — HiGHS (requires highspy)
    """

    def __init__(
        self,
        backend: str = "cbc",
        time_limit_sec: int = 120,
        mip_gap: float = 0.01,
    ):
        super().__init__(time_limit_sec, mip_gap)
        self.backend = backend
        self.name = f"Pyomo/{backend.upper()}"

    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        m = self._build_model(instance)
        results = self._call_solver(m)
        return self._extract_results(m, instance, results)

    # ──────────────────────────────────────────────────────────────────
    # Model construction
    # ──────────────────────────────────────────────────────────────────

    def _build_model(self, instance: PlanningInstance) -> pyo.ConcreteModel:
        m = pyo.ConcreteModel(name="ElectiveSurgeryScheduling")

        cases    = instance.cases
        rooms    = instance.rooms
        days     = instance.days
        alpha    = instance.alpha
        case_map = instance.cases_by_id
        surg_map = instance.surgeons_by_id
        penalties = compute_all_penalties(cases)

        # ── Sets ──────────────────────────────────────────────────────
        m.C = pyo.Set(initialize=[c.id for c in cases],   doc="Surgical cases")
        m.D = pyo.Set(initialize=days,                     doc="Planning days")
        m.R = pyo.Set(initialize=[r.id for r in rooms],   doc="Operating rooms")
        m.H = pyo.Set(initialize=[s.id for s in instance.surgeons], doc="Surgeons")

        # ── Feasible triples (c,d,r) ─────────────────────────────────
        # Pre-filtering mirrors removal of zero-coefficients in (5.4)
        feasible = []
        for c in cases:
            for d in instance.valid_days(c):
                for r in rooms:
                    if not instance.room_service_match(r, c, d):
                        continue
                    if r.ambulatory_only and c.scope.value != 2:
                        continue
                    if instance.is_paediatric_day(c, d):
                        continue
                    if not surg_map[c.surgeon_id].availability.get(d, True):
                        continue
                    feasible.append((c.id, d, r.id))

        m.CDR = pyo.Set(initialize=feasible, within=m.C * m.D * m.R,
                        doc="Feasible (case, day, room) triples")

        # ── Parameters ───────────────────────────────────────────────
        m.t_tot    = pyo.Param(m.C, initialize={c.id: c.t_tot   for c in cases}, doc="t_c^tot")
        m.t_cir    = pyo.Param(m.C, initialize={c.id: c.t_cir   for c in cases}, doc="t_c^cir")
        m.priority = pyo.Param(m.C, initialize={c.id: c.priority.value for c in cases})
        m.penalty  = pyo.Param(m.C, initialize=penalties)
        m.dd       = pyo.Param(m.C, initialize={c.id: c.days_to_deadline for c in cases},
                               doc="dd_c - d_1 (positive=on-time, negative=overdue)")
        m.alpha    = pyo.Param(initialize=alpha, doc="Urgency multiplier for overdue cases")

        m.cap  = pyo.Param(m.D, m.R,
                            initialize={(d, r.id): r.capacity_min.get(d, 0)
                                        for d in days for r in rooms},
                            doc="k_{dbr}: room capacity in minutes")

        m.klim_day  = pyo.Param(m.H, m.D,
                                  initialize={(s.id, d): s.daily_limit_min
                                              for s in instance.surgeons for d in days},
                                  doc="k_{hd}^{dia}")
        m.klim_week = pyo.Param(m.H,
                                  initialize={s.id: s.weekly_limit_min
                                              for s in instance.surgeons},
                                  doc="k_h^{sem}")

        m.surgeon_of = pyo.Param(m.C,
                                   initialize={c.id: c.surgeon_id for c in cases},
                                   within=m.H)
        m.patient_of = pyo.Param(m.C,
                                   initialize={c.id: c.patient_id for c in cases},
                                   within=pyo.Any)

        # ── Variables ─────────────────────────────────────────────────
        m.x = pyo.Var(m.CDR, domain=pyo.Binary,
                      doc="x_{cdbr}: 1 if case c scheduled on day d in room r")
        m.z = pyo.Var(m.C, domain=pyo.NonNegativeReals,
                      doc="z_c: 1 if case c is NOT scheduled (auxiliary)")

        # ── Objective (5.12) ──────────────────────────────────────────
        day_index = {d: i+1 for i, d in enumerate(days)}

        def obj_rule(m):
            terms = []
            for (cid, d, rid) in m.CDR:
                dtd   = pyo.value(m.dd[cid])
                d_val = day_index[d]
                coeff = (dtd + d_val) if dtd >= 0 else (dtd + pyo.value(m.alpha) * d_val)
                terms.append(coeff * m.x[cid, d, rid])
            for cid in m.C:
                c = case_map[cid]
                if c.priority != Priority.DEFERRED_URGENT:
                    terms.append(pyo.value(m.priority[cid]) *
                                 pyo.value(m.penalty[cid]) * m.z[cid])
            return sum(terms)

        m.OBJ = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        # ── Constraint (5.1): one procedure per patient per week ──────
        patients = {}
        for c in cases:
            patients.setdefault(c.patient_id, []).append(c.id)

        def one_per_patient(m, pid):
            return (
                sum(m.x[cid, d, rid]
                    for cid in patients.get(pid, [])
                    for (c2, d2, rid2) in m.CDR if c2 == cid and d2 == d  # iterate properly
                    for d in [d2] for rid in [rid2]
                    )
                <= 1
            )
        # Simpler rewrite:
        patient_ids = list(patients.keys())
        m.PatientSet = pyo.Set(initialize=patient_ids)

        def c51(m, pid):
            return (
                sum(m.x[cid, d, rid]
                    for (cid, d, rid) in m.CDR
                    if case_map[cid].patient_id == pid)
                <= 1
            )
        m.C51_OnePerPatient = pyo.Constraint(m.PatientSet, rule=c51,
                                               doc="(5.1) max one procedure per patient")

        # ── Constraint (5.2): priority-4 on day 1 ────────────────────
        urgent_cases = [c.id for c in cases if c.priority == Priority.DEFERRED_URGENT]
        if urgent_cases:
            m.UrgentSet = pyo.Set(initialize=urgent_cases)
            d1 = days[0]

            def c52(m, cid):
                return (
                    sum(m.x[cid, d1, rid]
                        for (c2, d2, rid) in m.CDR if c2 == cid and d2 == d1)
                    == 1
                )
            m.C52_Priority4Day1 = pyo.Constraint(m.UrgentSet, rule=c52,
                                                   doc="(5.2) priority-4 must be on day 1")

        # ── Constraint (5.3): schedule or penalise ───────────────────
        non_urgent = [c.id for c in cases if c.priority != Priority.DEFERRED_URGENT]
        m.NonUrgentSet = pyo.Set(initialize=non_urgent)

        def c53(m, cid):
            return (
                sum(m.x[cid, d, rid] for (c2, d, rid) in m.CDR if c2 == cid)
                + m.z[cid]
                == 1
            )
        m.C53_ScheduleOrPenalise = pyo.Constraint(m.NonUrgentSet, rule=c53,
                                                    doc="(5.3) x + z = 1 for non-urgent")

        # Force z=0 for urgent cases (they must be scheduled)
        m.UrgentZero = pyo.ConstraintList(doc="z_c=0 for priority-4")
        for cid in urgent_cases:
            m.UrgentZero.add(m.z[cid] == 0)

        # ── Constraint (5.7): room capacity ──────────────────────────
        def c57(m, d, rid):
            return (
                sum(m.t_tot[cid] * m.x[cid, d, rid]
                    for (cid, d2, rid2) in m.CDR if d2 == d and rid2 == rid)
                <= m.cap[d, rid]
            )
        m.C57_RoomCapacity = pyo.Constraint(m.D, m.R, rule=c57,
                                             doc="(5.7) room capacity constraint")

        # ── Constraint (5.8): surgeon daily limit ─────────────────────
        def c58(m, hid, d):
            return (
                sum(m.t_cir[cid] * m.x[cid, d, rid]
                    for (cid, d2, rid) in m.CDR
                    if d2 == d and case_map[cid].surgeon_id == hid)
                <= m.klim_day[hid, d]
            )
        m.C58_SurgeonDaily = pyo.Constraint(m.H, m.D, rule=c58,
                                             doc="(5.8) surgeon daily time limit")

        # ── Constraint (5.9): surgeon weekly limit ────────────────────
        def c59(m, hid):
            return (
                sum(m.t_cir[cid] * m.x[cid, d, rid]
                    for (cid, d, rid) in m.CDR
                    if case_map[cid].surgeon_id == hid)
                <= m.klim_week[hid]
            )
        m.C59_SurgeonWeekly = pyo.Constraint(m.H, rule=c59,
                                              doc="(5.9) surgeon weekly time limit")

        return m

    # ──────────────────────────────────────────────────────────────────
    # Solver call
    # ──────────────────────────────────────────────────────────────────

    def _call_solver(self, m: pyo.ConcreteModel):
        opt = pyo.SolverFactory(self.backend)

        options = {}
        if self.backend == "cbc":
            options["seconds"] = self.time_limit_sec
            options["ratioGap"] = self.mip_gap
        elif self.backend == "glpk":
            options["tmlim"] = self.time_limit_sec
            options["mipgap"] = self.mip_gap
        elif self.backend == "gurobi":
            options["TimeLimit"] = self.time_limit_sec
            options["MIPGap"] = self.mip_gap
        elif self.backend == "cplex":
            options["timelimit"] = self.time_limit_sec
            options["mip tolerances mipgap"] = self.mip_gap
        elif self.backend == "highs":
            options["time_limit"] = self.time_limit_sec
            options["mip_rel_gap"] = self.mip_gap

        return opt.solve(m, tee=False, options=options)

    # ──────────────────────────────────────────────────────────────────
    # Result extraction
    # ──────────────────────────────────────────────────────────────────

    def _extract_results(
        self,
        m: pyo.ConcreteModel,
        instance: PlanningInstance,
        results,
    ) -> SolverResult:

        tc = results.solver.termination_condition
        if tc in (TerminationCondition.optimal, TerminationCondition.feasible):
            status = "Optimal" if tc == TerminationCondition.optimal else "Feasible"
        else:
            status = str(tc)

        obj_val = pyo.value(m.OBJ) if status in ("Optimal", "Feasible") else None

        assignments = []
        unscheduled = []

        if obj_val is not None:
            for (cid, d, rid) in m.CDR:
                if pyo.value(m.x[cid, d, rid]) > 0.5:
                    assignments.append(Assignment(case_id=cid, day=d, room_id=rid))

            case_ids_scheduled = {a.case_id for a in assignments}
            for c in instance.cases:
                if c.id not in case_ids_scheduled:
                    if c.id in m.NonUrgentSet:
                        if pyo.value(m.z[c.id]) > 0.5:
                            unscheduled.append(c.id)

        return SolverResult(
            status=status,
            objective_value=obj_val,
            assignments=assignments,
            unscheduled_case_ids=unscheduled,
            solve_time_sec=0.0,
            solver_name=self.name,
        )
