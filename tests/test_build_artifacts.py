from __future__ import annotations

from dataclasses import replace
import json

import pandas as pd
import pytest
import yaml

from auction_engine.draft_state import RosterEntry
from auction_engine.live_draft import (
    MarketBaseline,
    RecalculationError,
    load_draft_inputs,
    normalize_player_key,
    recalculate_draft,
)
from scripts.build_draft_board import write_live_artifacts
from tests.fixtures import acceptance_inputs


def _write_loader_inputs(tmp_path, inputs):
    config = {
        "league": {
            "teams": len(inputs.rules.managers),
            "salary_cap": inputs.rules.salary_cap,
            "roster_size": inputs.rules.roster_size,
            "min_bid": inputs.rules.min_bid,
        },
        "starters": dict(inputs.rules.starters),
        "position_max": dict(inputs.rules.position_max),
        "flex_eligible": list(inputs.rules.flex_eligible),
    }
    config_path = tmp_path / "league.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    keepers_path = tmp_path / "keepers.csv"
    pd.DataFrame(
        [
            {
                "manager": manager,
                "player": None,
                "status": "none",
                "keeper_cost": 0,
            }
            for manager in inputs.rules.managers
        ]
    ).to_csv(keepers_path, index=False)
    return config_path, keepers_path


def test_live_artifacts_include_full_pool_board_and_market_context(tmp_path):
    inputs = acceptance_inputs()

    result = write_live_artifacts(inputs, tmp_path, draft_id="synthetic-2026")

    pool_path = tmp_path / "draft_pool_2026.csv"
    board_path = tmp_path / "draft_board_2026.csv"
    context_path = tmp_path / "draft_context_2026.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert len(pd.read_csv(pool_path)) == len(inputs.players)
    assert len(pd.read_csv(board_path)) == len(result.board)
    assert context["draft_id"] == "synthetic-2026"
    assert context["schema_version"] == 2
    assert context["target_manager"] == "Manager_01"
    assert context["deployable_league_capital"] == 2000.0
    assert context["full_baseline_value"] == inputs.market.initial_remaining_baseline_value


def test_generated_artifacts_and_private_keepers_load_into_draft_inputs(tmp_path):
    inputs = acceptance_inputs(top_n=2)
    write_live_artifacts(inputs, tmp_path, draft_id="synthetic-2026")
    config_path, keepers_path = _write_loader_inputs(tmp_path, inputs)

    loaded = load_draft_inputs(
        config_path=config_path,
        pool_path=tmp_path / "draft_pool_2026.csv",
        context_path=tmp_path / "draft_context_2026.json",
        keepers_path=keepers_path,
    )

    assert loaded.rules.managers == inputs.rules.managers
    assert loaded.target_manager == inputs.target_manager
    assert loaded.market == inputs.market
    assert loaded.top_n == 2
    assert loaded.players.player_key.tolist() == inputs.players.player_key.tolist()
    assert all(not entries for entries in loaded.keepers.values())


def test_keeper_status_reload_recalculates_market_from_prekeeper_context(tmp_path):
    base = acceptance_inputs(top_n=2)
    players = base.players.copy()
    players["player_key"] = players.player.map(normalize_player_key)
    base = replace(base, players=players)
    keeper = RosterEntry("rb00", "RB 00", "RB", 7, "keeper")
    keeper_value = 30.0
    active = replace(
        base,
        keepers={
            manager: ((keeper,) if manager == "Manager_01" else ())
            for manager in base.rules.managers
        },
        market=MarketBaseline(
            initial_remaining_capital=1993.0,
            initial_remaining_baseline_value=(
                base.market.initial_remaining_baseline_value - keeper_value
            ),
        ),
    )
    write_live_artifacts(active, tmp_path, draft_id="synthetic-2026")
    config_path, keepers_path = _write_loader_inputs(tmp_path, base)
    keeper_rows = pd.read_csv(keepers_path)
    keeper_rows["player"] = keeper_rows["player"].astype("object")
    keeper_rows.loc[keeper_rows.manager.eq("Manager_01"), ["player", "status", "keeper_cost"]] = [
        "RB 00",
        "likely",
        7,
    ]
    keeper_rows.to_csv(keepers_path, index=False)

    likely = load_draft_inputs(
        config_path,
        tmp_path / "draft_pool_2026.csv",
        tmp_path / "draft_context_2026.json",
        keepers_path,
    )
    keeper_rows.loc[keeper_rows.manager.eq("Manager_01"), "status"] = "confirmed"
    keeper_rows.to_csv(keepers_path, index=False)
    confirmed = load_draft_inputs(
        config_path,
        tmp_path / "draft_pool_2026.csv",
        tmp_path / "draft_context_2026.json",
        keepers_path,
    )

    assert likely.market == MarketBaseline(1993.0, base.market.initial_remaining_baseline_value - 30.0)
    assert confirmed.market == likely.market
    assert confirmed.keepers == likely.keepers
    assert dict(confirmed.keeper_status_counts)["confirmed"] == 1
    likely_result = recalculate_draft(likely, ())

    keeper_rows.loc[keeper_rows.manager.eq("Manager_01"), "status"] = "opt_out"
    keeper_rows.to_csv(keepers_path, index=False)
    opted_out = load_draft_inputs(
        config_path,
        tmp_path / "draft_pool_2026.csv",
        tmp_path / "draft_context_2026.json",
        keepers_path,
    )

    assert opted_out.market == base.market
    assert all(not entries for entries in opted_out.keepers.values())
    opted_out_result = recalculate_draft(opted_out, ())
    assert "rb00" not in set(likely_result.available.player_key)
    assert "rb00" in set(opted_out_result.available.player_key)
    assert opted_out_result.remaining_capital == 2000.0
    assert opted_out_result.remaining_baseline_value == base.market.initial_remaining_baseline_value
    likely_bids = likely_result.board.dropna(subset=["bid_up_to"]).set_index("player_key")["bid_up_to"]
    opted_out_bids = opted_out_result.board.dropna(subset=["bid_up_to"]).set_index("player_key")["bid_up_to"]
    common = likely_bids.index.intersection(opted_out_bids.index)
    assert len(common) > 0
    assert (likely_bids.loc[common] != opted_out_bids.loc[common]).any()


def test_loader_rejects_unknown_keeper_status_and_legacy_context(tmp_path):
    inputs = acceptance_inputs()
    write_live_artifacts(inputs, tmp_path, draft_id="synthetic-2026")
    config_path, keepers_path = _write_loader_inputs(tmp_path, inputs)
    keepers = pd.read_csv(keepers_path)
    keepers.loc[0, "status"] = "maybe"
    keepers.to_csv(keepers_path, index=False)

    with pytest.raises(RecalculationError, match="keeper status"):
        load_draft_inputs(
            config_path,
            tmp_path / "draft_pool_2026.csv",
            tmp_path / "draft_context_2026.json",
            keepers_path,
        )

    keepers.loc[0, "status"] = "none"
    keepers.to_csv(keepers_path, index=False)
    context_path = tmp_path / "draft_context_2026.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["schema_version"] = 1
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(RecalculationError, match="Rebuild live artifacts"):
        load_draft_inputs(
            config_path,
            tmp_path / "draft_pool_2026.csv",
            context_path,
            keepers_path,
        )

