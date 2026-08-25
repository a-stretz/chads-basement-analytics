from __future__ import annotations

import pandas as pd


def keeper_market_state(keepers: pd.DataFrame, teams: int = 10, cap: int = 200) -> dict[str, float]:
    active = keepers[keepers["status"].isin(["likely", "confirmed"]) & keepers["player"].notna()]
    keeper_spend = float(active["keeper_cost"].sum())
    return {
        "league_capital": float(teams * cap),
        "keeper_count": float(len(active)),
        "keeper_spend": keeper_spend,
        "remaining_capital": float(teams * cap - keeper_spend),
    }


def historical_capital_deployment(history: pd.DataFrame, teams: int = 10, cap: int = 200, seasons: int = 5) -> float:
    annual = history.groupby("season")["cost"].sum().sort_index().tail(seasons)
    if annual.empty:
        return 1.0
    return float((annual / (teams * cap)).mean())


def effective_remaining_capital(league_capital: float, keeper_spend: float, deployment_ratio: float = 1.0) -> float:
    return max(0.0, league_capital * deployment_ratio - keeper_spend)


def market_inflation(remaining_budget: float, remaining_baseline_value: float) -> float:
    if remaining_baseline_value <= 0:
        raise ValueError("remaining_baseline_value must be positive")
    return remaining_budget / remaining_baseline_value


def apply_inflation(players: pd.DataFrame, factor: float, source_col: str = "aav") -> pd.DataFrame:
    out = players.copy()
    out["inflated_aav"] = (out[source_col].fillna(1).clip(lower=1) * factor).round(1)
    return out
