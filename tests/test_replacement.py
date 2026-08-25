import pandas as pd

from auction_engine.optimizer import RosterRules
from auction_engine.replacement import league_replacement_levels


def test_flex_drives_league_replacement_pool():
    rows = []
    for pos, count, base in [("QB", 20, 300), ("RB", 50, 240), ("WR", 60, 230), ("TE", 25, 190), ("DST", 20, 120), ("K", 20, 100)]:
        for i in range(count):
            rows.append({"player": f"{pos}{i}", "position": pos, "projected_points": base - i})
    df = pd.DataFrame(rows)
    levels = league_replacement_levels(df, teams=10, rules=RosterRules())
    assert set(["QB", "RB", "WR", "TE", "DST", "K"]).issubset(levels)
    assert levels["RB"] < 240
    assert levels["WR"] < 230
