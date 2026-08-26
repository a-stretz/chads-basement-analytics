from __future__ import annotations

import importlib

import pandas as pd


def test_nomination_pool_stays_ranked_by_available_aav_descending():
    draft_ui = importlib.import_module("auction_engine.draft_ui")
    available = pd.DataFrame(
        [
            {"player_key": "low", "player": "Low AAV", "position": "RB", "normalized_aav": 4.0},
            {"player_key": "tie-z", "player": "Zulu Tie", "position": "WR", "normalized_aav": 17.0},
            {"player_key": "unmodeled", "player": "Defense", "position": "DST", "normalized_aav": 30.0},
            {"player_key": "high", "player": "High AAV", "position": "QB", "normalized_aav": 31.0},
            {"player_key": "tie-a", "player": "Alpha Tie", "position": "TE", "normalized_aav": 17.0},
        ]
    )

    ranked = draft_ui.prepare_nomination_pool(
        available,
        modeled_positions=("QB", "RB", "WR", "TE"),
    )

    assert ranked.player_key.tolist() == ["high", "tie-a", "tie-z", "low"]


def test_nomination_labels_expose_aav_without_changing_rank_order():
    draft_ui = importlib.import_module("auction_engine.draft_ui")
    ranked = pd.DataFrame(
        [
            {"player_key": "alpha", "player": "Alpha", "position": "RB", "normalized_aav": 24.6},
            {"player_key": "beta", "player": "Beta", "position": "WR", "normalized_aav": 9.2},
        ]
    )

    labels = draft_ui.nomination_labels(ranked)

    assert labels == {
        "alpha": "Alpha — RB — AAV $25",
        "beta": "Beta — WR — AAV $9",
    }


def test_draft_input_version_changes_after_same_size_file_edit(tmp_path):
    draft_ui = importlib.import_module("auction_engine.draft_ui")
    config = tmp_path / "league.yaml"
    keepers = tmp_path / "keepers.csv"
    config.write_text("K: 1\n", encoding="utf-8")
    keepers.write_text("likely\n", encoding="utf-8")
    original = draft_ui.draft_input_version((config, keepers))

    config.write_text("K: 0\n", encoding="utf-8")
    changed = draft_ui.draft_input_version((config, keepers))

    assert changed != original


def test_draft_resources_are_reused_until_inputs_change():
    draft_ui = importlib.import_module("auction_engine.draft_ui")
    state = {}
    loads = []

    def load_resources():
        resources = (object(), object(), object())
        loads.append(resources)
        return resources

    first = draft_ui.get_or_load_draft_resources(state, "version-1", load_resources)
    repeated = draft_ui.get_or_load_draft_resources(state, "version-1", load_resources)
    changed = draft_ui.get_or_load_draft_resources(state, "version-2", load_resources)

    assert repeated == first
    assert changed != first
    assert loads == [first, changed]
