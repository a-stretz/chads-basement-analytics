from __future__ import annotations

import pandas as pd

from auction_engine.draft_state import LeagueRules, RosterEntry
from auction_engine.live_draft import DraftInputs, MarketBaseline


def league_rules(
    managers: tuple[str, ...] = ("Manager_01", "Manager_02"),
    position_max: dict[str, int] | None = None,
    roster_size: int = 10,
) -> LeagueRules:
    maxima = {"QB": 2, "RB": 5, "WR": 5, "TE": 3, "DST": 2, "K": 2}
    maxima.update(position_max or {})
    return LeagueRules(
        managers=managers,
        salary_cap=200,
        roster_size=roster_size,
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


def keeper_map(
    managers: tuple[str, ...] = ("Manager_01", "Manager_02"),
) -> dict[str, tuple[RosterEntry, ...]]:
    keepers = {manager: () for manager in managers}
    keepers[managers[0]] = (
        RosterEntry("rb_00", "RB 00", "RB", 2, "keeper"),
    )
    return keepers


def acceptance_inputs(top_n: int = 1) -> DraftInputs:
    managers = tuple(f"Manager_{index:02d}" for index in range(1, 11))
    rules = LeagueRules(
        managers=managers,
        salary_cap=200,
        roster_size=8,
        min_bid=1,
        starters={
            "QB": 1,
            "RB": 1,
            "WR": 1,
            "TE": 1,
            "FLEX": 0,
            "DST": 0,
            "K": 0,
        },
        position_max={"QB": 2, "RB": 3, "WR": 3, "TE": 2, "DST": 0, "K": 0},
    )
    players = player_pool(per_position=20)
    return DraftInputs(
        rules=rules,
        keepers={manager: () for manager in managers},
        players=players,
        target_manager=managers[0],
        market=MarketBaseline(
            initial_remaining_capital=float(len(managers) * rules.salary_cap),
            initial_remaining_baseline_value=float(players.normalized_aav.sum()),
        ),
        top_n=top_n,
    )


def legal_sale_sequence(count: int = 40) -> list[tuple[str, str, int]]:
    if not 0 <= count <= 50:
        raise ValueError("Synthetic sale count must be between 0 and 50")
    managers = tuple(f"Manager_{index:02d}" for index in range(1, 11))
    position_rounds = ("QB", "RB", "WR", "TE", "RB")
    position_offsets: dict[str, int] = {}
    sales: list[tuple[str, str, int]] = []
    for round_index, position in enumerate(position_rounds):
        offset = position_offsets.get(position, 0)
        for manager_index, manager in enumerate(managers):
            if len(sales) >= count:
                return sales
            player_index = offset + manager_index
            sales.append(
                (
                    f"{position.lower()}_{player_index:02d}",
                    manager,
                    2 + ((round_index + manager_index) % 3),
                )
            )
        position_offsets[position] = offset + len(managers)
    return sales
