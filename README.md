# Elective Surgery Scheduling — MILP Model & Demo Solver

**Operations Research · Healthcare Scheduling · Portuguese NHS (SNS/SIGIC)**

> A rigorous Mixed-Integer Linear Programme for weekly elective surgery planning,
> grounded in CHLN operational data and SIGIC clinical priority rules (Portaria n.º 45/2008).

---

## Quick Start

```bash
# 1. Install dependencies (no commercial licence required)
pip install pulp pyomo

# Optional open-source: pip install highspy
# Optional commercial:  pip install gurobipy  |  pip install cplex

# 2. Run the 20-case demo (PuLP/CBC — always available)
python main.py

# 3. Compare all available solvers
python main.py --compare

# 4. Larger instances
python main.py --instance small        # 50 cases, 4 services
python main.py --instance literature   # ~60 cases, Cardoen benchmark structure

# 5. Choose backend
python main.py --solver pyomo-cbc
python main.py --solver pyomo-glpk
python main.py --solver pyomo-gurobi   # requires gurobipy + licence
python main.py --solver pyomo-cplex    # requires cplex + licence
python main.py --solver pyomo-highs    # pip install highspy
python main.py --solver greedy         # milliseconds, no solver needed

# 6. Run tests
python tests/test_model.py
```

---

## Repository Structure

```
or-surgery-scheduling/
├── main.py                       # CLI entry point
├── FORMULATION.md                # Full mathematical formulation (sets, params, variables, constraints, objective)
├── README.md                     # This file
├── requirements.txt
│
├── src/
│   ├── model/
│   │   ├── types.py              # SurgicalCase, Surgeon, OperatingRoom, PlanningInstance, SolverResult
│   │   └── penalty.py            # w_c penalty weight (Figure 5.1, Marques & Captivo 2015)
│   │
│   ├── solvers/
│   │   ├── base_solver.py        # Abstract interface — solver-agnostic
│   │   ├── pulp_cbc_solver.py    # PuLP + CBC — PRIMARY demo solver
│   │   ├── pyomo_solver.py       # Pyomo — CBC / GLPK / Gurobi / CPLEX / HiGHS
│   │   └── greedy_solver.py      # Constructive heuristic (warm-start / upper bound)
│   │
│   ├── data/
│   │   └── instances.py          # demo_chln() · small_chln() · literature_cardoen()
│   │
│   └── utils/
│       └── reporter.py           # Schedule printer + consistency checks
│
├── tests/
│   └── test_model.py             # 7 unit tests — all constraint types
│
└── docs/
    └── or_surgery_scheduling_beamer.pptx   # 20-slide Beamer-style presentation
```

---

## Mathematical Model — Summary

**Decision variables:**

| Variable | Domain | Meaning |
|----------|--------|---------|
| $x_{cdbr}$ | $\{0,1\}$ | Case $c$ scheduled on day $d$, block $b$, room $r$ |
| $z_c$ | $\mathbb{R}^+ (\in\{0,1\})$ | Case $c$ is NOT scheduled (penalty variable) |

**Objective (5.12):** minimise weighted tardiness + non-scheduling penalty.  
Three terms: on-time cases / overdue cases (×α urgency multiplier) / penalty w_c for non-scheduling.

**Constraints:**

| # | Name | Rule |
|---|------|------|
| 5.1 | One per patient | At most one surgery per patient per week |
| 5.2 | Priority-4 on Monday | Deferred-urgent cases must be on day 1 (72h SIGIC window) |
| 5.3 | Schedule or penalise | Non-urgent cases: scheduled exactly once, or pay w_c |
| 5.4 | MSS service-room | Rooms only host cases from their assigned surgical service |
| 5.5 | Ambulatory block | Ambulatory-only rooms exclude inpatient cases |
| 5.6 | ORL paediatric Fri | ORL rooms on Fridays: patients ≤ 8 years only |
| 5.7 | Room capacity | Total occupation ≤ daily opening hours (no overtime) |
| 5.8 | Surgeon daily | Operative time per surgeon per day ≤ k_{hd}^dia |
| 5.9 | Surgeon weekly | Operative time per surgeon per week ≤ k_h^sem |

See **FORMULATION.md** for full notation, justifications, and references.

---

## Demo Results (20-case CHLN instance)

```
========================================================================
  ELECTIVE SURGERY SCHEDULING — DEMO_CHLN_20CASES
========================================================================
  Cases    : 20  |  Rooms: 5  |  Surgeons: 6
  Overdue  : 3 cases already past deadline
  P4 (must Mon): 3 cases

  Solver  : PuLP/CBC
  Status  : Optimal
  Obj     : 155.00
  Time    : 0.027s

  Mon  (11 cases): C14 C18 [CVA] | C03⚠ C04 C07 C02 C05★ C06 [ORL] | C11⚠ C13★ [ORT]
  Tue  ( 6 cases): C16⚠ C15 C17  [CVA] | C01 [ORL] | C09 C10 [ORT]
  Wed  ( 2 cases): C20 [CVA] | C08 [ORT]
  Thu  ( 1 case ): C12 [ORT]
  Fri  ( 0 cases): — (ORL paediatric circuit: no adult ORL patients ✓)

  ⚠ = overdue   ★ = Priority-4 (forced to Mon)   Unscheduled: 0

  ✓ All priority-4 cases scheduled on Monday
  ✓ Paediatric ORL circuit respected
  ✓ All room capacities respected (no overtime)
  ✓ All surgeon time limits respected
```

