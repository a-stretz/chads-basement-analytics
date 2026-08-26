from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from .draft_state import LeagueDraftState, LeagueRules


FLEX_POSITIONS = ("RB", "WR", "TE")
KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")


@dataclass(frozen=True)
class ScarcityResult:
    league_replacement_levels: dict[str, float]
    outstanding_demand: dict[str, int]
    target_needs: dict[str, int]
    selected_available: pd.DataFrame


class ScarcityError(RuntimeError):
    pass


def _prepared_players(
    players: pd.DataFrame,
    points_col: str,
    modeled_positions: tuple[str, ...],
) -> pd.DataFrame:
    required = {"player_key", "player", "position", points_col}
    missing = required - set(players.columns)
    if missing:
        raise ScarcityError(f"Missing scarcity columns: {sorted(missing)}")
    pool = players.copy()
    pool[points_col] = pd.to_numeric(pool[points_col], errors="coerce")
    pool = pool.dropna(subset=["player_key", "player", "position", points_col])
    pool = pool[pool.position.isin(modeled_positions)]
    pool = pool.sort_values("player_key", kind="stable").reset_index(drop=True)
    duplicates = pool.loc[pool.player_key.duplicated(), "player_key"]
    if len(duplicates):
        raise ScarcityError(f"Duplicate player identity: {duplicates.iloc[0]}")
    return pool


def _solve_assignment_matrix(
    pool: pd.DataFrame,
    state: LeagueDraftState,
    rules: LeagueRules,
    managers: tuple[str, ...],
    points_col: str,
) -> np.ndarray:
    manager_count = len(managers)
    player_count = len(pool)
    variable_count = manager_count * player_count
    if variable_count == 0:
        if rules.roster_rules().starter_count:
            raise ScarcityError("No players available for league scarcity")
        return np.zeros((manager_count, player_count), dtype=bool)

    player_keys = pool.player_key.to_numpy()
    positions = pool.position.to_numpy()
    points = pool[points_col].to_numpy(dtype=float)
    owned_by: dict[str, str] = {}
    modeled = set(rules.modeled_positions)
    for manager, manager_state in state.managers.items():
        for entry in manager_state.roster:
            if entry.position in modeled:
                owned_by[entry.player_key] = manager
    missing_owned = sorted(set(owned_by) - set(player_keys))
    if missing_owned:
        raise ScarcityError(f"Owned player missing from projections: {missing_owned[0]}")
    available_mask = ~np.isin(player_keys, list(state.owned_player_keys))

    lower_bounds = np.zeros(variable_count)
    upper_bounds = np.zeros(variable_count)
    for manager_index, manager in enumerate(managers):
        start = manager_index * player_count
        for player_index, key in enumerate(player_keys):
            owner = owned_by.get(str(key))
            if owner is None or owner == manager:
                upper_bounds[start + player_index] = 1.0

    constraints: list[LinearConstraint] = []

    def add(row: np.ndarray, lower: float, upper: float) -> None:
        constraints.append(LinearConstraint(row, lb=lower, ub=upper))

    def manager_row(manager_index: int, mask: np.ndarray | None = None) -> np.ndarray:
        row = np.zeros(variable_count)
        start = manager_index * player_count
        row[start:start + player_count] = 1.0 if mask is None else mask.astype(float)
        return row

    for player_index, is_available in enumerate(available_mask):
        if not is_available:
            continue
        row = np.zeros(variable_count)
        for manager_index in range(manager_count):
            row[manager_index * player_count + player_index] = 1.0
        add(row, -np.inf, 1.0)

    roster_rules = rules.modeled_roster_rules()
    for manager_index, manager in enumerate(managers):
        manager_state = state.managers[manager]
        add(manager_row(manager_index, positions == "QB"), roster_rules.qb, roster_rules.qb)
        add(manager_row(manager_index, positions == "DST"), roster_rules.dst, roster_rules.dst)
        add(manager_row(manager_index, positions == "K"), roster_rules.k, roster_rules.k)
        add(manager_row(manager_index, positions == "RB"), roster_rules.rb, np.inf)
        add(manager_row(manager_index, positions == "WR"), roster_rules.wr, np.inf)
        add(manager_row(manager_index, positions == "TE"), roster_rules.te, np.inf)
        flex_count = roster_rules.rb + roster_rules.wr + roster_rules.te + roster_rules.flex
        add(manager_row(manager_index, np.isin(positions, FLEX_POSITIONS)), flex_count, flex_count)
        add(manager_row(manager_index), roster_rules.starter_count, roster_rules.starter_count)
        add(
            manager_row(manager_index, available_mask),
            -np.inf,
            float(manager_state.roster_slots_remaining),
        )
        for position in rules.modeled_positions:
            add(
                manager_row(manager_index, available_mask & (positions == position)),
                -np.inf,
                float(manager_state.position_capacity.get(position, 0)),
            )

    points_coefficients = np.tile(points, manager_count)
    primary = milp(
        c=-points_coefficients,
        integrality=np.ones(variable_count),
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=constraints,
        options={"time_limit": 10.0},
    )
    if not primary.success or primary.x is None:
        raise ScarcityError(f"League scarcity optimization failed: {primary.message}")
    maximum_points = float(points_coefficients @ primary.x)
    points_constraint = LinearConstraint(
        points_coefficients,
        lb=maximum_points - 1e-7,
        ub=np.inf,
    )
    stable_coefficients = np.zeros(variable_count)
    for manager_index in range(manager_count):
        start = manager_index * player_count
        stable_coefficients[start:start + player_count] = (
            np.arange(1, player_count + 1, dtype=float) * (manager_count + 1)
            + manager_index
        )
    stable = milp(
        c=stable_coefficients,
        integrality=np.ones(variable_count),
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=[*constraints, points_constraint],
        options={"time_limit": 10.0},
    )
    solution = stable if stable.success and stable.x is not None else primary
    return np.rint(solution.x).astype(bool).reshape(manager_count, player_count)


def calculate_scarcity(
    players: pd.DataFrame,
    state: LeagueDraftState,
    rules: LeagueRules,
    target_manager: str,
    points_col: str = "projected_points",
) -> ScarcityResult:
    if target_manager not in state.managers:
        raise ScarcityError(f"Unknown target manager: {target_manager}")
    managers = tuple(sorted(state.managers))
    pool = _prepared_players(players, points_col, rules.modeled_positions)
    assignment = _solve_assignment_matrix(pool, state, rules, managers, points_col)
    selected_mask = (
        assignment.any(axis=0)
        & ~pool.player_key.isin(state.owned_player_keys).to_numpy()
    )
    selected = pool.loc[selected_mask].copy()
    selected = selected.sort_values("player_key", kind="stable").reset_index(drop=True)
    levels = {
        position: float(group[points_col].min())
        for position, group in selected.groupby("position", sort=True)
    }
    outstanding = selected.position.value_counts().sort_index().astype(int).to_dict()
    outstanding["ALL"] = int(len(selected))
    target = state.managers[target_manager]
    target_needs = {
        position: count
        for position, count in target.starter_needs.items()
        if position in rules.modeled_positions
    }
    target_needs["FLEX"] = target.flex_need
    target_needs = dict(sorted(target_needs.items()))
    return ScarcityResult(
        league_replacement_levels=levels,
        outstanding_demand=outstanding,
        target_needs=target_needs,
        selected_available=selected,
    )

