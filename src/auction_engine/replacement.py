from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from .optimizer import OFFENSE_FLEX, RosterRules


def league_replacement_levels(
    players: pd.DataFrame,
    teams: int,
    rules: RosterRules,
    points_col: str = "projected_points",
) -> dict[str, float]:
    """Infer replacement levels from the league-wide optimal starting pool."""
    df = players.dropna(subset=[points_col, "position"]).copy().reset_index(drop=True)
    n = len(df)
    pos = df["position"].to_numpy()
    constraints = []

    def add(row: np.ndarray, lb: float, ub: float) -> None:
        constraints.append(LinearConstraint(row, lb=lb, ub=ub))

    add((pos == "QB").astype(float), teams * rules.qb, teams * rules.qb)
    add((pos == "DST").astype(float), teams * rules.dst, teams * rules.dst)
    add((pos == "K").astype(float), teams * rules.k, teams * rules.k)
    add((pos == "RB").astype(float), teams * rules.rb, np.inf)
    add((pos == "WR").astype(float), teams * rules.wr, np.inf)
    add((pos == "TE").astype(float), teams * rules.te, np.inf)
    offense_n = teams * (rules.rb + rules.wr + rules.te + rules.flex)
    add(np.isin(pos, list(OFFENSE_FLEX)).astype(float), offense_n, offense_n)
    add(np.ones(n), teams * rules.starter_count, teams * rules.starter_count)

    result = milp(
        c=-df[points_col].to_numpy(dtype=float),
        integrality=np.ones(n),
        bounds=Bounds(np.zeros(n), np.ones(n)),
        constraints=constraints,
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"Replacement-level optimization failed: {result.message}")
    selected = df[np.rint(result.x).astype(bool)]
    levels = {}
    for p in ["QB", "RB", "WR", "TE", "DST", "K"]:
        vals = selected.loc[selected.position.eq(p), points_col]
        if len(vals):
            levels[p] = float(vals.min())
    return levels


def add_vor(players: pd.DataFrame, levels: dict[str, float], points_col: str = "projected_points") -> pd.DataFrame:
    out = players.copy()
    out["replacement_points"] = out["position"].map(levels)
    out["vor"] = out[points_col] - out["replacement_points"]
    return out
