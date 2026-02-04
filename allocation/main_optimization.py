"""Entry point for the allocation optimization workflow."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

from loguru import logger
import pulp

try:
    from allocation.config import OUTPUT_FALLBACK_COLUMNS, OUTPUT_SHEET
    from allocation.data_handling import load_input_data
    from allocation.model_creation import build_allocation_problem
except ModuleNotFoundError:
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from allocation.config import OUTPUT_FALLBACK_COLUMNS, OUTPUT_SHEET
    from allocation.data_handling import load_input_data
    from allocation.model_creation import build_allocation_problem


#=========================================================================
# 0. LOGGING
#=========================================================================

def _configure_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stdout, level=level)


#=========================================================================
# 1. SOLVE WORKFLOW
#=========================================================================

def _solve_model(
    data: Dict[str, Any],
    *,
    weights: List[float] | None = None,
    unranked_penalty: float | None = None,
    time_limit: int | None = None,
    solver_msg: bool = False,
    fairness_mode: str | None = "minimax_balance",
) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if unranked_penalty is not None:
        params["unranked_penalty"] = unranked_penalty

    spec = build_allocation_problem(data, weights=weights, params=params)

    problem = pulp.LpProblem("missionario_allocation", pulp.LpMaximize)
    for constraint, name in spec["constraints"]:
        problem += constraint, name

    solver = pulp.PULP_CBC_CMD(msg=solver_msg, timeLimit=time_limit)
    happiness_objective = spec["objective"]
    if fairness_mode in {"minimax", "minimax_balance"}:
        rank_value_map = spec["additional_data"]["rank_value_map"]
        penalty_map = spec["additional_data"].get("penalty_map")
        max_rank_var = pulp.LpVariable("MaxRank", lowBound=1, cat=pulp.LpInteger)
        for person in data["people"]:
            problem += (
                pulp.lpSum(
                    rank_value_map[(person, valencia)]
                    * spec["variables"]["assign"][(person, valencia)]
                    for valencia in data["valencias"]
                )
                <= max_rank_var,
                f"maxrank_{person}",
            )

        problem.sense = pulp.LpMinimize
        problem.setObjective(max_rank_var)
        status = problem.solve(solver)
        status_str = pulp.LpStatus.get(status, str(status))
        if status_str not in {"Optimal", "Feasible"}:
            logger.error("Solver ended with status: {}", status_str)
            raise SystemExit(1)
        best_max_rank = max_rank_var.value()
        if best_max_rank is None:
            logger.error("Failed to compute max rank value.")
            raise SystemExit(1)
        logger.info("Best achievable max rank: {}", int(round(best_max_rank)))
        problem += max_rank_var <= best_max_rank, "lock_max_rank"

        if fairness_mode == "minimax_balance" and penalty_map is not None:
            penalty_expr = pulp.lpSum(
                penalty_map[(person, valencia)]
                * spec["variables"]["assign"][(person, valencia)]
                for person in data["people"]
                for valencia in data["valencias"]
            )
            problem.sense = pulp.LpMinimize
            problem.setObjective(penalty_expr)
            status = problem.solve(solver)
            status_str = pulp.LpStatus.get(status, str(status))
            if status_str not in {"Optimal", "Feasible"}:
                logger.error("Solver ended with status: {}", status_str)
                raise SystemExit(1)
            best_penalty = penalty_expr.value()
            if best_penalty is None:
                logger.error("Failed to compute penalty value.")
                raise SystemExit(1)
            logger.info("Best achievable penalty: {}", int(round(best_penalty)))
            problem += penalty_expr <= best_penalty, "lock_penalty"

        problem.sense = pulp.LpMaximize
        problem.setObjective(happiness_objective)
        status = problem.solve(solver)
        status_str = pulp.LpStatus.get(status, str(status))
        if status_str not in {"Optimal", "Feasible"}:
            logger.error("Solver ended with status: {}", status_str)
            raise SystemExit(1)
    else:
        problem.sense = pulp.LpMaximize
        problem.setObjective(happiness_objective)
        status = problem.solve(solver)
        status_str = pulp.LpStatus.get(status, str(status))
        if status_str not in {"Optimal", "Feasible"}:
            logger.error("Solver ended with status: {}", status_str)
            raise SystemExit(1)

    assignments: Dict[str, str] = {}
    assign_vars = spec["variables"]["assign"]
    for person in data["people"]:
        chosen = None
        for valencia in data["valencias"]:
            if assign_vars[(person, valencia)].value() > 0.5:
                chosen = valencia
                break
        if not chosen:
            logger.error("No assignment found for {}", person)
            raise SystemExit(1)
        assignments[person] = chosen

    return {
        "assignments": assignments,
        "status": status_str,
    }


#=========================================================================
# 1.5. DEBUG DEFAULTS
#=========================================================================

DEBUG_INPUT_PATH = "input.xlsx"
DEBUG_OUTPUT_PATH = "output.xlsx"


#=========================================================================
# 2. OUTPUT WRITING
#=========================================================================

def _write_output_excel(
    output_path: str,
    rows: List[Dict[str, Any]],
    *,
    sheet_name: str = OUTPUT_SHEET,
) -> None:
    try:
        import pandas as pd

        df = pd.DataFrame(rows)
        df.to_excel(output_path, index=False, sheet_name=sheet_name)
        return
    except Exception as pandas_exc:
        logger.debug("Pandas write failed: {}", pandas_exc)

    try:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        if rows:
            headers = list(rows[0].keys())
            ws.append(headers)
            for row in rows:
                ws.append([row.get(header) for header in headers])
        wb.save(output_path)
        return
    except Exception as openpyxl_exc:
        raise RuntimeError(
            "Failed to write Excel output. Install pandas or openpyxl."
        ) from openpyxl_exc


#=========================================================================
# 3. PROGRAMMATIC ENTRY
#=========================================================================

def run_allocation(
    *,
    input_path: str,
    output_path: str,
    input_bytes: bytes | None = None,
    time_limit: int | None = None,
    unranked_penalty: float | None = None,
    solver_msg: bool = False,
    verbose: bool = False,
    fairness_mode: str | None = "minimax_balance",
) -> Dict[str, Any]:
    _configure_logging(verbose)

    if input_bytes is None:
        if not os.path.exists(input_path):
            logger.error("Input file not found: {}", input_path)
            raise SystemExit(1)
        data = load_input_data(input_path)
    else:
        data = load_input_data(input_bytes)
    result = _solve_model(
        data,
        unranked_penalty=unranked_penalty,
        time_limit=time_limit,
        solver_msg=solver_msg,
        fairness_mode=fairness_mode,
    )

    col_person = data["columns"].get("person") or OUTPUT_FALLBACK_COLUMNS["person"]
    col_valencia = data["columns"].get("valencia") or OUTPUT_FALLBACK_COLUMNS["valencia"]
    col_rank = OUTPUT_FALLBACK_COLUMNS["rank"]

    rows: List[Dict[str, Any]] = []
    for person in data["people"]:
        valencia = result["assignments"][person]
        rank = data["rankings"].get(person, {}).get(valencia, "Unranked")
        rows.append(
            {
                col_person: person,
                col_valencia: valencia,
                col_rank: rank,
            }
        )

    _write_output_excel(output_path, rows)
    logger.info("Optimization completed with status {}", result["status"])
    logger.info("Output written to {}", output_path)
    return result


def run_debug() -> Dict[str, Any]:
    return run_allocation(
        input_path=DEBUG_INPUT_PATH,
        output_path=DEBUG_OUTPUT_PATH,
        verbose=True,
    )


#=========================================================================
# 4. CLI
#=========================================================================

def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Missionario allocation optimizer")
    parser.add_argument("--input", required=True, help="Path to input Excel file")
    parser.add_argument("--output", required=True, help="Path to output Excel file")
    parser.add_argument(
        "--time-limit",
        type=int,
        default=None,
        help="CBC time limit in seconds",
    )
    parser.add_argument(
        "--unranked-penalty",
        type=float,
        default=None,
        help="Penalty for assigning an unranked valencia",
    )
    parser.add_argument(
        "--solver-msg",
        action="store_true",
        help="Enable solver output",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    run_allocation(
        input_path=args.input,
        output_path=args.output,
        time_limit=args.time_limit,
        unranked_penalty=args.unranked_penalty,
        solver_msg=args.solver_msg,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    if len(sys.argv) == 1:
        run_debug()
    else:
        main()
