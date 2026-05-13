# Missionary Allocation Optimizer

A web application that solves a **preference-based assignment problem** using Mixed-Integer Linear Programming (MILP). Built for [Missão País](https://www.missaopais.pt/), a Portuguese volunteer missionary organisation, to automate the assignment of missionaries to ministry areas.

**Live demo:** [alocacao-missionarios.vercel.app](https://alocacao-missionarios.vercel.app)
&nbsp;·&nbsp;
**Source:** [github.com/deus1906/alocacao-missionarios](https://github.com/deus1906/alocacao-missionarios)

---

## The Problem

Each year, coordinators must assign hundreds of missionaries to a set of ministry areas (*valências* — e.g. children's ministry, elderly care, street outreach). Each missionary submits a ranked preference list. Each area has a fixed capacity. The goal is to find an assignment that is simultaneously:

1. **Feasible** — every missionary is assigned, every area is filled exactly.
2. **Preference-aware** — assignments respect individual rankings as much as possible.
3. **Fair** — no missionary is systematically disadvantaged (minimax over worst-case rank).

This is a variant of the **Hospital-Resident** / **Assignment Problem** with capacities, hard fixed pre-assignments, and a multi-objective fairness criterion.

---

## Optimization Model

### Decision Variables

Binary variable $x_{p,v} \in \{0,1\}$ — 1 if person $p$ is assigned to ministry $v$.

### Constraints

| Constraint | Description |
|---|---|
| $\sum_v x_{p,v} = 1 \quad \forall p$ | Each missionary assigned to exactly one area |
| $\sum_p x_{p,v} = c_v \quad \forall v$ | Each area $v$ filled to its required capacity $c_v$ |
| $x_{p,v^*} = 1$ | Honour any fixed pre-assignments |

### Objective — Three-Phase Lexicographic Solver

A plain happiness-maximisation objective produces high aggregate scores but can leave some missionaries assigned to their last-ranked choice. The solver uses a **lexicographic minimax** strategy instead:

**Phase 1 — Minimax:** Minimise the worst rank assigned across all missionaries.

$$\min \; R_{\max} \quad \text{s.t.} \quad \sum_v \text{rank}(p,v) \cdot x_{p,v} \leq R_{\max} \quad \forall p$$

**Phase 2 — Minimise penalty given $R_{\max}$:** Lock $R_{\max}$ and minimise a quadratic penalty that penalises assignments below rank 2:

$$\min \sum_{p,v} \max(0,\; \text{rank}(p,v) - 2)^2 \cdot x_{p,v}$$

**Phase 3 — Maximise happiness:** Lock both $R_{\max}$ and the penalty, then maximise total preference score using a decaying weight schedule [100, 80, 60, 45, 30, 15] for ranks 1–6. Unranked assignments carry a heavy penalty of −1000.

This lexicographic approach guarantees Pareto-efficient solutions where fairness takes priority over aggregate utility.

---

## Stack

| Layer | Technology |
|---|---|
| Solver | [PuLP](https://coin-or.github.io/pulp/) + [CBC](https://github.com/coin-or/Cbc) (open-source MILP) |
| Backend | Python 3.11 |
| Frontend | [Dash](https://dash.plotly.com/) + [AG Grid](https://dash.ag-grid.com/) + Bootstrap |
| Data I/O | pandas · openpyxl |
| Deployment | Vercel (serverless, WSGI via `api/index.py`) |

---

## Architecture

```
alocation_mission/
├── app.py                      # Dash frontend + all callbacks
├── api/index.py                # Vercel WSGI entrypoint
├── allocation/
│   ├── config.py               # Weights, penalty defaults, sheet names
│   ├── data_handling.py        # Excel parsing → normalised data structures
│   ├── model_creation.py       # MILP model builder (variables, objective, constraints)
│   └── main_optimization.py   # Solver orchestration, 3-phase loop, output writer
├── assets/                     # CSS + favicon
├── input.xlsx                  # Example input file
└── vercel.json                 # Routing config
```

The solver is fully decoupled from the frontend: `run_allocation()` takes raw bytes or a file path and returns assignments — usable as a library or via CLI.

---

## Input Format

The Excel workbook must contain two sheets.

**Sheet `Missionarios`**

| Nome | Valência Fixa | Rank1 | Rank2 | Rank3 | … |
|---|---|---|---|---|---|
| João Silva | Theatre | Street Outreach | Nursery | Children | … |
| Maria Santos | | Children | Nursery | Moral | … |

- `Valência Fixa` (optional): force a pre-assignment for that missionary.
- `Rank1`, `Rank2`, … columns: preference list in order.

**Sheet `Valencias`**

| Valência | Nº Missionários |
|---|---|
| Street Outreach | 12 |
| Children | 12 |
| Elderly | 10 |

The sum of `Nº Missionários` must equal the total number of missionaries.

An example workbook (`input.xlsx`) is included and downloadable from the app.

---

## Running Locally

```bash
pip install -r requirements.txt
python app.py          # starts Dash dev server on port 8030
```

**CLI usage:**

```bash
python -m allocation.main_optimization \
  --input input.xlsx \
  --output output.xlsx \
  --time-limit 60
```

---

## Design Decisions

**Why MILP over heuristics?** The problem is small enough (typically < 500 missionaries, < 20 areas) that CBC solves it in under a second. MILP gives a provably optimal solution within the feasible set, with guarantees that no greedy or local-search heuristic can provide.

**Why lexicographic minimax?** Maximising total happiness is utilitarian — it can sacrifice one missionary's preferences to gain marginal improvements for many others. The minimax criterion prevents that. Locking $R_{\max}$ before maximising happiness is a standard technique from multi-objective optimisation (ε-constraint method).

**Why Dash?** The target users are non-technical coordinators. Dash lets the entire app — upload, solve, preview, download — live in a browser with no installation required.

---

## Author

João de Deus · 2026
