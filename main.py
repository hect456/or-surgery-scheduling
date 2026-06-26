#!/usr/bin/env python3
"""
main.py — Demo runner for Elective Surgery Scheduling MILP.

Usage
-----
    python main.py                        # demo instance, PuLP/CBC
    python main.py --instance small       # 50-case instance
    python main.py --instance literature  # Cardoen benchmark (~60 cases)
    python main.py --solver greedy        # greedy heuristic only
    python main.py --solver pyomo-cbc     # Pyomo + CBC backend
    python main.py --solver pyomo-glpk    # Pyomo + GLPK backend
    python main.py --solver pyomo-gurobi  # Pyomo + Gurobi (needs licence)
    python main.py --compare              # run all available solvers and compare
    python main.py --time-limit 60        # set solver time limit (seconds)

The script prints a human-readable weekly schedule to stdout.
"""

import argparse
import sys
import os

# Allow running from repo root without installing
sys.path.insert(0, os.path.dirname(__file__))

from src.data.instances import demo_chln, small_chln, literature_cardoen
from src.solvers.pulp_cbc_solver import PuLPCBCSolver
from src.solvers.pyomo_solver import PyomoSolver
from src.solvers.greedy_solver import GreedySolver
from src.utils.reporter import print_header, print_result


INSTANCES = {
    "demo":       demo_chln,
    "small":      small_chln,
    "literature": literature_cardoen,
}


def get_solver(name: str, time_limit: int, gap: float):
    if name == "pulp-cbc" or name == "pulp":
        return PuLPCBCSolver(time_limit_sec=time_limit, mip_gap=gap)
    elif name == "greedy":
        return GreedySolver()
    elif name == "hexaly":
        from src.solvers.hexaly_solver import HexalySolver
        return HexalySolver(time_limit_sec=time_limit, mip_gap=gap)
    elif name.startswith("pyomo-"):
        backend = name.split("-", 1)[1]
        return PyomoSolver(backend=backend, time_limit_sec=time_limit, mip_gap=gap)
    else:
        print(f"Unknown solver '{name}'. Defaulting to pulp-cbc.")
        return PuLPCBCSolver(time_limit_sec=time_limit, mip_gap=gap)


def main():
    parser = argparse.ArgumentParser(
        description="Elective Surgery Scheduling MILP Demo"
    )
    parser.add_argument(
        "--instance", choices=list(INSTANCES.keys()), default="demo",
        help="Which instance to solve (default: demo)"
    )
    parser.add_argument(
        "--solver", default="pulp-cbc",
        help="Solver: pulp-cbc | greedy | pyomo-cbc | pyomo-glpk | pyomo-gurobi | pyomo-cplex"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Run all available solvers and print comparison table"
    )
    parser.add_argument(
        "--time-limit", type=int, default=120,
        help="Solver time limit in seconds (default: 120)"
    )
    parser.add_argument(
        "--gap", type=float, default=0.01,
        help="MIP gap tolerance (default: 0.01 = 1%%)"
    )
    args = parser.parse_args()

    instance = INSTANCES[args.instance]()
    print_header(instance)

    if args.compare:
        _run_comparison(instance, args.time_limit, args.gap)
    else:
        solver = get_solver(args.solver, args.time_limit, args.gap)
        result = solver.solve(instance)
        print_result(result, instance)


def _run_comparison(instance, time_limit: int, gap: float):
    """Run greedy + PuLP/CBC and compare objective values."""
    solvers = [
        GreedySolver(),
        PuLPCBCSolver(time_limit_sec=time_limit, mip_gap=gap),
    ]

    # Try Pyomo/CBC if available
    try:
        import pyomo.environ as pyo
        from src.solvers.pyomo_solver import PyomoSolver
        solvers.append(PyomoSolver(backend="cbc", time_limit_sec=time_limit, mip_gap=gap))
    except Exception:
        pass

    results = []
    for s in solvers:
        print(f"  Running {s.name} ...")
        r = s.solve(instance)
        results.append(r)
        print(f"    → {r.status}  obj={r.objective_value:.2f}  "
              f"scheduled={len(r.assignments)}/{len(instance.cases)}  "
              f"time={r.solve_time_sec:.3f}s")

    print()
    print("  ┌──────────────────┬───────────┬──────────┬───────────┬──────────┐")
    print("  │ Solver           │ Status    │ Obj      │ Sched     │ Time (s) │")
    print("  ├──────────────────┼───────────┼──────────┼───────────┼──────────┤")
    for r in results:
        sched = f"{len(r.assignments)}/{len(instance.cases)}"
        obj   = f"{r.objective_value:.1f}" if r.objective_value else "N/A"
        print(f"  │ {r.solver_name:<16} │ {r.status:<9} │ {obj:<8} │ {sched:<9} │ "
              f"{r.solve_time_sec:<8.3f} │")
    print("  └──────────────────┴───────────┴──────────┴───────────┴──────────┘")
    print()

    # Print the best solution detail
    best = min((r for r in results if r.is_optimal()),
               key=lambda r: r.objective_value or float("inf"),
               default=results[-1])
    print(f"  Best solution from: {best.solver_name}")
    print_result(best, instance)


if __name__ == "__main__":
    main()
