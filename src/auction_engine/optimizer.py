from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

OFFENSE_FLEX = {"RB", "WR", "TE"}


@dataclass(frozen=True)
class RosterRules:
    qb: int = 1
    rb: int = 2
    wr: int = 2
    te: int = 1
    flex: int = 2
    dst: int = 1
    k: int = 1
    roster_size: int = 16
    min_bid: int = 1

    @property
    def starter_count(self) -> int:
        return self.qb + self.rb + self.wr + self.te + self.flex + self.dst + self.k

    @property
    def bench_count(self) -> int:
        return self.roster_size - self.starter_count


@dataclass
class OptimizationResult:
    selected: pd.DataFrame
    projected_points: float
    total_cost: float
    success: bool
    message: str


def _constraint_row(pos: np.ndarray, target: str) -> np.ndarray:
    return (pos == target).astype(float)


def optimize_starter_core(
    players: pd.DataFrame,
    budget: float,
    rules: RosterRules,
    points_col: str = "projected_points",
    cost_col: str = "price",
    exclude: Iterable[str] | None = None,
    force_include: Iterable[str] | None = None,
    bench_slots_remaining: int | None = None,
) -> OptimizationResult:
    df = players.copy()
    if exclude:
        df = df[~df["player"].isin(set(exclude))]
    df = df.dropna(subset=[points_col, cost_col, "position"]).reset_index(drop=True)
    if df.empty:
        return OptimizationResult(df, 0, 0, False, "No eligible players")

    bench_slots_remaining = rules.bench_count if bench_slots_remaining is None else bench_slots_remaining
    starter_budget = budget - max(0, bench_slots_remaining) * rules.min_bid
    if starter_budget < 0:
        return OptimizationResult(df.iloc[0:0], 0, 0, False, "Budget below required bench reserve")

    n = len(df)
    pos = df["position"].to_numpy()
    constraints = []

    def add(row: np.ndarray, lb: float, ub: float) -> None:
        constraints.append(LinearConstraint(row, lb=lb, ub=ub))

    add(_constraint_row(pos, "QB"), rules.qb, rules.qb)
    add(_constraint_row(pos, "DST"), rules.dst, rules.dst)
    add(_constraint_row(pos, "K"), rules.k, rules.k)
    add(_constraint_row(pos, "RB"), rules.rb, np.inf)
    add(_constraint_row(pos, "WR"), rules.wr, np.inf)
    add(_constraint_row(pos, "TE"), rules.te, np.inf)
    add(np.isin(pos, list(OFFENSE_FLEX)).astype(float), rules.rb + rules.wr + rules.te + rules.flex, rules.rb + rules.wr + rules.te + rules.flex)
    add(np.ones(n), rules.starter_count, rules.starter_count)
    add(df[cost_col].to_numpy(dtype=float), -np.inf, starter_budget)

    for player in force_include or []:
        idx = np.flatnonzero(df["player"].to_numpy() == player)
        if len(idx) == 0:
            return OptimizationResult(df.iloc[0:0], 0, 0, False, f"Forced player unavailable: {player}")
        row = np.zeros(n)
        row[idx[0]] = 1
        add(row, 1, 1)

    result = milp(
        c=-df[points_col].to_numpy(dtype=float),
        integrality=np.ones(n),
        bounds=Bounds(np.zeros(n), np.ones(n)),
        constraints=constraints,
        options={"time_limit": 10.0},
    )
    if not result.success or result.x is None:
        return OptimizationResult(df.iloc[0:0], 0, 0, False, result.message)
    chosen = df[np.rint(result.x).astype(bool)].copy().sort_values(["position", points_col], ascending=[True, False])
    return OptimizationResult(
        selected=chosen,
        projected_points=float(chosen[points_col].sum()),
        total_cost=float(chosen[cost_col].sum()),
        success=True,
        message=result.message,
    )


