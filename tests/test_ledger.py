from __future__ import annotations

import json

import pytest

import auction_engine.ledger as ledger_module
from auction_engine.draft_state import Sale
from auction_engine.ledger import (
    LedgerError,
    edit_sale,
    empty_ledger,
    fold_sales,
    load_ledger,
    record_sale,
    save_ledger_atomic,
    undo_sale,
)


def make_sale(
    sale_id: str = "sale-1",
    player_key: str = "rb_one",
    price: int = 20,
    order: int = 1,
) -> Sale:
    return Sale(
        sale_id=sale_id,
        player_key=player_key,
        player=player_key.replace("_", " ").title(),
        position="RB" if player_key.startswith("rb") else "WR",
        manager="Manager_01",
        price=price,
        order=order,
    )


def test_edit_and_undo_append_events_but_fold_only_active_sale_state():
    ledger = record_sale(
        empty_ledger("synthetic-2026"),
        make_sale(),
        event_id="event-1",
    )
    ledger = edit_sale(
        ledger,
        "sale-1",
        make_sale(price=25),
        event_id="event-2",
    )

    assert [event.sequence for event in ledger.events] == [1, 2]
    assert fold_sales(ledger)[0].price == 25

    ledger = undo_sale(ledger, "sale-1", event_id="event-3")

    assert [event.sequence for event in ledger.events] == [1, 2, 3]
    assert fold_sales(ledger) == ()


def test_edit_preserves_original_sale_order_and_identity():
    ledger = record_sale(empty_ledger("synthetic-2026"), make_sale(), event_id="event-1")
    ledger = record_sale(
        ledger,
        make_sale("sale-2", "wr_one", 15, 2),
        event_id="event-2",
    )
    ledger = edit_sale(
        ledger,
        "sale-1",
        make_sale(price=30, order=99),
        event_id="event-3",
    )

    active = fold_sales(ledger)

    assert [(sale.sale_id, sale.order, sale.price) for sale in active] == [
        ("sale-1", 1, 30),
        ("sale-2", 2, 15),
    ]


def test_inactive_sale_cannot_be_edited_or_undone_again():
    ledger = record_sale(empty_ledger("synthetic-2026"), make_sale(), event_id="event-1")
    ledger = undo_sale(ledger, "sale-1", event_id="event-2")

    with pytest.raises(LedgerError, match="active"):
        edit_sale(ledger, "sale-1", make_sale(price=22), event_id="event-3")
    with pytest.raises(LedgerError, match="active"):
        undo_sale(ledger, "sale-1", event_id="event-3")


def test_atomic_save_round_trips_stable_json(tmp_path):
    path = tmp_path / "state" / "draft.json"
    ledger = record_sale(empty_ledger("synthetic-2026"), make_sale(), event_id="event-1")

    save_ledger_atomic(path, ledger)

    assert load_ledger(path) == ledger
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["events"][0]["event_id"] == "event-1"
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_failed_atomic_replace_preserves_previous_file_and_removes_temp(tmp_path, monkeypatch):
    path = tmp_path / "draft.json"
    first = record_sale(empty_ledger("synthetic-2026"), make_sale(), event_id="event-1")
    save_ledger_atomic(path, first)
    before = path.read_bytes()
    second = edit_sale(first, "sale-1", make_sale(price=30), event_id="event-2")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(ledger_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_ledger_atomic(path, second)

    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_load_rejects_unsupported_schema_and_noncontiguous_sequence(tmp_path):
    path = tmp_path / "draft.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "draft_id": "synthetic-2026",
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="schema"):
        load_ledger(path)

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "draft_id": "synthetic-2026",
                "events": [
                    {
                        "event_id": "event-1",
                        "sequence": 2,
                        "event_type": "sale_recorded",
                        "sale_id": "sale-1",
                        "sale": {
                            "sale_id": "sale-1",
                            "player_key": "rb_one",
                            "player": "RB One",
                            "position": "RB",
                            "manager": "Manager_01",
                            "price": 20,
                            "order": 1,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="sequence"):
        load_ledger(path)
