from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auction_engine.live_draft import (
    DraftInputs,
    MarketBaseline,
    RecalculationResult,
    _keeper_entries_by_manager,
    league_rules_from_mapping,
    normalize_player_key,
    recalculate_draft,
)
from auction_engine.market import effective_remaining_capital, historical_capital_deployment, keeper_market_state, market_inflation


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


def write_live_artifacts(
    inputs: DraftInputs,
    output_dir: str | Path,
    draft_id: str = "cbxii-2026",
) -> RecalculationResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = recalculate_draft(inputs, ())
    inputs.players.to_csv(output / "draft_pool_2026.csv", index=False)
    context = {
        "draft_id": draft_id,
        "target_manager": inputs.target_manager,
        "initial_remaining_capital": inputs.market.initial_remaining_capital,
        "initial_remaining_baseline_value": (
            inputs.market.initial_remaining_baseline_value
        ),
        "top_n": inputs.top_n,
    }
    (output / "draft_context_2026.json").write_text(
        json.dumps(context, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    board = result.board.copy()
    board["surplus_vs_inflated_aav"] = board["bid_up_to"] - board["inflated_aav"]
    board.to_csv(output / "draft_board_2026.csv", index=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projections", default=str(ROOT / "data/processed/projections_2026.csv"))
    parser.add_argument("--config", default=str(ROOT / "config/cbxii.yaml"))
    parser.add_argument("--keepers", default=str(ROOT / "data/private/provisional_keepers_2026.csv"))
    parser.add_argument("--target-manager", required=True)
    parser.add_argument("--top-n", type=int, default=120)
    parser.add_argument("--draft-id", default="cbxii-2026")
    parser.add_argument("--output-dir", default=str(ROOT / "data/processed"))
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

    players["player_key"] = players["player"].map(normalize_player_key)
    keepers["player_key"] = keepers["player"].map(normalize_player_key)
    active_keepers = keepers[keepers.status.isin(["likely", "confirmed"]) & keepers.player.notna()].copy()
    managers = tuple(keepers.manager.dropna().astype(str).drop_duplicates())
    rules = league_rules_from_mapping(cfg, managers)
    if args.target_manager not in managers:
        raise ValueError(f"Target manager not found in keeper input: {args.target_manager}")

    # Normalize public AAV to this league's actual auction economy before measuring
    # keeper inflation. Public AAV sums are not guaranteed to equal 10 x $200.
    market = keeper_market_state(keepers, teams=cfg["league"]["teams"], cap=cfg["league"]["salary_cap"])
    history_path = ROOT / "data/processed/historical_transactions.csv"
    deployment = 1.0
    if history_path.exists():
        history = pd.read_csv(history_path)
        deployment = historical_capital_deployment(history, teams=cfg["league"]["teams"], cap=cfg["league"]["salary_cap"], seasons=5)

    target_league_spend = market["league_capital"] * deployment
    full_roster_slots = cfg["league"]["teams"] * cfg["league"]["roster_size"]
    baseline_pool = players.nlargest(min(full_roster_slots, len(players)), "aav")
    raw_aav_total = baseline_pool["aav"].fillna(1).clip(lower=1).sum()
    aav_normalization = target_league_spend / raw_aav_total
    players["normalized_aav"] = players["aav"] * aav_normalization

    active_keys = set(active_keepers.player_key)
    keeper_market_value = players.loc[players.player_key.isin(active_keys), "normalized_aav"].sum()
    if len(active_keys) != players.loc[players.player_key.isin(active_keys), "player_key"].nunique():
        matched = set(players.loc[players.player_key.isin(active_keys), "player_key"])
        missing = active_keys - matched
        raise ValueError(f"Could not match keeper(s) to projections: {sorted(missing)}")

    remaining_baseline_value = target_league_spend - keeper_market_value
    effective_capital = effective_remaining_capital(market["league_capital"], market["keeper_spend"], deployment)
    keeper_inflation = market_inflation(effective_capital, remaining_baseline_value)

    keeper_entries = _keeper_entries_by_manager(active_keepers, managers, players)
    inputs = DraftInputs(
        rules=rules,
        keepers=keeper_entries,
        players=players,
        target_manager=args.target_manager,
        market=MarketBaseline(effective_capital, remaining_baseline_value),
        top_n=args.top_n,
    )
    result = write_live_artifacts(inputs, args.output_dir, draft_id=args.draft_id)
    own_names = [entry.player for entry in keeper_entries[args.target_manager]]
    out = Path(args.output_dir) / "draft_board_2026.csv"
    print(f"keeper_spend=${market['keeper_spend']:.0f}; remaining_capital=${market['remaining_capital']:.0f}; effective_capital=${effective_capital:.1f}; deployment={deployment:.4f}")
    print(f"aav_normalization={aav_normalization:.3f}; keeper_market_value=${keeper_market_value:.1f}; keeper_inflation={keeper_inflation:.3f}")
    print(f"target_manager={args.target_manager}; own_keeper={','.join(own_names) if own_names else 'none'}")
    print(
        "replacement_levels="
        + ", ".join(
            f"{key}:{value:.1f}"
            for key, value in result.scarcity.league_replacement_levels.items()
        )
    )
    print(f"Wrote {len(result.board):,} rows to {out}")


if __name__ == "__main__":
    main()