def minimum_cost_roster_for_points(
    players: pd.DataFrame,
    minimum_points: float,
    budget: float,
    rules: RosterRules,
    points_col: str = "projected_points",
    cost_col: str = "price",
    exclude: Iterable[str] | None = None,
    force_include: Iterable[str] | None = None,
    zero_cost_players: Iterable[str] | None = None,
    bench_slots_remaining: int | None = None,
) -> OptimizationResult:
    """Find the cheapest legal starter core that reaches a points floor."""
    df = players.copy()
    if exclude:
        df = df[~df["player"].isin(set(exclude))]
    df = df.dropna(subset=[points_col, cost_col, "position"]).reset_index(drop=True)
    if df.empty:
        return OptimizationResult(df, 0, 0, False, "No eligible players")

    bench_slots_remaining = rules.bench_count if bench_slots_remaining is None else bench_slots_remaining
    starter_budget = budget - max(0, bench_slots_remaining) * rules.min_bid
    n = len(df)
    pos = df["position"].to_numpy()
    constraints = []

    def add(row: np.ndarray, lb: float, ub: float) -> None:
        constraints.append(LinearConstraint(row, lb=lb, ub=ub))

    add(_constraint_row(pos, "QB"), rules.qb, rules.qb)
    add(_constraint_row(pos, "DST"), rules.dst, rules.dst)
    add(_constraint_row(pos, "K"), rules.k, rules.k)
    add(_constraint_row(pos, "RB"), rules.rb, np.inf)
    add(_constraint_row(pos, "WR"), rules.wr, np.inf)
    add(_constraint_row(pos, "TE"), rules.te, np.inf)
    add(np.isin(pos, list(OFFENSE_FLEX)).astype(float), rules.rb + rules.wr + rules.te + rules.flex, rules.rb + rules.wr + rules.te + rules.flex)
    add(np.ones(n), rules.starter_count, rules.starter_count)
    add(df[points_col].to_numpy(dtype=float), minimum_points, np.inf)

    budget_costs = df[cost_col].to_numpy(dtype=float).copy()
    zero_names = set(zero_cost_players or [])
    if zero_names:
        budget_costs[df["player"].isin(zero_names).to_numpy()] = 0.0
    add(budget_costs, -np.inf, starter_budget - rules.min_bid)

    for player in force_include or []:
        idx = np.flatnonzero(df["player"].to_numpy() == player)
        if len(idx) == 0:
            return OptimizationResult(df.iloc[0:0], 0, 0, False, f"Forced player unavailable: {player}")
        row = np.zeros(n)
        row[idx[0]] = 1
        add(row, 1, 1)

    result = milp(
        c=budget_costs,
        integrality=np.ones(n),
        bounds=Bounds(np.zeros(n), np.ones(n)),
        constraints=constraints,
        options={"time_limit": 10.0},
    )
    if not result.success or result.x is None:
        return OptimizationResult(df.iloc[0:0], 0, 0, False, result.message)
    chosen_mask = np.rint(result.x).astype(bool)
    chosen = df[chosen_mask].copy().sort_values(["position", points_col], ascending=[True, False])
    return OptimizationResult(
        selected=chosen,
        projected_points=float(chosen[points_col].sum()),
        total_cost=float(budget_costs[chosen_mask].sum()),
        success=True,
        message=result.message,
    )


@dataclass
class CompletionResult:
    active: pd.DataFrame
    acquisitions: pd.DataFrame
    projected_points: float
    required_budget: float
    success: bool
    message: str


@dataclass
class _CompletionProblem:
    available: pd.DataFrame
    owned: pd.DataFrame
    constraints: list[LinearConstraint]
    acquisition_costs: np.ndarray
    budget_coefficients: np.ndarray
    points_coefficients: np.ndarray
    stable_coefficients: np.ndarray
    x_slice: slice
    owned_active_slice: slice
    available_active_slice: slice
    variable_count: int
    roster_slots_remaining: int
    min_bid: int


def _empty_completion(message: str, available: pd.DataFrame | None = None) -> CompletionResult:
    columns = list(available.columns) if available is not None else []
    empty = pd.DataFrame(columns=columns)
    return CompletionResult(empty, empty.copy(), 0.0, 0.0, False, message)


