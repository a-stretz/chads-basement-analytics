from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from .bid_up_to import bid_up_to_remaining
from .draft_state import LeagueDraftState, LeagueRules, RosterEntry, Sale, replay_draft
from .ledger import (
    DraftLedger,
    LedgerError,
    edit_sale as ledger_edit_sale,
    empty_ledger,
    fold_sales,
    load_ledger,
    record_sale as ledger_record_sale,
    save_ledger_atomic,
    undo_sale as ledger_undo_sale,
)
from .market import apply_inflation, market_inflation
from .optimizer import CompletionResult, optimize_roster_completion
from .scarcity import ScarcityResult, calculate_scarcity


@dataclass(frozen=True)
class MarketBaseline:
    initial_remaining_capital: float
    initial_remaining_baseline_value: float


@dataclass(frozen=True)
class DraftInputs:
    rules: LeagueRules
    keepers: Mapping[str, Sequence[RosterEntry]]
    players: pd.DataFrame
    target_manager: str
    market: MarketBaseline
    top_n: int = 80


@dataclass(frozen=True)
class RecalculationResult:
    state: LeagueDraftState
    available: pd.DataFrame
    remaining_capital: float
    remaining_baseline_value: float
    market_inflation: float
    scarcity: ScarcityResult
    target_lineup: CompletionResult
    board: pd.DataFrame


class RecalculationError(RuntimeError):
    pass


def _prepared_pool(players: pd.DataFrame) -> pd.DataFrame:
    required = {
        "player_key",
        "player",
        "position",
        "projected_points",
        "normalized_aav",
    }
    missing = required - set(players.columns)
    if missing:
        raise RecalculationError(f"Missing player columns: {sorted(missing)}")
    pool = players.copy()
    pool["projected_points"] = pd.to_numeric(pool["projected_points"], errors="coerce")
    pool["normalized_aav"] = pd.to_numeric(pool["normalized_aav"], errors="coerce")
    pool = pool.dropna(subset=list(required))
    pool = pool.sort_values("player_key", kind="stable").reset_index(drop=True)
    duplicate = pool.loc[pool.player_key.duplicated(), "player_key"]
    if len(duplicate):
        raise RecalculationError(f"Duplicate player identity: {duplicate.iloc[0]}")
    return pool


def _validate_owned_players(pool: pd.DataFrame, state: LeagueDraftState) -> None:
    by_key = pool.set_index("player_key", drop=False)
    for manager in sorted(state.managers):
        for entry in state.managers[manager].roster:
            if entry.player_key not in by_key.index:
                raise RecalculationError(
                    f"Owned player missing from projections: {entry.player_key}"
                )
            row = by_key.loc[entry.player_key]
            if row["player"] != entry.player or row["position"] != entry.position:
                raise RecalculationError(
                    f"Owned player identity does not match projections: {entry.player_key}"
                )


def _market_state(
    pool: pd.DataFrame,
    sales: Sequence[Sale],
    baseline: MarketBaseline,
) -> tuple[float, float, float]:
    sale_keys = [sale.player_key for sale in sales]
    purchased_baseline = float(
        pool.loc[pool.player_key.isin(sale_keys), "normalized_aav"].sum()
    )
    remaining_capital = max(
        0.0,
        float(baseline.initial_remaining_capital) - sum(sale.price for sale in sales),
    )
    remaining_baseline = max(
        0.0,
        float(baseline.initial_remaining_baseline_value) - purchased_baseline,
    )
    if remaining_baseline <= 0:
        raise RecalculationError("Remaining baseline value must stay positive")
    return (
        remaining_capital,
        remaining_baseline,
        market_inflation(remaining_capital, remaining_baseline),
    )


def _target_owned(pool: pd.DataFrame, state: LeagueDraftState, manager: str) -> pd.DataFrame:
    keys = {entry.player_key for entry in state.managers[manager].roster}
    return pool.loc[pool.player_key.isin(keys)].sort_values("player_key", kind="stable")


