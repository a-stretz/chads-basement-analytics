from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

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
