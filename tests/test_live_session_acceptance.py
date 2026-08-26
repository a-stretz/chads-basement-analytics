from __future__ import annotations

import pytest

import auction_engine.live_draft as live_draft_module
from auction_engine.draft_state import DraftValidationError, LeagueRules
from auction_engine.ledger import LedgerError
from auction_engine.live_draft import (
    DraftInputs,
    LiveDraftSession,
    MarketBaseline,
    RecalculationError,
    canonical_snapshot,
)
from tests.fixtures import acceptance_inputs, legal_sale_sequence, player_pool


def _unmodeled_position_inputs() -> DraftInputs:
    managers = ("Manager_01", "Manager_02")
    rules = LeagueRules(
        managers=managers,
        salary_cap=200,
        roster_size=8,
        min_bid=1,
        starters={
            "QB": 1,
            "RB": 1,
            "WR": 1,
            "TE": 1,
            "FLEX": 0,
            "DST": 1,
            "K": 1,
        },
        position_max={"QB": 2, "RB": 4, "WR": 4, "TE": 2, "DST": 3, "K": 3},
        modeled_positions=("QB", "RB", "WR", "TE"),
    )
    players = player_pool(per_position=8)
    players = players.loc[players.position.isin(rules.modeled_positions)].copy()
    return DraftInputs(
        rules=rules,
        keepers={manager: () for manager in managers},
        players=players,
        target_manager="Manager_01",
        market=MarketBaseline(400.0, float(players.normalized_aav.sum())),
        top_n=1,
    )


def test_forty_sales_reload_undo_edit_and_replay_identically(tmp_path):
    path = tmp_path / "state" / "draft.json"
    inputs = acceptance_inputs()
    session = LiveDraftSession.create(path, inputs, draft_id="synthetic-2026")
    sale_ids = []

    for player_key, manager, price in legal_sale_sequence(count=40):
        sale_ids.append(session.record_sale(player_key, manager, price).sale_id)

    after_sales = canonical_snapshot(session.snapshot())
    assert len(session.snapshot().state.active_sales) == 40
    assert canonical_snapshot(LiveDraftSession.load(path, inputs).snapshot()) == after_sales

    for sale_id in sale_ids[-3:]:
        session.undo_sale(sale_id)
    after_undo = canonical_snapshot(session.snapshot())
    assert len(session.snapshot().state.active_sales) == 37
    assert canonical_snapshot(LiveDraftSession.load(path, inputs).snapshot()) == after_undo

    corrected = session.edit_sale(sale_ids[4], price=2)
    assert corrected.order == 5
    after_edit = canonical_snapshot(session.snapshot())
    first_reload = LiveDraftSession.load(path, inputs)
    second_reload = LiveDraftSession.load(path, inputs)
    assert canonical_snapshot(first_reload.snapshot()) == after_edit
    assert canonical_snapshot(second_reload.snapshot()) == after_edit
    assert canonical_snapshot(first_reload.snapshot()) == canonical_snapshot(
        first_reload.snapshot()
    )


def test_invalid_historical_edit_keeps_valid_file_and_memory(tmp_path):
    path = tmp_path / "draft.json"
    inputs = acceptance_inputs()
    session = LiveDraftSession.create(path, inputs, draft_id="synthetic-2026")
    first = session.record_sale("qb_00", "Manager_02", 20)
    session.record_sale("wr_00", "Manager_02", 168)
    before_file = path.read_bytes()
    before_snapshot = canonical_snapshot(session.snapshot())

    with pytest.raises(DraftValidationError, match="maximum"):
        session.edit_sale(first.sale_id, price=30)

    assert path.read_bytes() == before_file
    assert canonical_snapshot(session.snapshot()) == before_snapshot


