"""
base_solver.py — Abstract base class for all solver backends.

Design rationale
----------------
All solvers share the same interface so that:
  1. The main script can swap solvers with a single flag.
  2. Tests can verify that every solver produces the same schedule on
     the demo instance (regression testing).
  3. A library of models (interview Q2) is easy to extend.

The solve() method is the single entry point; it returns a SolverResult
that is solver-agnostic and human-readable.
"""

from __future__ import annotations
import time
from abc import ABC, abstractmethod
from typing import Optional

from ..model.types import PlanningInstance, SolverResult


class BaseSolver(ABC):
    """
    Abstract base for all OR-scheduling solver backends.

    Subclasses implement _build_and_solve() and return a SolverResult.
    The base class wraps it with timing and error handling.
    """

    name: str = "BaseSolver"

    def __init__(self, time_limit_sec: int = 120, mip_gap: float = 0.01):
        self.time_limit_sec = time_limit_sec
        self.mip_gap = mip_gap           # terminate when gap ≤ 1 % (operational quality)

    def solve(self, instance: PlanningInstance) -> SolverResult:
        """Public entry point. Times the solve and catches errors gracefully."""
        t0 = time.perf_counter()
        try:
            result = self._build_and_solve(instance)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return SolverResult(
                status=f"Error: {exc}",
                objective_value=None,
                assignments=[],
                unscheduled_case_ids=[c.id for c in instance.cases],
                solve_time_sec=elapsed,
                solver_name=self.name,
            )
        result.solve_time_sec = time.perf_counter() - t0
        return result

    @abstractmethod
    def _build_and_solve(self, instance: PlanningInstance) -> SolverResult:
        """Build the model, call the solver, extract and return results."""
        ...