def _completion_frame(
    frame: pd.DataFrame,
    required: tuple[str, ...],
    points_col: str,
    cost_col: str | None = None,
) -> pd.DataFrame:
    if frame.empty:
        columns = list(dict.fromkeys((*required, points_col, *((cost_col,) if cost_col else ()))))
        return pd.DataFrame(columns=columns)
    missing = [column for column in required if column not in frame.columns]
    if points_col not in frame.columns:
        missing.append(points_col)
    if cost_col and cost_col not in frame.columns:
        missing.append(cost_col)
    if missing:
        raise KeyError(f"Missing completion columns: {sorted(set(missing))}")
    out = frame.copy()
    out[points_col] = pd.to_numeric(out[points_col], errors="coerce")
    if cost_col:
        out[cost_col] = pd.to_numeric(out[cost_col], errors="coerce")
    subset = [*required, points_col, *((cost_col,) if cost_col else ())]
    out = out.dropna(subset=subset)
    out = out[out["position"].isin({"QB", "RB", "WR", "TE", "DST", "K"})]
    return out.sort_values("player_key", kind="stable").drop_duplicates("player_key").reset_index(drop=True)


def _build_completion_problem(
    available: pd.DataFrame,
    owned: pd.DataFrame,
    budget: float,
    roster_slots_remaining: int,
    position_capacity: Mapping[str, int],
    rules: RosterRules,
    points_col: str,
    cost_col: str,
    force_acquire: Iterable[str] = (),
    zero_cost: Iterable[str] = (),
) -> _CompletionProblem | CompletionResult:
    if roster_slots_remaining < 0:
        return _empty_completion("roster_slots_remaining cannot be negative", available)
    required = ("player_key", "player", "position")
    available_df = _completion_frame(available, required, points_col, cost_col)
    owned_df = _completion_frame(owned, required, points_col)
    if set(available_df.player_key) & set(owned_df.player_key):
        available_df = available_df[~available_df.player_key.isin(set(owned_df.player_key))].reset_index(drop=True)

    force_keys = tuple(dict.fromkeys(force_acquire))
    force_missing = set(force_keys) - set(available_df.player_key)
    if force_missing:
        return _empty_completion(
            f"Forced acquisition unavailable: {sorted(force_missing)[0]}",
            available_df,
        )
    if len(force_keys) > roster_slots_remaining:
        return _empty_completion("Forced acquisitions exceed remaining roster slots", available_df)

    n_available = len(available_df)
    n_owned = len(owned_df)
    variable_count = n_available + n_owned + n_available
    if variable_count == 0:
        return _empty_completion("No players available for roster completion", available_df)

    x_slice = slice(0, n_available)
    owned_active_slice = slice(n_available, n_available + n_owned)
    available_active_slice = slice(n_available + n_owned, variable_count)
    constraints: list[LinearConstraint] = []

    def add(row: np.ndarray, lower: float, upper: float) -> None:
        constraints.append(LinearConstraint(row, lb=lower, ub=upper))

    available_position = available_df.position.to_numpy()
    owned_position = owned_df.position.to_numpy()

    def acquisition_row(mask: np.ndarray | None = None) -> np.ndarray:
        row = np.zeros(variable_count)
        row[x_slice] = 1.0 if mask is None else mask.astype(float)
        return row

    def active_row(position: str | None = None, flex: bool = False) -> np.ndarray:
        row = np.zeros(variable_count)
        if position is None and not flex:
            row[owned_active_slice] = 1.0
            row[available_active_slice] = 1.0
        else:
            owned_mask = (
                np.isin(owned_position, list(OFFENSE_FLEX))
                if flex else owned_position == position
            )
            available_mask = (
                np.isin(available_position, list(OFFENSE_FLEX))
                if flex else available_position == position
            )
            row[owned_active_slice] = owned_mask.astype(float)
            row[available_active_slice] = available_mask.astype(float)
        return row

    for index in range(n_available):
        relation = np.zeros(variable_count)
        relation[available_active_slice.start + index] = 1.0
        relation[x_slice.start + index] = -1.0
        if available_df.iloc[index].player_key in force_keys:
            add(relation, -np.inf, 0.0)
        else:
            add(relation, 0.0, 0.0)

    add(acquisition_row(), -np.inf, float(roster_slots_remaining))
    for position in sorted(set(available_position)):
        add(
            acquisition_row(available_position == position),
            -np.inf,
            float(position_capacity.get(position, 0)),
        )
    for key in force_keys:
        index = int(available_df.index[available_df.player_key.eq(key)][0])
        row = np.zeros(variable_count)
        row[x_slice.start + index] = 1.0
        add(row, 1.0, 1.0)

    add(active_row("QB"), rules.qb, rules.qb)
    add(active_row("DST"), rules.dst, rules.dst)
    add(active_row("K"), rules.k, rules.k)
    add(active_row("RB"), rules.rb, np.inf)
    add(active_row("WR"), rules.wr, np.inf)
    add(active_row("TE"), rules.te, np.inf)
    flex_count = rules.rb + rules.wr + rules.te + rules.flex
    add(active_row(flex=True), flex_count, flex_count)
    add(active_row(), rules.starter_count, rules.starter_count)

    acquisition_costs = available_df[cost_col].to_numpy(dtype=float).copy()
    if np.any(acquisition_costs < rules.min_bid):
        invalid = available_df.loc[acquisition_costs < rules.min_bid, "player_key"].iloc[0]
        return _empty_completion(f"Market price below minimum bid: {invalid}", available_df)
    zero_keys = set(zero_cost)
    if zero_keys - set(force_keys):
        return _empty_completion("Zero-cost players must also be forced acquisitions", available_df)
    acquisition_costs[available_df.player_key.isin(zero_keys).to_numpy()] = 0.0
    budget_coefficients = np.zeros(variable_count)
    budget_coefficients[x_slice] = acquisition_costs - rules.min_bid
    reserve_budget = float(budget - rules.min_bid * roster_slots_remaining)
    add(budget_coefficients, -np.inf, reserve_budget)

    points_coefficients = np.zeros(variable_count)
    points_coefficients[owned_active_slice] = owned_df[points_col].to_numpy(dtype=float)
    points_coefficients[available_active_slice] = available_df[points_col].to_numpy(dtype=float)

    all_active_keys = [*owned_df.player_key.tolist(), *available_df.player_key.tolist()]
    rank = {key: index + 1 for index, key in enumerate(sorted(all_active_keys))}
    stable_coefficients = np.zeros(variable_count)
    stable_coefficients[x_slice] = [rank[key] / max(1, len(rank) + 1) for key in available_df.player_key]
    stable_coefficients[owned_active_slice] = [rank[key] for key in owned_df.player_key]
    stable_coefficients[available_active_slice] = [rank[key] for key in available_df.player_key]

    return _CompletionProblem(
        available=available_df,
        owned=owned_df,
        constraints=constraints,
        acquisition_costs=acquisition_costs,
        budget_coefficients=budget_coefficients,
        points_coefficients=points_coefficients,
        stable_coefficients=stable_coefficients,
        x_slice=x_slice,
        owned_active_slice=owned_active_slice,
        available_active_slice=available_active_slice,
        variable_count=variable_count,
        roster_slots_remaining=roster_slots_remaining,
        min_bid=rules.min_bid,
    )