def test_failed_persistence_does_not_replace_in_memory_state(tmp_path, monkeypatch):
    path = tmp_path / "draft.json"
    inputs = acceptance_inputs()
    session = LiveDraftSession.create(path, inputs, draft_id="synthetic-2026")
    before_file = path.read_bytes()
    before_snapshot = canonical_snapshot(session.snapshot())

    def fail_save(path, ledger):
        raise OSError("disk unavailable")

    monkeypatch.setattr(live_draft_module, "save_ledger_atomic", fail_save)

    with pytest.raises(OSError, match="disk unavailable"):
        session.record_sale("qb_00", "Manager_01", 2)

    assert path.read_bytes() == before_file
    assert canonical_snapshot(session.snapshot()) == before_snapshot


def test_stale_session_cannot_overwrite_newer_ledger_events(tmp_path):
    path = tmp_path / "draft.json"
    inputs = acceptance_inputs()
    first = LiveDraftSession.create(path, inputs, draft_id="synthetic-2026")
    stale = LiveDraftSession.load(path, inputs)

    first_sale = first.record_sale("qb_00", "Manager_01", 2)
    persisted_after_first = path.read_bytes()

    with pytest.raises(LedgerError, match="another session"):
        stale.record_sale("rb_00", "Manager_02", 2)

    assert path.read_bytes() == persisted_after_first
    reloaded = LiveDraftSession.load(path, inputs)
    assert [sale.sale_id for sale in reloaded.snapshot().state.active_sales] == [
        first_sale.sale_id
    ]


def test_projection_free_k_sale_reloads_edits_and_undoes_deterministically(tmp_path):
    path = tmp_path / "draft.json"
    inputs = _unmodeled_position_inputs()
    session = LiveDraftSession.create(path, inputs, draft_id="synthetic-2026")
    initial = canonical_snapshot(session.snapshot())

    sale = session.record_unmodeled_sale(
        player="Justin Tucker",
        position="K",
        manager="Manager_01",
        price=1,
    )
    after_sale = canonical_snapshot(session.snapshot())
    target = session.snapshot().state.managers["Manager_01"]

    assert sale.player_key == "unmodeled-k-justintucker"
    assert target.budget_remaining == 199
    assert target.roster_slots_remaining == 7
    assert target.starter_needs["K"] == 0
    assert target.maximum_legal_bid == 193
    assert canonical_snapshot(LiveDraftSession.load(path, inputs).snapshot()) == after_sale

    corrected = session.edit_sale(sale.sale_id, price=3)
    after_edit = canonical_snapshot(session.snapshot())
    assert corrected.player_key == sale.player_key
    assert session.snapshot().state.managers["Manager_01"].maximum_legal_bid == 191
    assert canonical_snapshot(LiveDraftSession.load(path, inputs).snapshot()) == after_edit

    session.undo_sale(sale.sale_id)
    assert canonical_snapshot(session.snapshot()) == initial
    assert canonical_snapshot(LiveDraftSession.load(path, inputs).snapshot()) == initial


def test_projection_free_sale_rejects_modeled_or_disabled_position(tmp_path):
    inputs = _unmodeled_position_inputs()
    session = LiveDraftSession.create(
        tmp_path / "draft.json",
        inputs,
        draft_id="synthetic-2026",
    )

    with pytest.raises(RecalculationError, match="modeled position"):
        session.record_unmodeled_sale("Offense", "RB", "Manager_01", 1)

    disabled_rules = LeagueRules(
        **{
            **inputs.rules.__dict__,
            "starters": {**inputs.rules.starters, "K": 0},
            "position_max": {**inputs.rules.position_max, "K": 0},
        }
    )
    disabled = LiveDraftSession.create(
        tmp_path / "disabled.json",
        DraftInputs(
            rules=disabled_rules,
            keepers=inputs.keepers,
            players=inputs.players,
            target_manager=inputs.target_manager,
            market=inputs.market,
            top_n=inputs.top_n,
        ),
        draft_id="synthetic-disabled",
    )

    with pytest.raises(RecalculationError, match="disabled position"):
        disabled.record_unmodeled_sale("Kicker", "K", "Manager_01", 1)

