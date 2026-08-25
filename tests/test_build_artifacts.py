from __future__ import annotations

import json

import pandas as pd
import yaml

from auction_engine.live_draft import load_draft_inputs
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
    assert context["target_manager"] == "Manager_01"
    assert (
        context["initial_remaining_capital"]
        == inputs.market.initial_remaining_capital
    )


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