def _solve_completion(
    problem: _CompletionProblem,
    objective: np.ndarray,
    extra_constraints: Iterable[LinearConstraint] = (),
):
    return milp(
        c=objective,
        integrality=np.ones(problem.variable_count),
        bounds=Bounds(
            np.zeros(problem.variable_count),
            np.ones(problem.variable_count),
        ),
        constraints=[*problem.constraints, *extra_constraints],
        options={"time_limit": 10.0},
    )


def _completion_result(
    problem: _CompletionProblem,
    solution,
    points_col: str,
) -> CompletionResult:
    if not solution.success or solution.x is None:
        return _empty_completion(solution.message, problem.available)
    selected = np.rint(solution.x).astype(bool)
    acquisitions_mask = selected[problem.x_slice]
    owned_active_mask = selected[problem.owned_active_slice]
    available_active_mask = selected[problem.available_active_slice]
    owned_active = problem.owned.loc[owned_active_mask].copy()
    available_active = problem.available.loc[available_active_mask].copy()
    if len(owned_active):
        owned_active["source"] = "owned"
    if len(available_active):
        available_active["source"] = "acquisition"
    active = pd.concat([owned_active, available_active], ignore_index=True, sort=False)
    if len(active):
        active = active.sort_values(["position", "player_key"], kind="stable").reset_index(drop=True)
    acquisitions = problem.available.loc[acquisitions_mask].copy()
    acquisitions = acquisitions.sort_values("player_key", kind="stable").reset_index(drop=True)
    acquisition_count = int(acquisitions_mask.sum())
    required_budget = float(
        problem.acquisition_costs[acquisitions_mask].sum()
        + problem.min_bid * (problem.roster_slots_remaining - acquisition_count)
    )
    return CompletionResult(
        active=active,
        acquisitions=acquisitions,
        projected_points=float(active[points_col].sum()) if len(active) else 0.0,
        required_budget=required_budget,
        success=True,
        message=solution.message,
    )


