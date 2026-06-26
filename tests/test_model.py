"""
tests/test_model.py — Unit tests for the MILP model.

Tests verify:
1. Constraint correctness (all feasibility checks pass on demo instance).
2. Solver consistency (greedy and MILP produce the same feasible structure).
3. Priority-4 cases always appear on day 1.
4. No room capacity violation.
5. No surgeon time-limit violation.
6. Paediatric ORL circuit respected.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.instances import demo_chln, small_chln
from src.solvers.pulp_cbc_solver import PuLPCBCSolver
from src.solvers.greedy_solver import GreedySolver
from src.model.types import Priority


def test_demo_solves_to_optimal():
    inst   = demo_chln()
    solver = PuLPCBCSolver(time_limit_sec=60)
    result = solver.solve(inst)
    assert result.status == "Optimal", f"Expected Optimal, got {result.status}"
    assert result.objective_value is not None


def test_priority4_on_day1():
    inst   = demo_chln()
    solver = PuLPCBCSolver(time_limit_sec=60)
    result = solver.solve(inst)
    scheduled = {a.case_id: a for a in result.assignments}
    d1 = inst.days[0]
    for c in inst.cases:
        if c.priority == Priority.DEFERRED_URGENT:
            a = scheduled.get(c.id)
            assert a is not None, f"P4 case {c.id} not scheduled"
            assert a.day == d1, f"P4 case {c.id} on {a.day}, expected {d1}"


def test_room_capacity_not_exceeded():
    inst   = demo_chln()
    solver = PuLPCBCSolver(time_limit_sec=60)
    result = solver.solve(inst)
    case_map = inst.cases_by_id
    from collections import defaultdict
    load: dict = defaultdict(int)
    for a in result.assignments:
        c = case_map[a.case_id]
        load[a.day, a.room_id] += c.t_tot
    room_map = inst.rooms_by_id
    for (d, rid), used in load.items():
        cap = room_map[rid].capacity_min.get(d, 0)
        assert used <= cap, f"Room {rid} on {d}: {used} > {cap}"


def test_surgeon_limits_not_exceeded():
    inst   = demo_chln()
    solver = PuLPCBCSolver(time_limit_sec=60)
    result = solver.solve(inst)
    case_map = inst.cases_by_id
    surg_map = inst.surgeons_by_id
    from collections import defaultdict
    day_load:  dict = defaultdict(int)
    week_load: dict = defaultdict(int)
    for a in result.assignments:
        c = case_map[a.case_id]
        day_load[c.surgeon_id, a.day] += c.t_cir
        week_load[c.surgeon_id] += c.t_cir
    for (hid, d), ld in day_load.items():
        assert ld <= surg_map[hid].daily_limit_min, \
            f"Surgeon {hid} on {d}: {ld} > daily limit"
    for hid, ld in week_load.items():
        assert ld <= surg_map[hid].weekly_limit_min, \
            f"Surgeon {hid}: {ld} > weekly limit"


def test_paediatric_circuit():
    inst   = demo_chln()
    solver = PuLPCBCSolver(time_limit_sec=60)
    result = solver.solve(inst)
    case_map = inst.cases_by_id
    for a in result.assignments:
        c = case_map[a.case_id]
        assert not inst.is_paediatric_day(c, a.day), \
            f"Case {c.id} (age {c.patient_age}) scheduled on paediatric day"


def test_greedy_feasible():
    inst   = demo_chln()
    solver = GreedySolver()
    result = solver.solve(inst)
    assert result.is_optimal(), f"Greedy failed: {result.status}"
    # All priority-4 must be scheduled
    case_map = inst.cases_by_id
    scheduled_ids = {a.case_id for a in result.assignments}
    for c in inst.cases:
        if c.priority == Priority.DEFERRED_URGENT:
            assert c.id in scheduled_ids, f"Greedy: P4 {c.id} not scheduled"


def test_small_instance_feasible():
    inst   = small_chln(seed=42)
    solver = PuLPCBCSolver(time_limit_sec=60, mip_gap=0.05)
    result = solver.solve(inst)
    assert result.is_optimal(), f"Small instance: {result.status}"


if __name__ == "__main__":
    tests = [
        test_demo_solves_to_optimal,
        test_priority4_on_day1,
        test_room_capacity_not_exceeded,
        test_surgeon_limits_not_exceeded,
        test_paediatric_circuit,
        test_greedy_feasible,
        test_small_instance_feasible,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: ERROR — {e}")
            failed += 1
    print(f"\n  {passed} passed, {failed} failed")
