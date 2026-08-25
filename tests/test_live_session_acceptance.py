from __future__ import annotations

import pytest

import auction_engine.live_draft as live_draft_module
from auction_engine.draft_state import DraftValidationError
from auction_engine.live_draft import LiveDraftSession, canonical_snapshot
from tests.fixtures import acceptance_inputs, legal_sale_sequence


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
