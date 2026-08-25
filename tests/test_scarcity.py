from __future__ import annotations

from auction_engine.draft_state import RosterEntry, Sale, replay_draft
from auction_engine.scarcity import calculate_scarcity
from tests.fixtures import league_rules, player_pool


def test_opponent_purchase_reduces_outstanding_league_demand():
    rules = league_rules()
    players = player_pool(per_position=8)
    empty = replay_draft(rules, {manager: () for manager in rules.managers}, ())
    after = replay_draft(
        rules,
        {manager: () for manager in rules.managers},
        (Sale("sale-1", "rb_00", "RB 00", "RB", "Manager_02", 10, 1),),
    )

    before_scarcity = calculate_scarcity(players, empty, rules, "Manager_01")
    after_scarcity = calculate_scarcity(players, after, rules, "Manager_01")

    assert "rb_00" in set(before_scarcity.selected_available.player_key)
    assert "rb_00" not in set(after_scarcity.selected_available.player_key)
    assert after_scarcity.outstanding_demand["ALL"] == before_scarcity.outstanding_demand["ALL"] - 1


def test_target_needs_are_separate_from_league_replacement_levels():
    rules = league_rules()
    keepers = {
        "Manager_01": (RosterEntry("rb_00", "RB 00", "RB", 10, "keeper"),),
        "Manager_02": (),
    }
    state = replay_draft(rules, keepers, ())

    scarcity = calculate_scarcity(player_pool(per_position=8), state, rules, "Manager_01")

    assert scarcity.target_needs["RB"] == 1
    assert scarcity.target_needs["FLEX"] == 2
    assert "RB" in scarcity.league_replacement_levels
    assert scarcity.outstanding_demand["ALL"] == 19


def test_full_roster_with_legal_starters_has_no_remaining_demand_for_manager():
    rules = league_rules(managers=("Manager_01",))
    starters = (
        RosterEntry("qb_00", "QB 00", "QB", 1, "keeper"),
        RosterEntry("rb_00", "RB 00", "RB", 1, "keeper"),
        RosterEntry("rb_01", "RB 01", "RB", 1, "keeper"),
        RosterEntry("rb_02", "RB 02", "RB", 1, "keeper"),
        RosterEntry("wr_00", "WR 00", "WR", 1, "keeper"),
        RosterEntry("wr_01", "WR 01", "WR", 1, "keeper"),
        RosterEntry("wr_02", "WR 02", "WR", 1, "keeper"),
        RosterEntry("te_00", "TE 00", "TE", 1, "keeper"),
        RosterEntry("dst_00", "DST 00", "DST", 1, "keeper"),
        RosterEntry("k_00", "K 00", "K", 1, "keeper"),
    )
    state = replay_draft(rules, {"Manager_01": starters}, ())

    scarcity = calculate_scarcity(player_pool(per_position=8), state, rules, "Manager_01")

    assert scarcity.outstanding_demand == {"ALL": 0}
    assert scarcity.selected_available.empty
    assert scarcity.target_needs == {"DST": 0, "FLEX": 0, "K": 0, "QB": 0, "RB": 0, "TE": 0, "WR": 0}


def test_scarcity_is_deterministic_when_equal_players_are_shuffled():
    rules = league_rules()
    players = player_pool(per_position=8)
    players["projected_points"] = players.groupby("position")["projected_points"].transform("max")
    state = replay_draft(rules, {manager: () for manager in rules.managers}, ())

    first = calculate_scarcity(players.sample(frac=1, random_state=1), state, rules, "Manager_01")
    second = calculate_scarcity(players.sample(frac=1, random_state=2), state, rules, "Manager_01")

    assert first.selected_available.player_key.tolist() == second.selected_available.player_key.tolist()
    assert first.league_replacement_levels == second.league_replacement_levels
