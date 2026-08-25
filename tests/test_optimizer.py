import pandas as pd

from auction_engine.optimizer import RosterRules, optimize_starter_core


def test_optimizer_respects_flex_and_budget():
    rows = []
    for pos, count, base in [("QB", 3, 250), ("RB", 8, 220), ("WR", 8, 215), ("TE", 5, 180), ("DST", 3, 120), ("K", 3, 100)]:
        for i in range(count):
            rows.append({"player": f"{pos}{i}", "position": pos, "projected_points": base - i * 5, "price": 10 + i})
    df = pd.DataFrame(rows)
    rules = RosterRules()
    result = optimize_starter_core(df, budget=200, rules=rules, bench_slots_remaining=6)
    assert result.success
    assert len(result.selected) == 10
    assert result.total_cost <= 194
    pos = result.selected.position.value_counts().to_dict()
    assert pos.get("QB", 0) == 1
    assert pos.get("DST", 0) == 1
    assert pos.get("K", 0) == 1
    assert pos.get("RB", 0) >= 2
    assert pos.get("WR", 0) >= 2
    assert pos.get("TE", 0) >= 1
    assert pos.get("RB", 0) + pos.get("WR", 0) + pos.get("TE", 0) == 7
