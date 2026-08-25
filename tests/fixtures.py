from __future__ import annotations

import pandas as pd

from auction_engine.draft_state import LeagueRules


def league_rules(
    managers: tuple[str, ...] = ("Manager_01", "Manager_02"),
    position_max: dict[str, int] | None = None,
) -> LeagueRules:
    maxima = {"QB": 2, "RB": 5, "WR": 5, "TE": 3, "DST": 2, "K": 2}
    maxima.update(position_max or {})
    return LeagueRules(
        managers=managers,
        salary_cap=200,
        roster_size=10,
        min_bid=1,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "DST": 1, "K": 1},
        position_max=maxima,
        flex_eligible=("RB", "WR", "TE"),
    )


def player_pool(per_position: int = 12) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    bases = {"QB": 300.0, "RB": 240.0, "WR": 230.0, "TE": 190.0, "DST": 120.0, "K": 100.0}
    for position, base in bases.items():
        for index in range(per_position):
            key = f"{position.lower()}_{index:02d}"
            rows.append(
                {
                    "player_key": key,
                    "player": f"{position} {index:02d}",
                    "position": position,
                    "projected_points": base - index,
                    "normalized_aav": max(1.0, 30.0 - index),
                    "aav": max(1.0, 28.0 - index),
                }
            )
    return pd.DataFrame(rows)
