from __future__ import annotations

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
