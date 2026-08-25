from __future__ import annotations

import pandas as pd

from auction_engine.optimizer import (
    RosterRules,
    minimum_cost_completion_for_points,
    optimize_roster_completion,
)


def test_owned_bench_player_is_rostered_but_not_forced_to_start():
    rules = RosterRules(
        qb=1, rb=1, wr=1, te=0, flex=0, dst=0, k=0,
        roster_size=5, min_bid=1,
    )
    owned = pd.DataFrame(
        [
            {"player_key": "rb_low", "player": "RB Low", "position": "RB", "projected_points": 5.0},
            {"player_key": "rb_high", "player": "RB High", "position": "RB", "projected_points": 20.0},
        ]
    )
    available = pd.DataFrame(
        [
            {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 30.0, "price": 10.0},
            {"player_key": "wr_one", "player": "WR One", "position": "WR", "projected_points": 25.0, "price": 10.0},
        ]
    )

    result = optimize_roster_completion(
        available=available,
        owned=owned,
        budget=50,
        roster_slots_remaining=3,
        position_capacity={"QB": 2, "RB": 3, "WR": 2},
        rules=rules,
    )

    assert result.success
    assert set(result.active.player_key) == {"rb_high", "qb_one", "wr_one"}
    assert "rb_low" not in set(result.active.player_key)
    assert set(result.acquisitions.player_key) == {"qb_one", "wr_one"}
    assert result.required_budget == 21.0


def test_forced_candidate_may_be_bench_and_consumes_roster_slot():
    rules = RosterRules(
        qb=1, rb=1, wr=0, te=0, flex=0, dst=0, k=0,
        roster_size=3, min_bid=1,
    )
    owned = pd.DataFrame(
        [
            {"player_key": "rb_one", "player": "RB One", "position": "RB", "projected_points": 20.0},
        ]
    )
    available = pd.DataFrame(
        [
            {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 30.0, "price": 10.0},
            {"player_key": "rb_bench", "player": "RB Bench", "position": "RB", "projected_points": 1.0, "price": 1.0},
        ]
    )

    result = minimum_cost_completion_for_points(
        available=available,
        owned=owned,
        minimum_points=50.0,
        budget=20,
        roster_slots_remaining=2,
        position_capacity={"QB": 2, "RB": 2},
        rules=rules,
        force_acquire=("rb_bench",),
        zero_cost=("rb_bench",),
    )

    assert result.success
    assert set(result.acquisitions.player_key) == {"qb_one", "rb_bench"}
    assert "rb_bench" not in set(result.active.player_key)
    assert result.required_budget == 10.0


def test_exact_point_and_cost_ties_choose_stable_player_identity():
    rules = RosterRules(
        qb=1, rb=0, wr=0, te=0, flex=0, dst=0, k=0,
        roster_size=2, min_bid=1,
    )
    available = pd.DataFrame(
        [
            {"player_key": "qb_b", "player": "QB B", "position": "QB", "projected_points": 20.0, "price": 5.0},
            {"player_key": "qb_a", "player": "QB A", "position": "QB", "projected_points": 20.0, "price": 5.0},
        ]
    )

    selected: list[tuple[str, ...]] = []
    for seed in range(5):
        shuffled = available.sample(frac=1, random_state=seed)
        result = optimize_roster_completion(
            available=shuffled,
            owned=pd.DataFrame(),
            budget=20,
            roster_slots_remaining=2,
            position_capacity={"QB": 2},
            rules=rules,
        )
        selected.append(tuple(result.active.player_key))

    assert selected == [("qb_a",)] * 5


def test_remaining_budget_reserves_every_unfilled_roster_slot():
    rules = RosterRules(
        qb=1, rb=0, wr=0, te=0, flex=0, dst=0, k=0,
        roster_size=4, min_bid=1,
    )
    available = pd.DataFrame(
        [
            {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 20.0, "price": 8.0},
        ]
    )

    impossible = optimize_roster_completion(
        available, pd.DataFrame(), budget=10, roster_slots_remaining=4,
        position_capacity={"QB": 1}, rules=rules,
    )
    affordable = optimize_roster_completion(
        available, pd.DataFrame(), budget=11, roster_slots_remaining=4,
        position_capacity={"QB": 1}, rules=rules,
    )

    assert not impossible.success
    assert affordable.success
    assert affordable.required_budget == 11.0


def test_position_capacity_can_make_completion_infeasible():
    rules = RosterRules(
        qb=1, rb=0, wr=0, te=0, flex=0, dst=0, k=0,
        roster_size=2, min_bid=1,
    )
    available = pd.DataFrame(
        [
            {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 20.0, "price": 1.0},
        ]
    )

    result = optimize_roster_completion(
        available, pd.DataFrame(), budget=20, roster_slots_remaining=2,
        position_capacity={"QB": 0}, rules=rules,
    )

    assert not result.success