def recalculate_draft(
    inputs: DraftInputs,
    sales: Sequence[Sale],
) -> RecalculationResult:
    """Rebuild every live derived value from immutable inputs and active sales."""
    if inputs.target_manager not in inputs.rules.managers:
        raise RecalculationError(f"Unknown target manager: {inputs.target_manager}")
    pool = _prepared_pool(inputs.players)
    ordered_sales = tuple(sorted(sales, key=lambda sale: sale.order))
    state = replay_draft(inputs.rules, inputs.keepers, ordered_sales)
    _validate_owned_players(pool, state)

    remaining_capital, remaining_baseline, inflation = _market_state(
        pool, ordered_sales, inputs.market
    )
    available = pool.loc[~pool.player_key.isin(state.owned_player_keys)].copy()
    available = apply_inflation(available, inflation, source_col="normalized_aav")
    available["inflated_aav"] = available["inflated_aav"].clip(
        lower=inputs.rules.min_bid
    )

    scarcity = calculate_scarcity(
        pool,
        state,
        inputs.rules,
        inputs.target_manager,
    )
    replacement = available.position.map(scarcity.league_replacement_levels)
    available["replacement_points"] = replacement
    available["vor"] = 0.0
    has_replacement = replacement.notna()
    available.loc[has_replacement, "vor"] = (
        available.loc[has_replacement, "projected_points"]
        - replacement.loc[has_replacement]
    )
    available = available.sort_values("player_key", kind="stable").reset_index(drop=True)

    target = state.managers[inputs.target_manager]
    owned = _target_owned(pool, state, inputs.target_manager)
    lineup = optimize_roster_completion(
        available=available,
        owned=owned,
        budget=target.budget_remaining,
        roster_slots_remaining=target.roster_slots_remaining,
        position_capacity=target.position_capacity,
        rules=inputs.rules.roster_rules(),
        points_col="projected_points",
        cost_col="inflated_aav",
    )
    if not lineup.success:
        raise RecalculationError(f"Target roster optimization failed: {lineup.message}")

    board = available.sort_values(
        ["vor", "projected_points", "player_key"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)
    candidate_keys = board.head(max(0, inputs.top_n)).player_key.tolist()
    bids = {
        key: bid_up_to_remaining(
            available=available,
            candidate_key=key,
            owned=owned,
            budget=target.budget_remaining,
            roster_slots_remaining=target.roster_slots_remaining,
            position_capacity=target.position_capacity,
            rules=inputs.rules.roster_rules(),
            maximum_legal_bid=target.maximum_legal_bid,
        )
        for key in candidate_keys
    }
    board["bid_up_to"] = board.player_key.map(bids)
    return RecalculationResult(
        state=state,
        available=available,
        remaining_capital=remaining_capital,
        remaining_baseline_value=remaining_baseline,
        market_inflation=inflation,
        scarcity=scarcity,
        target_lineup=lineup,
        board=board,
    )


def _rounded(value: float) -> float:
    return round(float(value), 8)


def canonical_snapshot(result: RecalculationResult) -> dict[str, Any]:
    """Stable, serializable proof of all draft-night values derived by replay."""
    managers = []
    for name in sorted(result.state.managers):
        manager = result.state.managers[name]
        roster = [
            {
                "player_key": entry.player_key,
                "position": entry.position,
                "price": entry.price,
                "acquisition": entry.acquisition,
                "sale_id": entry.sale_id,
            }
            for entry in sorted(manager.roster, key=lambda entry: entry.player_key)
        ]
        managers.append(
            {
                "manager": name,
                "budget_remaining": manager.budget_remaining,
                "roster_slots_remaining": manager.roster_slots_remaining,
                "position_counts": dict(sorted(manager.position_counts.items())),
                "position_capacity": dict(sorted(manager.position_capacity.items())),
                "starter_needs": dict(sorted(manager.starter_needs.items())),
                "flex_need": manager.flex_need,
                "maximum_legal_bid": manager.maximum_legal_bid,
                "roster": roster,
            }
        )

    board = []
    for row in result.board.sort_values("player_key", kind="stable").itertuples():
        bid = None if pd.isna(row.bid_up_to) else int(row.bid_up_to)
        board.append(
            {
                "player_key": row.player_key,
                "inflated_aav": _rounded(row.inflated_aav),
                "replacement_points": (
                    None
                    if pd.isna(row.replacement_points)
                    else _rounded(row.replacement_points)
                ),
                "vor": _rounded(row.vor),
                "bid_up_to": bid,
            }
        )
    return {
        "managers": managers,
        "available_player_keys": sorted(result.available.player_key.tolist()),
        "remaining_capital": _rounded(result.remaining_capital),
        "remaining_baseline_value": _rounded(result.remaining_baseline_value),
        "market_inflation": _rounded(result.market_inflation),
        "scarcity": {
            "league_replacement_levels": {
                key: _rounded(value)
                for key, value in sorted(
                    result.scarcity.league_replacement_levels.items()
                )
            },
            "outstanding_demand": dict(
                sorted(result.scarcity.outstanding_demand.items())
            ),
            "target_needs": dict(sorted(result.scarcity.target_needs.items())),
            "selected_available": sorted(
                result.scarcity.selected_available.player_key.tolist()
            ),
        },
        "target_lineup": {
            "active": sorted(result.target_lineup.active.player_key.tolist()),
            "acquisitions": sorted(
                result.target_lineup.acquisitions.player_key.tolist()
            ),
            "projected_points": _rounded(result.target_lineup.projected_points),
            "required_budget": _rounded(result.target_lineup.required_budget),
        },
        "board": board,
    }


class LiveDraftSession:
    """Persisted ledger session that validates a complete replay before saving."""

    def __init__(
        self,
        path: str | Path,
        inputs: DraftInputs,
        ledger: DraftLedger,
        result: RecalculationResult,
    ) -> None:
        self.path = Path(path)
        self.inputs = inputs
        self.ledger = ledger
        self.result = result

    @classmethod
    def create(
        cls,
        path: str | Path,
        inputs: DraftInputs,
        draft_id: str,
    ) -> "LiveDraftSession":
        ledger = empty_ledger(draft_id)
        result = recalculate_draft(inputs, ())
        save_ledger_atomic(path, ledger)
        return cls(path, inputs, ledger, result)

    @classmethod
    def load(
        cls,
        path: str | Path,
        inputs: DraftInputs,
    ) -> "LiveDraftSession":
        ledger = load_ledger(path)
        result = recalculate_draft(inputs, fold_sales(ledger))
        return cls(path, inputs, ledger, result)

    def snapshot(self) -> RecalculationResult:
        return self.result

    def _commit(self, candidate: DraftLedger) -> None:
        candidate_result = recalculate_draft(self.inputs, fold_sales(candidate))
        save_ledger_atomic(self.path, candidate)
        self.ledger = candidate
        self.result = candidate_result

    def _canonical_sale(
        self,
        player_key: str,
        manager: str,
        price: int,
        order: int,
        sale_id: str | None = None,
    ) -> Sale:
        matches = self.inputs.players.loc[
            self.inputs.players.player_key.eq(player_key)
        ]
        if len(matches) != 1:
            raise RecalculationError(
                f"Expected one projection row for {player_key}; found {len(matches)}"
            )
        row = matches.iloc[0]
        return Sale(
            sale_id=sale_id or str(uuid4()),
            player_key=str(row.player_key),
            player=str(row.player),
            position=str(row.position),
            manager=manager,
            price=price,
            order=order,
        )

    def record_sale(self, player_key: str, manager: str, price: int) -> Sale:
        order = max(
            (
                event.sale.order
                for event in self.ledger.events
                if event.event_type == "sale_recorded" and event.sale is not None
            ),
            default=0,
        ) + 1
        sale = self._canonical_sale(player_key, manager, price, order)
        candidate = ledger_record_sale(self.ledger, sale)
        self._commit(candidate)
        return sale

    def edit_sale(
        self,
        sale_id: str,
        *,
        player_key: str | None = None,
        manager: str | None = None,
        price: int | None = None,
    ) -> Sale:
        active = {sale.sale_id: sale for sale in fold_sales(self.ledger)}
        if sale_id not in active:
            raise LedgerError(f"Sale is not active: {sale_id}")
        current = active[sale_id]
        corrected = self._canonical_sale(
            player_key if player_key is not None else current.player_key,
            manager if manager is not None else current.manager,
            price if price is not None else current.price,
            current.order,
            sale_id=sale_id,
        )
        candidate = ledger_edit_sale(self.ledger, sale_id, corrected)
        self._commit(candidate)
        return corrected

    def undo_sale(self, sale_id: str) -> None:
        candidate = ledger_undo_sale(self.ledger, sale_id)
        self._commit(candidate)
