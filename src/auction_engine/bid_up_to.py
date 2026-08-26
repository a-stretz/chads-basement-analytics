from __future__ import annotations

from collections.abc import Iterable, Mapping
import math

import pandas as pd

from .optimizer import (
    RosterRules,
    minimum_cost_completion_for_points,
    minimum_cost_roster_for_points,
    optimize_roster_completion,
    optimize_starter_core,
)


def bid_up_to_remaining(
    available: pd.DataFrame,
    candidate_key: str,
    owned: pd.DataFrame,
    budget: float,
    roster_slots_remaining: int,
    position_capacity: Mapping[str, int],
    rules: RosterRules,
    market_price_col: str = "inflated_aav",
    points_col: str = "projected_points",
    maximum_legal_bid: int | None = None,
) -> int:
    """Opportunity-cost ceiling for the target manager's remaining roster."""
    if candidate_key not in set(available["player_key"]):
        raise KeyError(candidate_key)

    working = available.copy()
    working["market_price"] = (
        pd.to_numeric(working[market_price_col], errors="coerce")
        .fillna(rules.min_bid)
        .clip(lower=rules.min_bid)
    )
    alternative = optimize_roster_completion(
        available=working.loc[~working.player_key.eq(candidate_key)],
        owned=owned,
        budget=budget,
        roster_slots_remaining=roster_slots_remaining,
        position_capacity=position_capacity,
        rules=rules,
        points_col=points_col,
        cost_col="market_price",
    )
    minimum_points = alternative.projected_points if alternative.success else -1e18

    qualifying = minimum_cost_completion_for_points(
        available=working,
        owned=owned,
        minimum_points=minimum_points,
        budget=budget,
        roster_slots_remaining=roster_slots_remaining,
        position_capacity=position_capacity,
        rules=rules,
        points_col=points_col,
        cost_col="market_price",
        force_acquire=(candidate_key,),
        zero_cost=(candidate_key,),
    )
    if not qualifying.success:
        return 0

    ceiling = math.floor(budget - qualifying.required_budget + 1e-9)
    if maximum_legal_bid is not None:
        ceiling = min(ceiling, maximum_legal_bid)
    return max(0, ceiling)


def bid_up_to(
    players: pd.DataFrame,
    player_name: str,
    budget: float,
    rules: RosterRules,
    market_price_col: str = "inflated_aav",
    points_col: str = "projected_points",
    always_force: Iterable[str] | None = None,
) -> int:
    """Exact starter-core bid ceiling via opportunity cost."""
    if player_name not in set(players["player"]):
        raise KeyError(player_name)
    always_force = list(always_force or [])

    working = players.copy()
    working["market_price"] = working[market_price_col].fillna(1).clip(lower=1)

    alternative = optimize_starter_core(
        working,
        budget=budget,
        rules=rules,
        points_col=points_col,
        cost_col="market_price",
        exclude=[player_name],
        force_include=always_force,
    )
    minimum_points = alternative.projected_points if alternative.success else -1e18

    forced = list(dict.fromkeys(always_force + [player_name]))
    qualifying = minimum_cost_roster_for_points(
        working,
        minimum_points=minimum_points,
        budget=budget,
        rules=rules,
        points_col=points_col,
        cost_col="market_price",
        force_include=forced,
        zero_cost_players=[player_name],
    )
    if not qualifying.success:
        return 0

    starter_budget = budget - rules.bench_count * rules.min_bid
    ceiling = math.floor(starter_budget - qualifying.total_cost + 1e-9)
    return max(0, ceiling)


def add_bid_up_to(
    players: pd.DataFrame,
    budget: float,
    rules: RosterRules,
    top_n: int = 80,
    market_price_col: str = "inflated_aav",
    points_col: str = "projected_points",
    always_force: Iterable[str] | None = None,
    exclude_from_output: Iterable[str] | None = None,
) -> pd.DataFrame:
    out = players.copy()
    excluded = set(exclude_from_output or [])
    candidate_df = out[~out.player.isin(excluded)]
    rank_col = "vor" if "vor" in candidate_df.columns else points_col
    candidates = candidate_df.nlargest(min(top_n, len(candidate_df)), rank_col)["player"].tolist()
    values = {
        p: bid_up_to(
            out,
            p,
            budget,
            rules,
            market_price_col=market_price_col,
            points_col=points_col,
            always_force=always_force,
        )
        for p in candidates
    }
    out["bid_up_to"] = out["player"].map(values)
    return out
