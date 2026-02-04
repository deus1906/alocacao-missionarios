"""Model creation for the allocation optimization problem."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from loguru import logger
import pulp

from allocation.config import DEFAULT_WEIGHTS, UNRANKED_PENALTY

ConstraintSpec = Tuple[pulp.LpConstraint, str]


#=========================================================================
# 1. DATA EXTRACTION & PREPARATION
#=========================================================================

#-------------------------------------------------------------------------
# 1.1. Core data structures
#-------------------------------------------------------------------------

def _weight_for_rank(rank: int, weights: List[float]) -> float:
    if rank <= len(weights):
        return float(weights[rank - 1])
    last = float(weights[-1]) if weights else 0.0
    step = 5.0
    return max(5.0, last - step * (rank - len(weights)))


def _build_weight_map(
    people: Iterable[str],
    valencias: Iterable[str],
    rankings: Dict[str, Dict[str, int]],
    weights: List[float],
    unranked_penalty: float,
) -> Dict[Tuple[str, str], float]:
    weight_map: Dict[Tuple[str, str], float] = {}
    for person in people:
        person_ranks = rankings.get(person, {})
        for valencia in valencias:
            rank = person_ranks.get(valencia)
            if rank is None:
                weight_map[(person, valencia)] = float(unranked_penalty)
            else:
                weight_map[(person, valencia)] = _weight_for_rank(rank, weights)
    return weight_map


def _build_rank_value_map(
    people: Iterable[str],
    valencias: Iterable[str],
    rankings: Dict[str, Dict[str, int]],
    unranked_rank: int,
) -> Dict[Tuple[str, str], int]:
    rank_map: Dict[Tuple[str, str], int] = {}
    for person in people:
        person_ranks = rankings.get(person, {})
        for valencia in valencias:
            rank = person_ranks.get(valencia)
            if rank is None:
                rank_map[(person, valencia)] = unranked_rank
            else:
                rank_map[(person, valencia)] = int(rank)
    return rank_map


def _build_penalty_map(
    people: Iterable[str],
    valencias: Iterable[str],
    rank_value_map: Dict[Tuple[str, str], int],
) -> Dict[Tuple[str, str], int]:
    penalty_map: Dict[Tuple[str, str], int] = {}
    for person in people:
        for valencia in valencias:
            rank = rank_value_map[(person, valencia)]
            if rank <= 2:
                penalty = 0
            else:
                penalty = (rank - 2) ** 2
            penalty_map[(person, valencia)] = penalty
    return penalty_map


#-------------------------------------------------------------------------
# 1.2. Parameters and derived attributes
#-------------------------------------------------------------------------

def build_allocation_problem(
    data: Dict[str, Any],
    *,
    weights: List[float] | None = None,
    params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Translate pre-processed data structures into a PuLP model description.

    Returns:
        dict with keys: variables, objective, constraints, additional_data
    """
    params = params or {}
    weights = weights or DEFAULT_WEIGHTS
    unranked_penalty = float(params.get("unranked_penalty", UNRANKED_PENALTY))

    people = data["people"]
    valencias = data["valencias"]
    capacities = data["capacities"]
    rankings = data["rankings"]
    fixed_assignments = data.get("fixed_assignments", {})

    #=========================================================================
    # 1.4. Index sets for variables
    #=========================================================================
    x_index = [(person, valencia) for person in people for valencia in valencias]

    #=========================================================================
    # 2. DECISION VARIABLES
    #=========================================================================
    x = pulp.LpVariable.dicts("Assign", x_index, cat=pulp.LpBinary)

    #=========================================================================
    # 3. OBJECTIVE FUNCTION
    #=========================================================================
    weight_map = _build_weight_map(
        people, valencias, rankings, weights, unranked_penalty
    )
    all_ranks = [rank for person_ranks in rankings.values() for rank in person_ranks.values()]
    max_rank = max(all_ranks) if all_ranks else len(weights)
    unranked_rank = max_rank + 1
    rank_value_map = _build_rank_value_map(
        people, valencias, rankings, unranked_rank
    )
    penalty_map = _build_penalty_map(people, valencias, rank_value_map)
    objective = pulp.lpSum(weight_map[idx] * x[idx] for idx in x_index)

    #=========================================================================
    # 4. CONSTRAINTS
    #=========================================================================
    constraints: List[ConstraintSpec] = []

    # 4.1 Each person assigned to exactly one valencia
    for person in people:
        constraints.append(
            (
                pulp.lpSum(x[(person, valencia)] for valencia in valencias) == 1,
                f"assign_{person}",
            )
        )

    # 4.2 Each valencia filled to required capacity
    for valencia in valencias:
        constraints.append(
            (
                pulp.lpSum(x[(person, valencia)] for person in people)
                == capacities[valencia],
                f"capacity_{valencia}",
            )
        )

    # 4.3 Fixed allocations
    for person, valencia in fixed_assignments.items():
        constraints.append(
            (x[(person, valencia)] == 1, f"fixed_{person}")
        )

    logger.info(
        "Model built with {} people, {} valencias, {} binaries.",
        len(people),
        len(valencias),
        len(x_index),
    )

    return {
        "variables": {"assign": x},
        "objective": objective,
        "constraints": constraints,
        "additional_data": {
            "weight_map": weight_map,
            "rank_value_map": rank_value_map,
            "penalty_map": penalty_map,
            "unranked_rank": unranked_rank,
            "weights": weights,
            "unranked_penalty": unranked_penalty,
        },
    }