def _stable_minimum_solution(
    problem: _CompletionProblem,
    minimum_points: float,
):
    tolerance = 1e-7
    points_constraint = LinearConstraint(
        problem.points_coefficients,
        lb=minimum_points - tolerance,
        ub=np.inf,
    )
    cost_solution = _solve_completion(
        problem,
        problem.budget_coefficients,
        (points_constraint,),
    )
    if not cost_solution.success or cost_solution.x is None:
        return cost_solution
    minimum_variable_cost = float(problem.budget_coefficients @ cost_solution.x)
    cost_constraint = LinearConstraint(
        problem.budget_coefficients,
        lb=-np.inf,
        ub=minimum_variable_cost + tolerance,
    )
    stable = _solve_completion(
        problem,
        problem.stable_coefficients,
        (points_constraint, cost_constraint),
    )
    return stable if stable.success and stable.x is not None else cost_solution


def optimize_roster_completion(
    available: pd.DataFrame,
    owned: pd.DataFrame,
    budget: float,
    roster_slots_remaining: int,
    position_capacity: Mapping[str, int],
    rules: RosterRules,
    points_col: str = "projected_points",
    cost_col: str = "price",
) -> CompletionResult:
    problem = _build_completion_problem(
        available,
        owned,
        budget,
        roster_slots_remaining,
        position_capacity,
        rules,
        points_col,
        cost_col,
    )
    if isinstance(problem, CompletionResult):
        return problem
    points_solution = _solve_completion(problem, -problem.points_coefficients)
    if not points_solution.success or points_solution.x is None:
        return _empty_completion(points_solution.message, problem.available)
    maximum_points = float(problem.points_coefficients @ points_solution.x)
    stable_solution = _stable_minimum_solution(problem, maximum_points)
    return _completion_result(problem, stable_solution, points_col)


def minimum_cost_completion_for_points(
    available: pd.DataFrame,
    owned: pd.DataFrame,
    minimum_points: float,
    budget: float,
    roster_slots_remaining: int,
    position_capacity: Mapping[str, int],
    rules: RosterRules,
    points_col: str = "projected_points",
    cost_col: str = "price",
    force_acquire: Iterable[str] = (),
    zero_cost: Iterable[str] = (),
) -> CompletionResult:
    problem = _build_completion_problem(
        available,
        owned,
        budget,
        roster_slots_remaining,
        position_capacity,
        rules,
        points_col,
        cost_col,
        force_acquire,
        zero_cost,
    )
    if isinstance(problem, CompletionResult):
        return problem
    solution = _stable_minimum_solution(problem, minimum_points)
    return _completion_result(problem, solution, points_col)