**Solver comparison (demo instance):**

| Solver       | Status  | Obj   | Scheduled | Time     |
|--------------|---------|-------|-----------|----------|
| Greedy       | Feasible| 161.0 | 20/20     | < 0.001s |
| PuLP/CBC     | Optimal | 155.0 | 20/20     | 0.027s   |
| Pyomo/CBC    | Optimal | 155.0 | 20/20     | 0.046s   |
| Pyomo/Gurobi | Optimal | 155.0 | 20/20     | < 0.01s  |

Greedy gap: **3.7%** — useful as warm-start for MILP.

---

## Solver Backends

| Solver | Licence | Installation | Notes |
|--------|---------|-------------|-------|
| PuLP/CBC | Free (EPL) | `pip install pulp` | Default; always available |
| Pyomo/CBC | Free (EPL) | `pip install pyomo` + `apt install coinor-cbc` | Same model, Pyomo interface |
| Pyomo/GLPK | Free (GPL) | `apt install glpk-utils` | Good for small/medium instances |
| Pyomo/Gurobi | Commercial | `pip install gurobipy` + licence | Best performance at scale |
| Pyomo/CPLEX | Commercial | `pip install cplex` + licence | IBM; competitive with Gurobi |
| Pyomo/HiGHS | Free (MIT) | `pip install highspy` | State-of-the-art open solver |
| Greedy | None | built-in | Priority-first heuristic; 3.7% gap on demo |

For very large instances (real CHLN: ~130k variables after pre-filtering), Gurobi or CPLEX with the Pyomo backend are recommended. HiGHS is a strong free alternative.

---

## Open Questions

### 1. Passing the Torch

To hand this formulation to a developer faithfully:

1. **This markdown + code**: `FORMULATION.md` and `src/` are designed to be read together — every constraint in the markdown has an identically-numbered counterpart in the Python (`C57_RoomCapacity`, `C58_SurgeonDaily`, etc.).
2. **Entity schema**: `src/model/types.py` is the data dictionary — `SurgicalCase`, `Surgeon`, `OperatingRoom`, `PlanningInstance` are the schema, no ORM needed.
3. **Acceptance tests**: `tests/test_model.py` has 7 constraint-level unit tests. Any correct implementation must pass all 7. The tests are the contract.
4. **Minimum reproducible instance**: `demo_chln()`, 20 cases, known optimal obj = 155.0 in < 0.03s. Run this before scaling.
5. **Domain glossary**: LIC (Lista de Inscritos para Cirurgia), MSS (Master Surgery Schedule), SIGIC, prioridade, âmbito, higienização — shared vocabulary between OR scientists and engineers.

### 2. A Library of Models

Organise the library around four layers:

1. **Core abstractions** (`BaseSolver`, `PlanningInstance`, typed dataclasses) — solver-agnostic, fully testable, no external dependencies.
2. **Domain building blocks** (`CapacityConstraint`, `ResourceLimitConstraint`, `PriorityWeighting`, `TimeWindowConstraint`) — reusable primitives composable across surgery scheduling, nurse rostering, bed allocation, equipment assignment.
3. **Problem templates** (`SurgeryScheduler`, `NurseRoster`, `BedAllocation`) — YAML/JSON-configured compositions of building blocks; adding a new problem means assembling blocks and writing a config file, not writing new Python.
4. **Institution configurations** (`CHLN_Config`, `HospitalX_Config`) — client-specific overrides (MSS structure, SIGIC parameters, special operational rules).

The solver layer is orthogonal to all four: the same `ConcreteModel` compiles to CBC, Gurobi, CPLEX, or HiGHS via a single string argument, so licence availability and instance scale drive backend selection without touching the formulation.

---

## References

1. Marques, I., & Captivo, M.E. (2015). *Planeamento de cirurgias eletivas no Centro Hospitalar Lisboa Norte*. MSc Thesis, Universidade de Lisboa.
2. Cardoen, B., Demeulemeester, E., & Beliën, J. (2010). Operating room planning and scheduling: A literature review. *EJOR* 201(3), 921–932.
3. Denton, B.T., et al. (2010). Optimal allocation of surgery blocks to operating rooms under uncertainty. *Operations Research* 58(4), 802–816.
4. SIGIC — Portaria n.º 45/2008, Diário da República, Portugal.
5. Van Riet, C., & Demeulemeester, E. (2015). Trade-offs in OR planning for electives and emergencies. *OR Spectrum* 37(1), 59–87.
