from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import tempfile
from typing import Literal
from uuid import uuid4

from .draft_state import Sale


EventType = Literal["sale_recorded", "sale_edited", "sale_undone"]
SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    sequence: int
    event_type: EventType
    sale_id: str
    sale: Sale | None = None


@dataclass(frozen=True)
class DraftLedger:
    schema_version: int
    draft_id: str
    events: tuple[LedgerEvent, ...] = ()


class LedgerError(ValueError):
    pass


def empty_ledger(draft_id: str) -> DraftLedger:
    if not draft_id:
        raise LedgerError("draft_id is required")
    return DraftLedger(schema_version=SUPPORTED_SCHEMA_VERSION, draft_id=draft_id)


def _new_event_id() -> str:
    return str(uuid4())


def _append(
    ledger: DraftLedger,
    event_type: EventType,
    sale_id: str,
    sale: Sale | None,
    event_id: str | None,
) -> DraftLedger:
    identifier = event_id or _new_event_id()
    if not identifier:
        raise LedgerError("event_id is required")
    if identifier in {event.event_id for event in ledger.events}:
        raise LedgerError(f"Duplicate event ID: {identifier}")
    event = LedgerEvent(
        event_id=identifier,
        sequence=len(ledger.events) + 1,
        event_type=event_type,
        sale_id=sale_id,
        sale=sale,
    )
    candidate = replace(ledger, events=ledger.events + (event,))
    fold_sales(candidate)
    return candidate


def record_sale(
    ledger: DraftLedger,
    sale: Sale,
    *,
    event_id: str | None = None,
) -> DraftLedger:
    if any(event.sale_id == sale.sale_id for event in ledger.events):
        raise LedgerError(f"Sale ID already exists: {sale.sale_id}")
    return _append(ledger, "sale_recorded", sale.sale_id, sale, event_id)


def edit_sale(
    ledger: DraftLedger,
    sale_id: str,
    corrected: Sale,
    *,
    event_id: str | None = None,
) -> DraftLedger:
    active = {sale.sale_id: sale for sale in fold_sales(ledger)}
    if sale_id not in active:
        raise LedgerError(f"Sale is not active: {sale_id}")
    corrected = replace(
        corrected,
        sale_id=sale_id,
        order=active[sale_id].order,
    )
    return _append(ledger, "sale_edited", sale_id, corrected, event_id)


def undo_sale(
    ledger: DraftLedger,
    sale_id: str,
    *,
    event_id: str | None = None,
) -> DraftLedger:
    if sale_id not in {sale.sale_id for sale in fold_sales(ledger)}:
        raise LedgerError(f"Sale is not active: {sale_id}")
    return _append(ledger, "sale_undone", sale_id, None, event_id)


def fold_sales(ledger: DraftLedger) -> tuple[Sale, ...]:
    if ledger.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise LedgerError(
            f"Unsupported ledger schema: {ledger.schema_version}; "
            f"expected {SUPPORTED_SCHEMA_VERSION}"
        )
    if not ledger.draft_id:
        raise LedgerError("draft_id is required")

    active: dict[str, Sale] = {}
    original_order: dict[str, int] = {}
    event_ids: set[str] = set()
    recorded_ids: set[str] = set()
    for expected_sequence, event in enumerate(ledger.events, start=1):
        if event.sequence != expected_sequence:
            raise LedgerError(
                f"Invalid event sequence {event.sequence}; expected {expected_sequence}"
            )
        if not event.event_id or event.event_id in event_ids:
            raise LedgerError(f"Duplicate or empty event ID: {event.event_id}")
        event_ids.add(event.event_id)

        if event.event_type == "sale_recorded":
            if event.sale is None or event.sale.sale_id != event.sale_id:
                raise LedgerError(f"Recorded sale payload mismatch: {event.sale_id}")
            if event.sale_id in recorded_ids:
                raise LedgerError(f"Sale ID already recorded: {event.sale_id}")
            if event.sale.order in original_order.values():
                raise LedgerError(f"Duplicate sale order: {event.sale.order}")
            recorded_ids.add(event.sale_id)
            original_order[event.sale_id] = event.sale.order
            active[event.sale_id] = event.sale
        elif event.event_type == "sale_edited":
            if event.sale_id not in active:
                raise LedgerError(f"Sale is not active: {event.sale_id}")
            if event.sale is None:
                raise LedgerError(f"Edited sale payload missing: {event.sale_id}")
            active[event.sale_id] = replace(
                event.sale,
                sale_id=event.sale_id,
                order=original_order[event.sale_id],
            )
        elif event.event_type == "sale_undone":
            if event.sale_id not in active:
                raise LedgerError(f"Sale is not active: {event.sale_id}")
            if event.sale is not None:
                raise LedgerError(f"Undo event cannot contain a sale: {event.sale_id}")
            del active[event.sale_id]
        else:
            raise LedgerError(f"Unsupported event type: {event.event_type}")

    return tuple(sorted(active.values(), key=lambda sale: sale.order))


def _event_to_dict(event: LedgerEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "sale_id": event.sale_id,
        "sale": asdict(event.sale) if event.sale is not None else None,
    }


def _ledger_to_dict(ledger: DraftLedger) -> dict[str, object]:
    fold_sales(ledger)
    return {
        "schema_version": ledger.schema_version,
        "draft_id": ledger.draft_id,
        "events": [_event_to_dict(event) for event in ledger.events],
    }


def _sale_from_dict(payload: object) -> Sale | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise LedgerError("Sale payload must be an object")
    try:
        return Sale(
            sale_id=str(payload["sale_id"]),
            player_key=str(payload["player_key"]),
            player=str(payload["player"]),
            position=str(payload["position"]),
            manager=str(payload["manager"]),
            price=int(payload["price"]),
            order=int(payload["order"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise LedgerError(f"Invalid sale payload: {error}") from error


def _ledger_from_dict(payload: object) -> DraftLedger:
    if not isinstance(payload, dict):
        raise LedgerError("Ledger document must be an object")
    try:
        schema_version = int(payload["schema_version"])
        draft_id = str(payload["draft_id"])
        raw_events = payload["events"]
    except (KeyError, TypeError, ValueError) as error:
        raise LedgerError(f"Invalid ledger envelope: {error}") from error
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise LedgerError(
            f"Unsupported ledger schema: {schema_version}; "
            f"expected {SUPPORTED_SCHEMA_VERSION}"
        )
    if not isinstance(raw_events, list):
        raise LedgerError("Ledger events must be a list")

    events: list[LedgerEvent] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise LedgerError("Ledger event must be an object")
        try:
            event_type = str(raw["event_type"])
            if event_type not in {"sale_recorded", "sale_edited", "sale_undone"}:
                raise LedgerError(f"Unsupported event type: {event_type}")
            events.append(
                LedgerEvent(
                    event_id=str(raw["event_id"]),
                    sequence=int(raw["sequence"]),
                    event_type=event_type,
                    sale_id=str(raw["sale_id"]),
                    sale=_sale_from_dict(raw.get("sale")),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LedgerError(f"Invalid ledger event: {error}") from error
    ledger = DraftLedger(schema_version, draft_id, tuple(events))
    fold_sales(ledger)
    return ledger


def load_ledger(path: str | Path) -> DraftLedger:
    ledger_path = Path(path)
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LedgerError(f"Could not read ledger {ledger_path}: {error}") from error
    return _ledger_from_dict(payload)


def save_ledger_atomic(path: str | Path, ledger: DraftLedger) -> None:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        _ledger_to_dict(ledger),
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{ledger_path.name}.",
            suffix=".tmp",
            dir=ledger_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, ledger_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
