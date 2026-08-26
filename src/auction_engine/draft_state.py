from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from .optimizer import RosterRules


ROSTER_POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")


@dataclass(frozen=True)
class LeagueRules:
    managers: tuple[str, ...]
    salary_cap: int
    roster_size: int
    min_bid: int
    starters: Mapping[str, int]
    position_max: Mapping[str, int]
    flex_eligible: tuple[str, ...] = ("RB", "WR", "TE")
    modeled_positions: tuple[str, ...] = ROSTER_POSITIONS

    def roster_rules(self) -> RosterRules:
        return RosterRules(
            qb=int(self.starters.get("QB", 0)),
            rb=int(self.starters.get("RB", 0)),
            wr=int(self.starters.get("WR", 0)),
            te=int(self.starters.get("TE", 0)),
            flex=int(self.starters.get("FLEX", 0)),
            dst=int(self.starters.get("DST", 0)),
            k=int(self.starters.get("K", 0)),
            roster_size=self.roster_size,
            min_bid=self.min_bid,
        )

    def modeled_roster_rules(self) -> RosterRules:
        """Starter constraints used only by projection-based calculations."""
        full = self.roster_rules()
        modeled = set(self.modeled_positions)
        return RosterRules(
            qb=full.qb if "QB" in modeled else 0,
            rb=full.rb if "RB" in modeled else 0,
            wr=full.wr if "WR" in modeled else 0,
            te=full.te if "TE" in modeled else 0,
            flex=full.flex,
            dst=full.dst if "DST" in modeled else 0,
            k=full.k if "K" in modeled else 0,
            roster_size=full.roster_size,
            min_bid=full.min_bid,
        )


@dataclass(frozen=True)
class RosterEntry:
    player_key: str
    player: str
    position: str
    price: int
    acquisition: str
    sale_id: str | None = None


@dataclass(frozen=True)
class Sale:
    sale_id: str
    player_key: str
    player: str
    position: str
    manager: str
    price: int
    order: int


@dataclass(frozen=True)
class ManagerState:
    manager: str
    budget_remaining: int
    roster: tuple[RosterEntry, ...]
    roster_slots_remaining: int
    position_counts: dict[str, int]
    position_capacity: dict[str, int]
    starter_needs: dict[str, int]
    flex_need: int
    maximum_legal_bid: int


@dataclass(frozen=True)
class LeagueDraftState:
    managers: dict[str, ManagerState]
    active_sales: tuple[Sale, ...]
    owned_player_keys: frozenset[str]


