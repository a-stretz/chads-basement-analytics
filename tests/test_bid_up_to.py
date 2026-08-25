import pandas as pd

from auction_engine.bid_up_to import bid_up_to
from auction_engine.optimizer import RosterRules, optimize_starter_core


def _players():
    rows = []
    for pos, count, base in [("QB", 3, 250), ("RB", 8, 220), ("WR", 8, 215), ("TE", 5, 180), ("DST", 3, 120), ("K", 3, 100)]:
        for i in range(count):
            rows.append({"player": f"{pos}{i}", "position": pos, "projected_points": base - i * 5, "inflated_aav": 5 + i})
    return pd.DataFrame(rows)


def test_bid_up_to_returns_affordable_threshold():
    value = bid_up_to(_players(), "RB0", budget=200, rules=RosterRules())
    assert isinstance(value, int)
    assert 1 <= value <= 194


def test_direct_bid_ceiling_matches_opportunity_cost_threshold():
    df = _players()
    candidate = "RB0"
    rules = RosterRules()
    ceiling = bid_up_to(df, candidate, budget=200, rules=rules)

    priced = df.copy()
    priced["price"] = priced["inflated_aav"]
    alternative = optimize_starter_core(priced, budget=200, rules=rules, cost_col="price", exclude=[candidate])
    assert alternative.success

    priced.loc[priced.player.eq(candidate), "price"] = ceiling
    at_ceiling = optimize_starter_core(priced, budget=200, rules=rules, cost_col="price", force_include=[candidate])
    assert at_ceiling.success
    assert at_ceiling.projected_points >= alternative.projected_points

    priced.loc[priced.player.eq(candidate), "price"] = ceiling + 1
    above = optimize_starter_core(priced, budget=200, rules=rules, cost_col="price", force_include=[candidate])
    assert (not above.success) or above.projected_points < alternative.projected_points
