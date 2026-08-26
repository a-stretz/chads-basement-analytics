from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import pandas as pd
import yaml

from .bid_up_to import bid_up_to_remaining
from .draft_state import (
    DraftValidationError,
    LeagueDraftState,
    LeagueRules,
    RosterEntry,
    ROSTER_POSITIONS,
    Sale,
    replay_draft,
)
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


ACTIVE_KEEPER_STATUSES = frozenset({"likely", "confirmed"})
KEEPER_STATUSES = frozenset({*ACTIVE_KEEPER_STATUSES, "opt_out", "none"})
LIVE_CONTEXT_SCHEMA_VERSION = 2


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
    keeper_status_counts: tuple[tuple[str, int], ...] = ()


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


def normalize_player_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(value).lower())
    for suffix in ("iii", "ii", "jr", "sr"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def league_rules_from_mapping(
    config: Mapping[str, Any],
    managers: Sequence[str],
) -> LeagueRules:
    league = config["league"]
    manager_names = tuple(str(manager) for manager in managers)
    expected_teams = int(league["teams"])
    if len(manager_names) != expected_teams:
        raise RecalculationError(
            f"Expected {expected_teams} managers from league config; "
            f"found {len(manager_names)}"
        )
    starters = {key: int(value) for key, value in config["starters"].items()}
    position_max = {
        key: int(value) for key, value in config["position_max"].items()
    }
    model = config.get("model", {})
    modeled_positions = tuple(
        str(position).upper()
        for position in model.get("modeled_positions", ROSTER_POSITIONS)
    )
    if len(set(modeled_positions)) != len(modeled_positions):
        raise RecalculationError("modeled_positions must be unique")
    unknown_modeled = sorted(set(modeled_positions) - set(ROSTER_POSITIONS))
    if unknown_modeled:
        raise RecalculationError(
            f"Unknown modeled position: {unknown_modeled[0]}"
        )
    flex_eligible = tuple(config.get("flex_eligible", ("RB", "WR", "TE")))
    if int(starters.get("FLEX", 0)) and not set(flex_eligible).issubset(
        modeled_positions
    ):
        raise RecalculationError(
            "Every FLEX-eligible position must be included in modeled_positions"
        )
    for position in ("DST", "K"):
        if int(starters.get(position, 0)) == 0:
            position_max[position] = 0
    return LeagueRules(
        managers=manager_names,
        salary_cap=int(league["salary_cap"]),
        roster_size=int(league["roster_size"]),
        min_bid=int(league["min_bid"]),
        starters=starters,
        position_max=position_max,
        flex_eligible=flex_eligible,
        modeled_positions=modeled_positions,
    )


def _keeper_entries_by_manager(
    active: pd.DataFrame,
    managers: Sequence[str],
    players: pd.DataFrame,
) -> dict[str, tuple[RosterEntry, ...]]:
    by_key = players.set_index("player_key", drop=False)
    keepers: dict[str, list[RosterEntry]] = {str(manager): [] for manager in managers}
    for row in active.itertuples(index=False):
        manager = str(row.manager)
        if manager not in keepers:
            raise DraftValidationError(
                "unknown_manager",
                f"Unknown keeper manager: {manager}",
            )
        key = normalize_player_key(row.player)
        if key not in by_key.index:
            raise DraftValidationError(
                "unknown_player",
                f"Could not match keeper to projections: {row.player}",
            )
        projection = by_key.loc[key]
        raw_cost = float(row.keeper_cost)
        if not raw_cost.is_integer():
            raise DraftValidationError(
                "invalid_keeper_price",
                f"Keeper price must be an integer: {row.player}",
            )
        keepers[manager].append(
            RosterEntry(
                player_key=str(projection.player_key),
                player=str(projection.player),
                position=str(projection.position),
                price=int(raw_cost),
                acquisition="keeper",
            )
        )
    return {manager: tuple(entries) for manager, entries in keepers.items()}


def _normalized_keeper_rows(keeper_rows: pd.DataFrame) -> pd.DataFrame:
    rows = keeper_rows.copy()
    rows["status"] = (
        rows["status"].fillna("none").astype(str).str.strip().str.lower()
    )
    rows.loc[rows.status.eq(""), "status"] = "none"
    unsupported = sorted(set(rows.status) - KEEPER_STATUSES)
    if unsupported:
        raise RecalculationError(
            f"Unsupported keeper status: {unsupported[0]!r}; "
            f"expected one of {sorted(KEEPER_STATUSES)}"
        )
    return rows


def _keeper_adjusted_market(
    context: Mapping[str, Any],
    keepers: Mapping[str, Sequence[RosterEntry]],
    players: pd.DataFrame,
) -> MarketBaseline:
    if int(context.get("schema_version", 0)) != LIVE_CONTEXT_SCHEMA_VERSION:
        raise RecalculationError(
            "Unsupported live context schema. Rebuild live artifacts with "
            "scripts/build_draft_board.py."
        )
    try:
        deployable_capital = float(context["deployable_league_capital"])
        full_baseline_value = float(context["full_baseline_value"])
    except (KeyError, TypeError, ValueError) as error:
        raise RecalculationError(
            "Invalid live market context. Rebuild live artifacts with "
            "scripts/build_draft_board.py."
        ) from error

    entries = [entry for roster in keepers.values() for entry in roster]
    keeper_spend = float(sum(entry.price for entry in entries))
    keeper_keys = {entry.player_key for entry in entries}
    normalized = players.copy()
    normalized["normalized_aav"] = pd.to_numeric(
        normalized["normalized_aav"], errors="coerce"
    )
    keeper_rows = normalized.loc[normalized.player_key.isin(keeper_keys)]
    if keeper_rows.player_key.nunique() != len(keeper_keys):
        matched = set(keeper_rows.player_key)
        raise RecalculationError(
            f"Could not derive market value for keeper: {sorted(keeper_keys - matched)[0]}"
        )
    keeper_value = float(keeper_rows.normalized_aav.sum())
    remaining_capital = deployable_capital - keeper_spend
    remaining_baseline = full_baseline_value - keeper_value
    if remaining_capital < 0 or remaining_baseline <= 0:
        raise RecalculationError("Active keeper state leaves an invalid market baseline")
    return MarketBaseline(remaining_capital, remaining_baseline)


def load_draft_inputs(
    config_path: str | Path,
    pool_path: str | Path,
    context_path: str | Path,
    keepers_path: str | Path,
) -> DraftInputs:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    context = json.loads(Path(context_path).read_text(encoding="utf-8"))
    players = pd.read_csv(pool_path)
    keeper_rows = pd.read_csv(keepers_path)
    required_keeper_columns = {"manager", "player", "status", "keeper_cost"}
    missing = required_keeper_columns - set(keeper_rows.columns)
    if missing:
        raise RecalculationError(f"Missing keeper columns: {sorted(missing)}")
    keeper_rows = _normalized_keeper_rows(keeper_rows)
    managers = tuple(keeper_rows.manager.dropna().astype(str).drop_duplicates())
    rules = league_rules_from_mapping(config, managers)
    active = keeper_rows.loc[
        keeper_rows.status.isin(ACTIVE_KEEPER_STATUSES)
        & keeper_rows.player.notna()
    ].copy()
    keepers = _keeper_entries_by_manager(active, managers, players)
    market = _keeper_adjusted_market(context, keepers, players)
    status_counts = tuple(
        sorted(
            (str(status), int(count))
            for status, count in keeper_rows.status.value_counts().items()
        )
    )
    return DraftInputs(
        rules=rules,
        keepers=keepers,
        players=players,
        target_manager=str(context["target_manager"]),
        market=market,
        top_n=int(context.get("top_n", 80)),
        keeper_status_counts=status_counts,
    )


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


def _validate_owned_players(
    pool: pd.DataFrame,
    state: LeagueDraftState,
    modeled_positions: Sequence[str],
) -> None:
    by_key = pool.set_index("player_key", drop=False)
    modeled = set(modeled_positions)
    for manager in sorted(state.managers):
        for entry in state.managers[manager].roster:
            if entry.player_key not in by_key.index:
                if entry.position not in modeled:
                    continue
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


def _target_owned(
    pool: pd.DataFrame,
    state: LeagueDraftState,
    manager: str,
    modeled_positions: Sequence[str],
) -> pd.DataFrame:
    modeled = set(modeled_positions)
    keys = {
        entry.player_key
        for entry in state.managers[manager].roster
        if entry.position in modeled
    }
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
    _validate_owned_players(pool, state, inputs.rules.modeled_positions)

    remaining_capital, remaining_baseline, inflation = _market_state(
        pool, ordered_sales, inputs.market
    )
    available = pool.loc[~pool.player_key.isin(state.owned_player_keys)].copy()
    available = apply_inflation(available, inflation, source_col="normalized_aav")
    available["inflated_aav"] = available["inflated_aav"].clip(
        lower=inputs.rules.min_bid
    )
    modeled_available = available.loc[
        available.position.isin(inputs.rules.modeled_positions)
    ].copy()

    scarcity = calculate_scarcity(
        pool,
        state,
        inputs.rules,
        inputs.target_manager,
    )
    replacement = modeled_available.position.map(
        scarcity.league_replacement_levels
    )
    modeled_available["replacement_points"] = replacement
    modeled_available["vor"] = 0.0
    has_replacement = replacement.notna()
    modeled_available.loc[has_replacement, "vor"] = (
        modeled_available.loc[has_replacement, "projected_points"]
        - replacement.loc[has_replacement]
    )
    available = available.sort_values("player_key", kind="stable").reset_index(drop=True)
    modeled_available = modeled_available.sort_values(
        "player_key", kind="stable"
    ).reset_index(drop=True)

    target = state.managers[inputs.target_manager]
    owned = _target_owned(
        pool,
        state,
        inputs.target_manager,
        inputs.rules.modeled_positions,
    )
    modeled_rules = inputs.rules.modeled_roster_rules()
    lineup = optimize_roster_completion(
        available=modeled_available,
        owned=owned,
        budget=target.budget_remaining,
        roster_slots_remaining=target.roster_slots_remaining,
        position_capacity=target.position_capacity,
        rules=modeled_rules,
        points_col="projected_points",
        cost_col="inflated_aav",
    )
    if not lineup.success:
        raise RecalculationError(f"Target roster optimization failed: {lineup.message}")

    board = modeled_available.sort_values(
        ["vor", "projected_points", "player_key"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)
    candidate_keys = board.head(max(0, inputs.top_n)).player_key.tolist()
    bids = {
        key: bid_up_to_remaining(
            available=modeled_available,
            candidate_key=key,
            owned=owned,
            budget=target.budget_remaining,
            roster_slots_remaining=target.roster_slots_remaining,
            position_capacity=target.position_capacity,
            rules=modeled_rules,
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

    def _next_sale_order(self) -> int:
        return max(
            (
                event.sale.order
                for event in self.ledger.events
                if event.event_type == "sale_recorded" and event.sale is not None
            ),
            default=0,
        ) + 1

    def record_sale(self, player_key: str, manager: str, price: int) -> Sale:
        sale = self._canonical_sale(
            player_key,
            manager,
            price,
            self._next_sale_order(),
        )
        candidate = ledger_record_sale(self.ledger, sale)
        self._commit(candidate)
        return sale

    def record_unmodeled_sale(
        self,
        player: str,
        position: str,
        manager: str,
        price: int,
    ) -> Sale:
        canonical_position = str(position).strip().upper()
        if canonical_position in self.inputs.rules.modeled_positions:
            raise RecalculationError(
                f"Use the projected player pool for modeled position: "
                f"{canonical_position}"
            )
        if canonical_position not in self.inputs.rules.position_max:
            raise RecalculationError(f"Unknown position: {canonical_position}")
        if int(self.inputs.rules.position_max[canonical_position]) <= 0:
            raise RecalculationError(f"Cannot record disabled position: {canonical_position}")
        canonical_player = str(player).strip()
        normalized_name = normalize_player_key(canonical_player)
        if not normalized_name:
            raise RecalculationError("Projection-free player name cannot be empty")
        sale = Sale(
            sale_id=str(uuid4()),
            player_key=(
                f"unmodeled-{canonical_position.lower()}-{normalized_name}"
            ),
            player=canonical_player,
            position=canonical_position,
            manager=manager,
            price=price,
            order=self._next_sale_order(),
        )
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
        projection_keys = set(self.inputs.players.player_key)
        if current.player_key not in projection_keys and player_key is None:
            corrected = Sale(
                sale_id=sale_id,
                player_key=current.player_key,
                player=current.player,
                position=current.position,
                manager=manager if manager is not None else current.manager,
                price=price if price is not None else current.price,
                order=current.order,
            )
        else:
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