class DraftValidationError(ValueError):
    def __init__(self, code: str, message: str, sale_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.sale_id = sale_id


def _error(code: str, message: str, sale_id: str | None = None) -> DraftValidationError:
    return DraftValidationError(code, message, sale_id)


def _position_counts(roster: Iterable[RosterEntry]) -> dict[str, int]:
    return dict(sorted(Counter(entry.position for entry in roster).items()))


def _starter_needs(
    counts: Mapping[str, int], rules: LeagueRules
) -> tuple[dict[str, int], int]:
    needs: dict[str, int] = {}
    flex_surplus = 0
    for position, required in rules.starters.items():
        if position == "FLEX":
            continue
        owned = int(counts.get(position, 0))
        needs[position] = max(0, int(required) - owned)
        if position in rules.flex_eligible:
            flex_surplus += max(0, owned - int(required))
    flex_need = max(0, int(rules.starters.get("FLEX", 0)) - flex_surplus)
    return dict(sorted(needs.items())), flex_need


def _manager_state(
    manager: str,
    roster: Iterable[RosterEntry],
    rules: LeagueRules,
) -> ManagerState:
    entries = tuple(roster)
    counts = _position_counts(entries)
    slots = max(0, rules.roster_size - len(entries))
    budget = rules.salary_cap - sum(entry.price for entry in entries)
    maximum_bid = (
        max(0, budget - rules.min_bid * (slots - 1))
        if slots > 0
        else 0
    )
    capacity = {
        position: max(0, int(maximum) - int(counts.get(position, 0)))
        for position, maximum in sorted(rules.position_max.items())
    }
    needs, flex_need = _starter_needs(counts, rules)
    return ManagerState(
        manager=manager,
        budget_remaining=budget,
        roster=entries,
        roster_slots_remaining=slots,
        position_counts=counts,
        position_capacity=capacity,
        starter_needs=needs,
        flex_need=flex_need,
        maximum_legal_bid=maximum_bid,
    )


def _validate_entry(
    entry: RosterEntry,
    manager: str,
    rules: LeagueRules,
    owned: set[str],
) -> None:
    if not entry.player_key:
        raise _error("unknown_player", f"{manager} has an empty player identity")
    if entry.player_key in owned:
        raise _error("duplicate_player", f"{entry.player} is already owned")
    if entry.position not in rules.position_max:
        raise _error("unknown_position", f"Unknown position: {entry.position}")
    if int(rules.position_max[entry.position]) <= 0:
        raise _error("disabled_position", f"Position is disabled: {entry.position}")
    if not isinstance(entry.price, int) or isinstance(entry.price, bool) or entry.price < 0:
        raise _error("invalid_keeper_price", f"Invalid keeper price for {entry.player}")


def replay_draft(
    rules: LeagueRules,
    keepers: Mapping[str, Iterable[RosterEntry]],
    sales: Iterable[Sale],
) -> LeagueDraftState:
    if len(set(rules.managers)) != len(rules.managers):
        raise _error("duplicate_manager", "League manager names must be unique")
    unknown_keeper_managers = set(keepers) - set(rules.managers)
    if unknown_keeper_managers:
        name = sorted(unknown_keeper_managers)[0]
        raise _error("unknown_manager", f"Unknown keeper manager: {name}")

    rosters: dict[str, list[RosterEntry]] = {manager: [] for manager in rules.managers}
    owned: set[str] = set()
    for manager in rules.managers:
        for entry in keepers.get(manager, ()):
            _validate_entry(entry, manager, rules, owned)
            candidate = rosters[manager] + [entry]
            if len(candidate) > rules.roster_size:
                raise _error("roster_full", f"{manager} exceeds roster size")
            counts = _position_counts(candidate)
            if counts[entry.position] > int(rules.position_max[entry.position]):
                raise _error(
                    "position_maximum",
                    f"{manager} exceeds the {entry.position} position maximum",
                )
            if sum(item.price for item in candidate) > rules.salary_cap:
                raise _error("negative_budget", f"{manager} keeper spend exceeds salary cap")
            rosters[manager].append(entry)
            owned.add(entry.player_key)

    ordered_sales = tuple(sorted(sales, key=lambda item: item.order))
    seen_sale_ids: set[str] = set()
    seen_orders: set[int] = set()
    for sale in ordered_sales:
        if not sale.sale_id or sale.sale_id in seen_sale_ids:
            raise _error("duplicate_sale", f"Duplicate sale ID: {sale.sale_id}", sale.sale_id)
        if not isinstance(sale.order, int) or sale.order <= 0 or sale.order in seen_orders:
            raise _error("invalid_sale_order", f"Invalid sale order: {sale.order}", sale.sale_id)
        seen_sale_ids.add(sale.sale_id)
        seen_orders.add(sale.order)
        if sale.manager not in rosters:
            raise _error("unknown_manager", f"Unknown manager: {sale.manager}", sale.sale_id)
        if not sale.player_key:
            raise _error("unknown_player", "Sale has an empty player identity", sale.sale_id)
        if sale.player_key in owned:
            raise _error("duplicate_player", f"{sale.player} is already owned", sale.sale_id)
        if sale.position not in rules.position_max:
            raise _error("unknown_position", f"Unknown position: {sale.position}", sale.sale_id)
        if int(rules.position_max[sale.position]) <= 0:
            raise _error("disabled_position", f"Position is disabled: {sale.position}", sale.sale_id)
        if not isinstance(sale.price, int) or isinstance(sale.price, bool):
            raise _error("invalid_price", "Sale price must be an integer", sale.sale_id)
        if sale.price < rules.min_bid:
            raise _error(
                "below_minimum_bid",
                f"{sale.price} is below the minimum bid of {rules.min_bid}",
                sale.sale_id,
            )

        before = _manager_state(sale.manager, rosters[sale.manager], rules)
        if before.roster_slots_remaining <= 0:
            raise _error("roster_full", f"{sale.manager} has no roster slots remaining", sale.sale_id)
        if before.position_capacity.get(sale.position, 0) <= 0:
            raise _error(
                "position_maximum",
                f"{sale.manager} exceeds the {sale.position} position maximum",
                sale.sale_id,
            )
        if sale.price > before.maximum_legal_bid:
            raise _error(
                "above_maximum_bid",
                f"{sale.manager} cannot legally bid {sale.price}; maximum is {before.maximum_legal_bid}",
                sale.sale_id,
            )

        rosters[sale.manager].append(
            RosterEntry(
                player_key=sale.player_key,
                player=sale.player,
                position=sale.position,
                price=sale.price,
                acquisition="sale",
                sale_id=sale.sale_id,
            )
        )
        owned.add(sale.player_key)

    manager_states = {
        manager: _manager_state(manager, rosters[manager], rules)
        for manager in sorted(rosters)
    }
    return LeagueDraftState(
        managers=manager_states,
        active_sales=ordered_sales,
        owned_player_keys=frozenset(owned),
    )

