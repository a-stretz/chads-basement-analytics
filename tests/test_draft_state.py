from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from auction_engine.draft_state import (
    DraftValidationError,
    RosterEntry,
    Sale,
    replay_draft,
)
from auction_engine.live_draft import league_rules_from_mapping
from tests.fixtures import league_rules


def test_replay_counts_keeper_and_sale_in_budget_roster_and_needs():
    rules = league_rules()
    keeper = RosterEntry("rb_keeper", "RB Keeper", "RB", 12, "keeper")
    sale = Sale("sale-1", "wr_one", "WR One", "WR", "Manager_01", 31, 1)

    state = replay_draft(
        rules,
        {"Manager_01": (keeper,), "Manager_02": ()},
        (sale,),
    )
    manager = state.managers["Manager_01"]

    assert manager.budget_remaining == 157
    assert manager.roster_slots_remaining == 8
    assert manager.position_counts == {"RB": 1, "WR": 1}
    assert manager.maximum_legal_bid == 150
    assert manager.starter_needs["RB"] == 1
    assert manager.starter_needs["WR"] == 1
    assert manager.flex_need == 2


@pytest.mark.parametrize("price", [0, 200])
def test_replay_rejects_price_outside_legal_bid_range(price: int):
    rules = league_rules(managers=("Manager_01",))
    sale = Sale("sale-1", "qb_one", "QB One", "QB", "Manager_01", price, 1)

    with pytest.raises(DraftValidationError) as error:
        replay_draft(rules, {"Manager_01": ()}, (sale,))

    assert error.value.code in {"below_minimum_bid", "above_maximum_bid"}
    assert error.value.sale_id == "sale-1"


def test_replay_rejects_player_already_owned_by_another_manager():
    rules = league_rules()
    first = Sale("sale-1", "qb_one", "QB One", "QB", "Manager_01", 5, 1)
    duplicate = Sale("sale-2", "qb_one", "QB One", "QB", "Manager_02", 6, 2)

    with pytest.raises(DraftValidationError, match="already owned") as error:
        replay_draft(rules, {"Manager_01": (), "Manager_02": ()}, (first, duplicate))

    assert error.value.code == "duplicate_player"
    assert error.value.sale_id == "sale-2"


def test_replay_rejects_position_maximum_overflow():
    rules = league_rules(position_max={"QB": 1})
    first = Sale("sale-1", "qb_one", "QB One", "QB", "Manager_01", 5, 1)
    overflow = Sale("sale-2", "qb_two", "QB Two", "QB", "Manager_01", 5, 2)

    with pytest.raises(DraftValidationError, match="position maximum") as error:
        replay_draft(rules, {"Manager_01": (), "Manager_02": ()}, (first, overflow))

    assert error.value.code == "position_maximum"


def test_extra_flex_eligible_players_fill_flex_before_becoming_bench():
    rules = league_rules()
    keepers = {
        "Manager_01": (
            RosterEntry("rb_1", "RB 1", "RB", 2, "keeper"),
            RosterEntry("rb_2", "RB 2", "RB", 3, "keeper"),
            RosterEntry("rb_3", "RB 3", "RB", 4, "keeper"),
            RosterEntry("wr_1", "WR 1", "WR", 5, "keeper"),
            RosterEntry("wr_2", "WR 2", "WR", 6, "keeper"),
        ),
        "Manager_02": (),
    }

    manager = replay_draft(rules, keepers, ()).managers["Manager_01"]

    assert manager.starter_needs["RB"] == 0
    assert manager.starter_needs["WR"] == 0
    assert manager.flex_need == 1


@pytest.mark.parametrize("k_required, expected_max", [(0, 0), (1, 3)])
def test_k_starter_switch_controls_legal_position_capacity(
    k_required: int,
    expected_max: int,
):
    config = {
        "league": {
            "teams": 1,
            "salary_cap": 200,
            "roster_size": 8,
            "min_bid": 1,
        },
        "starters": {
            "QB": 1,
            "RB": 1,
            "WR": 1,
            "TE": 1,
            "FLEX": 0,
            "DST": 1,
            "K": k_required,
        },
        "position_max": {"QB": 2, "RB": 4, "WR": 4, "TE": 2, "DST": 3, "K": 3},
        "flex_eligible": ["RB", "WR", "TE"],
        "model": {"modeled_positions": ["QB", "RB", "WR", "TE"]},
    }

    rules = league_rules_from_mapping(config, ("Manager_01",))
    manager = replay_draft(rules, {"Manager_01": ()}, ()).managers["Manager_01"]

    assert manager.position_capacity["K"] == expected_max
    assert manager.starter_needs["K"] == k_required
    assert rules.modeled_roster_rules().k == 0
    assert rules.modeled_roster_rules().dst == 0


def test_public_config_keeps_dst_and_k_legal_but_unmodeled():
    config = yaml.safe_load(Path("config/cbxii.yaml").read_text(encoding="utf-8"))
    managers = tuple(f"Manager_{index:02d}" for index in range(1, 11))

    rules = league_rules_from_mapping(config, managers)

    assert rules.modeled_positions == ("QB", "RB", "WR", "TE")
    assert rules.roster_rules().dst == 1
    assert rules.roster_rules().k == 1
    assert rules.modeled_roster_rules().dst == 0
    assert rules.modeled_roster_rules().k == 0

