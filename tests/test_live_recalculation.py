from __future__ import annotations

import pytest

from auction_engine.draft_state import LeagueRules, Sale
from auction_engine.live_draft import (
    DraftInputs,
    MarketBaseline,
    canonical_snapshot,
    recalculate_draft,
)
from tests.fixtures import keeper_map, league_rules, player_pool


def _inputs(top_n: int = 8) -> DraftInputs:
    managers = ("Manager_01", "Manager_02")
    rules = league_rules(managers=managers, roster_size=12)
    players = player_pool(per_position=12)
    keepers = keeper_map(managers)
    keeper_keys = {entry.player_key for entries in keepers.values() for entry in entries}
    initial_pool = players.loc[~players.player_key.isin(keeper_keys)]
    baseline = MarketBaseline(
        initial_remaining_capital=398.0,
        initial_remaining_baseline_value=float(initial_pool.normalized_aav.sum()),
    )
    return DraftInputs(
        rules=rules,
        keepers=keepers,
        players=players,
        target_manager="Manager_01",
        market=baseline,
        top_n=top_n,
    )


def test_opponent_purchase_recalculates_pool_market_scarcity_and_bid_board():
    inputs = _inputs()
    before = recalculate_draft(inputs, ())
    sale = Sale("sale-1", "rb_01", "RB 01", "RB", "Manager_02", 20, 1)

    after = recalculate_draft(inputs, (sale,))

    assert "rb_01" in set(before.available.player_key)
    assert "rb_01" not in set(after.available.player_key)
    assert after.state.managers["Manager_02"].budget_remaining == 180
    assert after.remaining_capital == before.remaining_capital - 20
    assert after.remaining_baseline_value == (
        before.remaining_baseline_value - 29.0
    )
    assert after.market_inflation != before.market_inflation
    assert (
        after.scarcity.outstanding_demand["ALL"]
        == before.scarcity.outstanding_demand["ALL"] - 1
    )

    before_bids = before.board.dropna(subset=["bid_up_to"]).set_index("player_key")["bid_up_to"]
    after_bids = after.board.dropna(subset=["bid_up_to"]).set_index("player_key")["bid_up_to"]
    common = before_bids.index.intersection(after_bids.index)
    assert len(common) > 0
    assert (before_bids.loc[common] != after_bids.loc[common]).any()


def test_target_purchase_is_charged_owned_and_may_be_benched():
    inputs = _inputs()
    sale = Sale("sale-1", "rb_11", "RB 11", "RB", "Manager_01", 5, 1)

    result = recalculate_draft(inputs, (sale,))

    target = result.state.managers["Manager_01"]
    assert target.budget_remaining == 193
    assert target.roster_slots_remaining == 10
    assert {entry.player_key for entry in target.roster} == {"rb_00", "rb_11"}
    assert "rb_11" not in set(result.target_lineup.active.player_key)
    assert "rb_11" not in set(result.available.player_key)


def test_recalculation_snapshot_is_canonical_across_input_order():
    inputs = _inputs(top_n=5)
    sales = (
        Sale("sale-1", "rb_01", "RB 01", "RB", "Manager_02", 20, 1),
        Sale("sale-2", "wr_01", "WR 01", "WR", "Manager_01", 9, 2),
    )
    shuffled_inputs = DraftInputs(
        rules=inputs.rules,
        keepers=inputs.keepers,
        players=inputs.players.sample(frac=1, random_state=42),
        target_manager=inputs.target_manager,
        market=inputs.market,
        top_n=inputs.top_n,
    )

    first = recalculate_draft(inputs, sales)
    second = recalculate_draft(shuffled_inputs, tuple(reversed(sales)))

    assert canonical_snapshot(first) == canonical_snapshot(second)


@pytest.mark.parametrize("k_required", [0, 1])
def test_unmodeled_dst_and_k_require_slots_without_projections(k_required: int):
    managers = ("Manager_01", "Manager_02")
    roster_size = 7 + k_required
    rules = LeagueRules(
        managers=managers,
        salary_cap=200,
        roster_size=roster_size,
        min_bid=1,
        starters={
            "QB": 1,
            "RB": 1,
            "WR": 1,
            "TE": 1,
            "FLEX": 0,
            "DST": 1,
            "K": k_required,
        },
        position_max={
            "QB": 2,
            "RB": 4,
            "WR": 4,
            "TE": 2,
            "DST": 3,
            "K": 3 if k_required else 0,
        },
        flex_eligible=("RB", "WR", "TE"),
        modeled_positions=("QB", "RB", "WR", "TE"),
    )
    players = player_pool(per_position=8)
    players = players.loc[players.position.isin(rules.modeled_positions)].copy()
    inputs = DraftInputs(
        rules=rules,
        keepers={manager: () for manager in managers},
        players=players,
        target_manager="Manager_01",
        market=MarketBaseline(400.0, float(players.normalized_aav.sum())),
        top_n=8,
    )

    result = recalculate_draft(inputs, ())
    target = result.state.managers["Manager_01"]

    assert set(result.board.position) == {"QB", "RB", "WR", "TE"}
    assert set(result.scarcity.league_replacement_levels) == {"QB", "RB", "WR", "TE"}
    assert set(result.target_lineup.active.position) == {"QB", "RB", "WR", "TE"}
    assert target.starter_needs["DST"] == 1
    assert target.starter_needs["K"] == k_required
    assert target.roster_slots_remaining == roster_size
    assert target.maximum_legal_bid == 200 - (roster_size - 1)

