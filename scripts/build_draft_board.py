from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auction_engine.bid_up_to import add_bid_up_to
from auction_engine.market import effective_remaining_capital, historical_capital_deployment, keeper_market_state, market_inflation
from auction_engine.optimizer import RosterRules
from auction_engine.replacement import add_vor, league_replacement_levels


def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    raise KeyError(f"None of these columns found: {candidates}")


def derive_aav(df: pd.DataFrame) -> pd.Series:
    direct = [c for c in df.columns if c.lower() in {"aav", "aav_avg", "average_aav"}]
    if direct:
        return pd.to_numeric(df[direct[0]], errors="coerce")
    aav_cols = [c for c in df.columns if "aav" in c.lower()]
    if aav_cols:
        numeric = df[aav_cols].apply(pd.to_numeric, errors="coerce")
        return numeric.mean(axis=1, skipna=True)
    return pd.Series(1.0, index=df.index)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projections", default=str(ROOT / "data/processed/projections_2026.csv"))
    parser.add_argument("--config", default=str(ROOT / "config/cbxii.yaml"))
    parser.add_argument("--keepers", default=str(ROOT / "data/private/provisional_keepers_2026.csv"))
    parser.add_argument("--target-manager", default="Stretz")
    parser.add_argument("--top-n", type=int, default=120)
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    projections = pd.read_csv(args.projections)
    keepers = pd.read_csv(args.keepers)

    aggregate = cfg.get("model", {}).get("projection_aggregate", "average")
    if "avg_type" in projections.columns:
        projections = projections[projections["avg_type"].eq(aggregate)].copy()
        if projections.empty:
            raise ValueError(f"Projection aggregate {aggregate!r} not found in avg_type")

    if "player" not in projections.columns and {"first_name", "last_name"}.issubset(projections.columns):
        projections["player"] = (projections["first_name"].fillna("") + " " + projections["last_name"].fillna("")).str.strip()

    player_col = find_column(projections, ["player", "player_name", "name"])
    pos_col = find_column(projections, ["position", "pos"])
    pts_col = find_column(projections, ["points", "projected_points", "avg_points", "average"])
    players = projections.rename(columns={player_col: "player", pos_col: "position", pts_col: "projected_points"}).copy()
    players["projected_points"] = pd.to_numeric(players["projected_points"], errors="coerce")
    players["aav"] = derive_aav(players).fillna(1).clip(lower=1)
    players["position"] = players["position"].replace({"D/ST": "DST", "DEF": "DST"})
    players = players.drop_duplicates(["player", "position"]).copy()

    active_keepers = keepers[keepers.status.isin(["likely", "confirmed"]) & keepers.player.notna()].copy()
    own = active_keepers[active_keepers.manager.eq(args.target_manager)]
    own_names = set(own.player)
    other_names = set(active_keepers.loc[~active_keepers.manager.eq(args.target_manager), "player"])

    pool = players[~players.player.isin(other_names)].copy()
    pool["inflated_aav"] = pool["aav"].astype(float)

    market = keeper_market_state(keepers, teams=cfg["league"]["teams"], cap=cfg["league"]["salary_cap"])
    history_path = ROOT / "data/processed/historical_transactions.csv"
    deployment = 1.0
    if history_path.exists():
        history = pd.read_csv(history_path)
        deployment = historical_capital_deployment(history, teams=cfg["league"]["teams"], cap=cfg["league"]["salary_cap"], seasons=5)
    effective_capital = effective_remaining_capital(market["league_capital"], market["keeper_spend"], deployment)
    remaining_roster_slots = cfg["league"]["teams"] * cfg["league"]["roster_size"] - int(market["keeper_count"])
    auction_only = pool[~pool.player.isin(own_names)].nlargest(min(remaining_roster_slots, len(pool)), "aav")
    baseline = auction_only["aav"].fillna(1).clip(lower=1).sum()
    factor = market_inflation(effective_capital, baseline)
    pool.loc[~pool.player.isin(own_names), "inflated_aav"] = (pool.loc[~pool.player.isin(own_names), "aav"] * factor).clip(lower=1).round(1)
    for _, keeper in own.iterrows():
        pool.loc[pool.player.eq(keeper.player), "inflated_aav"] = keeper.keeper_cost

    s = cfg["starters"]
    rules = RosterRules(
        qb=s["QB"], rb=s["RB"], wr=s["WR"], te=s["TE"], flex=s["FLEX"],
        dst=s["DST"], k=s["K"], roster_size=cfg["league"]["roster_size"], min_bid=cfg["league"]["min_bid"]
    )
    levels = league_replacement_levels(players[~players.player.isin(set(active_keepers.player))], cfg["league"]["teams"], rules)
    pool = add_vor(pool, levels)
    board = add_bid_up_to(
        pool,
        budget=cfg["league"]["salary_cap"],
        rules=rules,
        top_n=args.top_n,
        always_force=own_names,
        exclude_from_output=own_names,
    )
    board["surplus_vs_inflated_aav"] = board["bid_up_to"] - board["inflated_aav"]
    board["keeper_locked"] = board.player.isin(own_names)
    board = board[~board.keeper_locked].sort_values(["bid_up_to", "vor", "projected_points"], ascending=False)
    out = ROOT / "data/processed/draft_board_2026.csv"
    board.to_csv(out, index=False)
    print(f"keeper_spend=${market['keeper_spend']:.0f}; remaining_capital=${market['remaining_capital']:.0f}; effective_capital=${effective_capital:.1f}; deployment={deployment:.4f}; market_factor={factor:.3f}")
    print(f"target_manager={args.target_manager}; own_keeper={','.join(own_names) if own_names else 'none'}")
    print("replacement_levels=" + ", ".join(f"{k}:{v:.1f}" for k, v in levels.items()))
    print(f"Wrote {len(board):,} rows to {out}")


if __name__ == "__main__":
    main()
