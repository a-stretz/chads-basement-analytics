from __future__ import annotations

from collections.abc import Iterable
import math

import pandas as pd

from .optimizer import RosterRules, minimum_cost_roster_for_points, optimize_starter_core


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
