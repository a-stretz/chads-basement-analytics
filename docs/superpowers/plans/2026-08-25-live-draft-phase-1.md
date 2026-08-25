# Live Draft Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persisted, replayable live-auction state engine that deterministically recalculates manager state, market/scarcity, target optimization, and Bid-Up-To after every record, edit, or undo operation.

**Architecture:** A versioned append-only JSON ledger is folded into active sales, then a pure replay function rebuilds every manager from config and keepers. A pure recalculation service consumes that rebuilt state and the full projection pool; Streamlit calls a thin persisted session service that validates a complete candidate replay before each atomic save.

**Tech Stack:** Python 3.11+, pandas, NumPy, SciPy `milp`, PyYAML, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-live-draft-phase-1-design.md`

## Global Constraints

- Preserve normalized AAV, keeper-adjusted market capital, dynamic replacement, starter-point maximization, minimum bench reserve, and opportunity-cost Bid-Up-To.
- Owned players consume budget, roster slots, and position capacity but may sit on the zero-weight bench.
- Keep league-wide scarcity and target-manager scarcity as separate outputs.
- Reject invalid ledger changes before replacing the last valid file.
- Use anonymized synthetic managers and players in every tracked test fixture.
- Do not stage or commit private mappings, keeper files, generated boards, live state, or non-anonymized history.
- Keep Phase 2 keeper/K controls and Phase 3 interface polish out of this plan.
- Run `& '.\.venv\Scripts\python.exe' -m pytest -q` after each meaningful increment.
- Update `docs/build-status.md` with the behavior that actually passes.

---

## File Structure

- `src/auction_engine/draft_state.py`: immutable league rules, roster entries, sales, manager snapshots, replay, needs, and domain validation.
- `src/auction_engine/ledger.py`: event types, fold semantics, JSON encoding, loading, and atomic persistence.
- `src/auction_engine/optimizer.py`: existing starter-core functions plus remaining-roster optimization and deterministic tie resolution.
- `src/auction_engine/scarcity.py`: league-wide remaining-demand MILP and target need summary.
- `src/auction_engine/bid_up_to.py`: existing static API plus remaining-roster Bid-Up-To.
- `src/auction_engine/live_draft.py`: market baseline, pure full recalculation, canonical snapshot, and validated persisted session operations.
- `scripts/build_draft_board.py`: emit the full normalized draft pool and market context required by live recalculation.
- `app/streamlit_app.py`: minimal persistent record/edit/undo workflow backed by `LiveDraftSession`.
- `tests/fixtures.py`: deterministic anonymized league and projection factories.
- `tests/test_draft_state.py`: state replay and legality.
- `tests/test_ledger.py`: event folding and atomic persistence.
- `tests/test_optimizer_live.py`: owned-roster completion and deterministic ties.
- `tests/test_scarcity.py`: two-layer scarcity.
- `tests/test_live_recalculation.py`: market, availability, lineup, and Bid-Up-To transitions.
- `tests/test_live_session_acceptance.py`: 30–50 sale persistence/reload/edit/undo acceptance workflow.
- `docs/build-status.md`: verified Phase 1 status.

---

### Task 1: Immutable Draft State and Chronological Validation

**Files:**
- Modify: `src/auction_engine/draft_state.py`
- Create: `tests/fixtures.py`
- Create: `tests/test_draft_state.py`

**Interfaces:**
- Produces: `LeagueRules`, `RosterEntry`, `Sale`, `ManagerState`, `LeagueDraftState`, `DraftValidationError`, and `replay_draft(rules, keepers, sales)`.
- Consumes: `RosterRules` only through `LeagueRules.roster_rules()` so existing optimizer callers remain compatible.

- [ ] **Step 1: Add failing replay and validation tests**

```python
# tests/test_draft_state.py
import pytest

from auction_engine.draft_state import (
    DraftValidationError,
    RosterEntry,
    Sale,
    replay_draft,
)
from tests.fixtures import league_rules


def test_replay_counts_keeper_and_sale_in_budget_roster_and_needs():
    rules = league_rules(managers=("Manager_01", "Manager_02"))
    keeper = RosterEntry("rb_keeper", "RB Keeper", "RB", 12, "keeper")
    sale = Sale("sale-1", "wr_one", "WR One", "WR", "Manager_01", 31, 1)

    state = replay_draft(rules, {"Manager_01": (keeper,), "Manager_02": ()}, (sale,))
    manager = state.managers["Manager_01"]

    assert manager.budget_remaining == 157
    assert manager.roster_slots_remaining == rules.roster_size - 2
    assert manager.position_counts == {"RB": 1, "WR": 1}
    assert manager.maximum_legal_bid == 157 - rules.min_bid * (manager.roster_slots_remaining - 1)
    assert manager.starter_needs["RB"] == 1
    assert manager.starter_needs["WR"] == 1


@pytest.mark.parametrize("price", [0, 200])
def test_replay_rejects_illegal_price(price):
    rules = league_rules(managers=("Manager_01",))
    sale = Sale("sale-1", "qb_one", "QB One", "QB", "Manager_01", price, 1)
    with pytest.raises(DraftValidationError):
        replay_draft(rules, {"Manager_01": ()}, (sale,))


def test_replay_rejects_duplicate_player_and_position_overflow():
    rules = league_rules(managers=("Manager_01", "Manager_02"), position_max={"QB": 1})
    first = Sale("sale-1", "qb_one", "QB One", "QB", "Manager_01", 5, 1)
    duplicate = Sale("sale-2", "qb_one", "QB One", "QB", "Manager_02", 6, 2)
    overflow = Sale("sale-3", "qb_two", "QB Two", "QB", "Manager_01", 5, 2)

    with pytest.raises(DraftValidationError, match="already owned"):
        replay_draft(rules, {"Manager_01": (), "Manager_02": ()}, (first, duplicate))
    with pytest.raises(DraftValidationError, match="position maximum"):
        replay_draft(rules, {"Manager_01": (), "Manager_02": ()}, (first, overflow))
```

```python
# tests/fixtures.py
from auction_engine.draft_state import LeagueRules


def league_rules(managers=("Manager_01", "Manager_02"), position_max=None):
    maxima = {"QB": 2, "RB": 5, "WR": 5, "TE": 3, "DST": 2, "K": 2}
    maxima.update(position_max or {})
    return LeagueRules(
        managers=tuple(managers), salary_cap=200, roster_size=10, min_bid=1,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "DST": 1, "K": 1},
        position_max=maxima, flex_eligible=("RB", "WR", "TE"),
    )
```

- [ ] **Step 2: Run the tests and verify the missing interfaces fail**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_draft_state.py -q`

Expected: collection fails because `LeagueRules`, `RosterEntry`, `Sale`, and `replay_draft` do not exist.

- [ ] **Step 3: Implement immutable replay state**

```python
# src/auction_engine/draft_state.py
@dataclass(frozen=True)
class LeagueRules:
    managers: tuple[str, ...]
    salary_cap: int
    roster_size: int
    min_bid: int
    starters: Mapping[str, int]
    position_max: Mapping[str, int]
    flex_eligible: tuple[str, ...] = ("RB", "WR", "TE")

    def roster_rules(self) -> RosterRules:
        return RosterRules(
            qb=self.starters.get("QB", 0), rb=self.starters.get("RB", 0),
            wr=self.starters.get("WR", 0), te=self.starters.get("TE", 0),
            flex=self.starters.get("FLEX", 0), dst=self.starters.get("DST", 0),
            k=self.starters.get("K", 0), roster_size=self.roster_size,
            min_bid=self.min_bid,
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
```

Implement `replay_draft` by initializing keepers, sorting sales by `order`, validating each sale against the manager snapshot at that chronological point, and rebuilding immutable manager snapshots. Compute base needs before FLEX: owned RB/WR/TE above base requirements fill FLEX, while owned non-starters remain on the zero-weight bench.

- [ ] **Step 4: Run focused and full tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_draft_state.py -q`

Expected: all draft-state tests pass.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: existing four tests and the new state tests pass.

- [ ] **Step 5: Commit only the domain increment**

```powershell
git add -- src/auction_engine/draft_state.py tests/fixtures.py tests/test_draft_state.py
git commit -m "feat: replay validated draft state"
```

---

### Task 2: Append-Only Ledger and Atomic Persistence

**Files:**
- Create: `src/auction_engine/ledger.py`
- Create: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `Sale` from Task 1.
- Produces: `LedgerEvent`, `DraftLedger`, `empty_ledger`, `record_sale`, `edit_sale`, `undo_sale`, `fold_sales`, `load_ledger`, and `save_ledger_atomic`.

- [ ] **Step 1: Add failing fold and persistence tests**

```python
# tests/test_ledger.py
import json
import pytest

from auction_engine.draft_state import Sale
from auction_engine.ledger import (
    LedgerError, edit_sale, empty_ledger, fold_sales, load_ledger,
    record_sale, save_ledger_atomic, undo_sale,
)


def sale(sale_id="sale-1", player_key="rb_one", price=20, order=1):
    return Sale(sale_id, player_key, player_key.replace("_", " ").title(), "RB", "Manager_01", price, order)


def test_edit_and_undo_append_events_but_fold_active_sales():
    ledger = record_sale(empty_ledger("synthetic-2026"), sale(), event_id="event-1")
    ledger = edit_sale(ledger, "sale-1", sale(price=25), event_id="event-2")
    assert len(ledger.events) == 2
    assert fold_sales(ledger)[0].price == 25

    ledger = undo_sale(ledger, "sale-1", event_id="event-3")
    assert len(ledger.events) == 3
    assert fold_sales(ledger) == ()


def test_edit_preserves_original_sale_order():
    ledger = record_sale(empty_ledger("synthetic-2026"), sale(), event_id="event-1")
    ledger = record_sale(ledger, sale("sale-2", "wr_one", 15, 2), event_id="event-2")
    ledger = edit_sale(ledger, "sale-1", sale(price=30, order=99), event_id="event-3")
    active = fold_sales(ledger)
    assert [(item.sale_id, item.order) for item in active] == [("sale-1", 1), ("sale-2", 2)]


def test_atomic_save_round_trips_and_preserves_old_file_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "draft.json"
    first = record_sale(empty_ledger("synthetic-2026"), sale(), event_id="event-1")
    save_ledger_atomic(path, first)
    before = path.read_bytes()

    second = edit_sale(first, "sale-1", sale(price=30), event_id="event-2")
    monkeypatch.setattr("auction_engine.ledger.os.replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        save_ledger_atomic(path, second)

    assert path.read_bytes() == before
    assert load_ledger(path) == first
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run and verify failure**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_ledger.py -q`

Expected: collection fails because `auction_engine.ledger` is missing.

- [ ] **Step 3: Implement ledger events and stable JSON**

```python
# src/auction_engine/ledger.py
@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    sequence: int
    event_type: Literal["sale_recorded", "sale_edited", "sale_undone"]
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
    return DraftLedger(schema_version=1, draft_id=draft_id)
```

Implement append helpers with contiguous `sequence=len(events)+1`, optional caller IDs for deterministic tests, UUID defaults for the app, active-reference validation through `fold_sales`, and complete JSON dictionaries sorted by key. `save_ledger_atomic` must use `tempfile.NamedTemporaryFile(delete=False, dir=path.parent)`, `flush`, `os.fsync`, and `os.replace`, deleting only its own temporary path on failure.

- [ ] **Step 4: Run focused and full tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_ledger.py -q`

Expected: all ledger tests pass.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the ledger increment**

```powershell
git add -- src/auction_engine/ledger.py tests/test_ledger.py
git commit -m "feat: persist append-only draft ledger"
```

---

### Task 3: Remaining-Roster Optimizer and Deterministic Ties

**Files:**
- Modify: `src/auction_engine/optimizer.py`
- Create: `tests/test_optimizer_live.py`

**Interfaces:**
- Consumes: existing `RosterRules`.
- Produces: `CompletionResult`, `optimize_roster_completion`, and `minimum_cost_completion_for_points` without changing existing optimizer signatures.

- [ ] **Step 1: Add failing owned-roster tests**

```python
# tests/test_optimizer_live.py
import pandas as pd

from auction_engine.optimizer import (
    RosterRules, minimum_cost_completion_for_points, optimize_roster_completion,
)


def test_owned_bench_player_is_locked_to_roster_but_not_forced_to_start():
    rules = RosterRules(qb=1, rb=1, wr=1, te=0, flex=0, dst=0, k=0, roster_size=5)
    owned = pd.DataFrame([
        {"player_key": "rb_low", "player": "RB Low", "position": "RB", "projected_points": 5.0},
        {"player_key": "rb_high", "player": "RB High", "position": "RB", "projected_points": 20.0},
    ])
    available = pd.DataFrame([
        {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 30.0, "price": 10.0},
        {"player_key": "wr_one", "player": "WR One", "position": "WR", "projected_points": 25.0, "price": 10.0},
    ])

    result = optimize_roster_completion(
        available, owned, budget=50, roster_slots_remaining=3,
        position_capacity={"QB": 2, "RB": 3, "WR": 2}, rules=rules,
    )
    assert result.success
    assert set(result.active.player_key) == {"rb_high", "qb_one", "wr_one"}
    assert "rb_low" not in set(result.active.player_key)


def test_forced_candidate_may_be_bench_and_consumes_slot_and_budget_reserve():
    rules = RosterRules(qb=1, rb=1, wr=0, te=0, flex=0, dst=0, k=0, roster_size=3)
    owned = pd.DataFrame([{"player_key": "rb_one", "player": "RB One", "position": "RB", "projected_points": 20.0}])
    available = pd.DataFrame([
        {"player_key": "qb_one", "player": "QB One", "position": "QB", "projected_points": 30.0, "price": 10.0},
        {"player_key": "rb_bench", "player": "RB Bench", "position": "RB", "projected_points": 1.0, "price": 1.0},
    ])
    result = minimum_cost_completion_for_points(
        available, owned, minimum_points=50.0, budget=20,
        roster_slots_remaining=2, position_capacity={"QB": 2, "RB": 2},
        rules=rules, force_acquire=("rb_bench",), zero_cost=("rb_bench",),
    )
    assert result.success
    assert set(result.acquisitions.player_key) == {"qb_one", "rb_bench"}
    assert result.required_budget == 10.0


def test_exact_ties_choose_same_stable_roster_repeatedly():
    rules = RosterRules(qb=1, rb=0, wr=0, te=0, flex=0, dst=0, k=0, roster_size=2)
    available = pd.DataFrame([
        {"player_key": "qb_b", "player": "QB B", "position": "QB", "projected_points": 20.0, "price": 5.0},
        {"player_key": "qb_a", "player": "QB A", "position": "QB", "projected_points": 20.0, "price": 5.0},
    ])
    selected = []
    for _ in range(5):
        result = optimize_roster_completion(available.sample(frac=1), pd.DataFrame(), 20, 2, {"QB": 2}, rules)
        selected.append(tuple(result.active.player_key))
    assert selected == [("qb_a",)] * 5
```

- [ ] **Step 2: Run and verify missing live optimizer interfaces**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_optimizer_live.py -q`

Expected: collection fails because the new completion APIs do not exist.

- [ ] **Step 3: Implement the two-variable completion MILP**

```python
# src/auction_engine/optimizer.py
@dataclass
class CompletionResult:
    active: pd.DataFrame
    acquisitions: pd.DataFrame
    projected_points: float
    required_budget: float
    success: bool
    message: str
```

Add `optimize_roster_completion(available, owned, budget, roster_slots_remaining, position_capacity, rules, points_col="projected_points", cost_col="price")` and `minimum_cost_completion_for_points(available, owned, minimum_points, budget, roster_slots_remaining, position_capacity, rules, points_col="projected_points", cost_col="price", force_acquire=(), zero_cost=())`. Use acquisition variables for available players and active-lineup variables for owned plus available players. Build the core constraints with these exact relationships:

```python
# y_owned and y_available are active variables; x is acquisition.
add(y_available - x, -np.inf, 0.0)
for index in non_forced_indices:
    add(unit(y_available, index) - unit(x, index), 0.0, 0.0)
add(x.sum_row(), -np.inf, float(roster_slots_remaining))
for position, capacity in position_capacity.items():
    add(x.position_row(position), -np.inf, float(capacity))

required_budget = acquisition_costs @ x + rules.min_bid * (roster_slots_remaining - x.sum())
add(required_budget.row, -np.inf, float(budget - rules.min_bid * roster_slots_remaining))
```

Represent the affine reserve by moving its constant term to the constraint bound; do not call `.sum()` on symbolic arrays in production. Enforce `x[index] == 1` for every forced acquisition and substitute zero into `acquisition_costs[index]` for every zero-cost candidate.

Run three deterministic stages for `optimize_roster_completion`: maximum points, minimum completion cost at that points threshold, then stable normalized-key rank at the same points and cost thresholds. Sort every input by `player_key` before matrix construction.

- [ ] **Step 4: Run focused, legacy, and full tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_optimizer_live.py tests/test_optimizer.py tests/test_bid_up_to.py -q`

Expected: live and legacy optimizer behavior passes.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the optimizer increment**

```powershell
git add -- src/auction_engine/optimizer.py tests/test_optimizer_live.py
git commit -m "feat: optimize remaining roster deterministically"
```

---

### Task 4: Two-Layer Dynamic Scarcity

**Files:**
- Create: `src/auction_engine/scarcity.py`
- Create: `tests/test_scarcity.py`

**Interfaces:**
- Consumes: `LeagueRules` and `LeagueDraftState` from Task 1 plus the normalized full player pool.
- Produces: `ScarcityResult` and `calculate_scarcity(players, state, rules, target_manager)`.

- [ ] **Step 1: Add failing league and target scarcity tests**

```python
# tests/test_scarcity.py
from auction_engine.draft_state import RosterEntry, Sale, replay_draft
from auction_engine.scarcity import calculate_scarcity
from tests.fixtures import league_rules, player_pool


def test_opponent_purchase_reduces_outstanding_league_demand_and_pool():
    rules = league_rules(managers=("Manager_01", "Manager_02"))
    players = player_pool(per_position=8)
    empty = replay_draft(rules, {m: () for m in rules.managers}, ())
    after = replay_draft(
        rules, {m: () for m in rules.managers},
        (Sale("sale-1", "rb_00", "RB 00", "RB", "Manager_02", 10, 1),),
    )
    before_scarcity = calculate_scarcity(players, empty, rules, "Manager_01")
    after_scarcity = calculate_scarcity(players, after, rules, "Manager_01")
    assert "rb_00" in set(before_scarcity.selected_available.player_key)
    assert "rb_00" not in set(after_scarcity.selected_available.player_key)
    assert after_scarcity.outstanding_demand["ALL"] == before_scarcity.outstanding_demand["ALL"] - 1


def test_target_needs_are_separate_from_league_replacement_levels():
    rules = league_rules(managers=("Manager_01", "Manager_02"))
    keepers = {
        "Manager_01": (RosterEntry("rb_00", "RB 00", "RB", 10, "keeper"),),
        "Manager_02": (),
    }
    state = replay_draft(rules, keepers, ())
    scarcity = calculate_scarcity(player_pool(per_position=8), state, rules, "Manager_01")
    assert scarcity.target_needs["RB"] == 1
    assert scarcity.target_needs["FLEX"] == 2
    assert "RB" in scarcity.league_replacement_levels
```

Add `player_pool` to `tests/fixtures.py` with deterministic `player_key`, `player`, `position`, `projected_points`, `normalized_aav`, and `aav` columns for all enabled positions.

- [ ] **Step 2: Run and verify failure**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_scarcity.py -q`

Expected: collection fails because `auction_engine.scarcity` is missing.

- [ ] **Step 3: Implement manager-assignment scarcity MILP**

```python
# src/auction_engine/scarcity.py
@dataclass(frozen=True)
class ScarcityResult:
    league_replacement_levels: dict[str, float]
    outstanding_demand: dict[str, int]
    target_needs: dict[str, int]
    selected_available: pd.DataFrame


def calculate_scarcity(
    players: pd.DataFrame,
    state: LeagueDraftState,
    rules: LeagueRules,
    target_manager: str,
    points_col: str = "projected_points",
) -> ScarcityResult:
    managers = tuple(sorted(state.managers))
    pool = players.sort_values("player_key").reset_index(drop=True)
    assignment = _solve_assignment_matrix(pool, state, rules, managers, points_col)
    selected_mask = assignment.any(axis=0) & ~pool.player_key.isin(state.owned_player_keys).to_numpy()
    selected = pool.loc[selected_mask].copy()
    levels = {
        position: float(group[points_col].min())
        for position, group in selected.groupby("position", sort=True)
    }
    demand = selected.position.value_counts().sort_index().astype(int).to_dict()
    demand["ALL"] = int(len(selected))
    target = state.managers[target_manager]
    target_needs = {**target.starter_needs, "FLEX": target.flex_need}
    return ScarcityResult(levels, demand, target_needs, selected)
```

Implement `_solve_assignment_matrix` in the same file as a league MILP containing one active variable per eligible manager/player pair. Owned players are eligible only for their manager; unowned players may be assigned to at most one manager. Respect every manager's active lineup constraints, remaining roster slots, and position capacity. Return a boolean `manager × player` NumPy matrix. Replacement levels are the minimum projected points among selected still-available players at each position. `target_needs` comes directly from the replayed target snapshot and adds `FLEX`.

- [ ] **Step 4: Run focused and full tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_scarcity.py tests/test_replacement.py -q`

Expected: both dynamic and legacy scarcity tests pass.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the scarcity increment**

```powershell
git add -- src/auction_engine/scarcity.py tests/fixtures.py tests/test_scarcity.py
git commit -m "feat: calculate two-layer live scarcity"
```

---

### Task 5: Pure Full Recalculation and Stateful Bid-Up-To

**Files:**
- Modify: `src/auction_engine/bid_up_to.py`
- Create: `src/auction_engine/live_draft.py`
- Create: `tests/test_live_recalculation.py`

**Interfaces:**
- Consumes: replay state, scarcity, completion optimizer, and existing market helpers.
- Produces: `MarketBaseline`, `DraftInputs`, `RecalculationResult`, `recalculate_draft`, `canonical_snapshot`, and `bid_up_to_remaining`.

- [ ] **Step 1: Add failing transaction-recalculation tests**

```python
# tests/test_live_recalculation.py
from auction_engine.draft_state import Sale
from auction_engine.live_draft import DraftInputs, MarketBaseline, canonical_snapshot, recalculate_draft
from tests.fixtures import keeper_map, league_rules, player_pool


def inputs():
    rules = league_rules()
    return DraftInputs(
        rules=rules,
        keepers=keeper_map(rules.managers),
        players=player_pool(per_position=12),
        target_manager="Manager_01",
        market=MarketBaseline(initial_remaining_capital=398.0, initial_remaining_baseline_value=390.0),
        top_n=12,
    )


def test_sale_removes_player_updates_capital_and_recalculates_board():
    initial = recalculate_draft(inputs(), ())
    sale = Sale("sale-1", "rb_00", "RB 00", "RB", "Manager_02", 25, 1)
    after = recalculate_draft(inputs(), (sale,))

    assert "rb_00" in set(initial.board.player_key)
    assert "rb_00" not in set(after.available.player_key)
    assert after.remaining_capital == initial.remaining_capital - 25
    assert after.market_inflation != initial.market_inflation
    compared = initial.board[["player_key", "bid_up_to"]].merge(
        after.board[["player_key", "bid_up_to"]], on="player_key", suffixes=("_before", "_after")
    ).dropna()
    assert compared.bid_up_to_before.ne(compared.bid_up_to_after).any()


def test_target_purchase_is_owned_charged_and_may_be_benched():
    purchase = Sale("sale-1", "rb_11", "RB 11", "RB", "Manager_01", 2, 1)
    result = recalculate_draft(inputs(), (purchase,))
    target = result.state.managers["Manager_01"]
    assert target.budget_remaining == 198 - 2
    assert "rb_11" in {item.player_key for item in target.roster}
    assert "rb_11" not in set(result.target_lineup.player_key)


def test_canonical_snapshot_is_identical_for_equal_sales():
    sales = (Sale("sale-1", "wr_00", "WR 00", "WR", "Manager_02", 20, 1),)
    assert canonical_snapshot(recalculate_draft(inputs(), sales)) == canonical_snapshot(recalculate_draft(inputs(), sales))
```

Add this fixture beside `player_pool` in `tests/fixtures.py`:

```python
def keeper_map(managers):
    return {
        manager: (
            (RosterEntry("rb_keeper", "RB Keeper", "RB", 2, "keeper"),)
            if index == 0 else ()
        )
        for index, manager in enumerate(managers)
    }
```

- [ ] **Step 2: Run and verify failure**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_live_recalculation.py -q`

Expected: collection fails because `auction_engine.live_draft` is missing.

- [ ] **Step 3: Implement remaining-roster Bid-Up-To**

```python
# src/auction_engine/bid_up_to.py
def bid_up_to_remaining(
    available: pd.DataFrame,
    owned: pd.DataFrame,
    player_key: str,
    budget: float,
    roster_slots_remaining: int,
    position_capacity: Mapping[str, int],
    rules: RosterRules,
    market_price_col: str = "inflated_aav",
    points_col: str = "projected_points",
    maximum_legal_bid: int | None = None,
) -> int:
    if player_key not in set(available.player_key):
        raise KeyError(player_key)
    alternative = optimize_roster_completion(
        available.loc[~available.player_key.eq(player_key)], owned, budget,
        roster_slots_remaining, position_capacity, rules, points_col, market_price_col,
    )
    if not alternative.success:
        return 0
    qualifying = minimum_cost_completion_for_points(
        available, owned, alternative.projected_points, budget,
        roster_slots_remaining, position_capacity, rules, points_col,
        market_price_col, force_acquire=(player_key,), zero_cost=(player_key,),
    )
    if not qualifying.success:
        return 0
    ceiling = max(0, math.floor(budget - qualifying.required_budget + 1e-9))
    return min(ceiling, maximum_legal_bid) if maximum_legal_bid is not None else ceiling
```

This solves the alternative without the candidate, then the minimum-cost threshold completion with the candidate forced onto the roster at zero cost. It subtracts the other completion cost from remaining budget, floors to integer dollars, and caps at `maximum_legal_bid`.

- [ ] **Step 4: Implement pure recalculation**

```python
# src/auction_engine/live_draft.py
@dataclass(frozen=True)
class MarketBaseline:
    initial_remaining_capital: float
    initial_remaining_baseline_value: float


@dataclass(frozen=True)
class DraftInputs:
    rules: LeagueRules
    keepers: Mapping[str, tuple[RosterEntry, ...]]
    players: pd.DataFrame
    target_manager: str
    market: MarketBaseline
    top_n: int = 80


@dataclass
class RecalculationResult:
    state: LeagueDraftState
    available: pd.DataFrame
    remaining_capital: float
    remaining_baseline_value: float
    market_inflation: float
    scarcity: ScarcityResult
    target_lineup: pd.DataFrame
    board: pd.DataFrame


def recalculate_draft(inputs: DraftInputs, active_sales: Iterable[Sale]) -> RecalculationResult:
    sales = tuple(sorted(active_sales, key=lambda sale: sale.order))
    state = replay_draft(inputs.rules, inputs.keepers, sales)
    available = inputs.players.loc[~inputs.players.player_key.isin(state.owned_player_keys)].copy()
    purchased_value = inputs.players.loc[
        inputs.players.player_key.isin({sale.player_key for sale in sales}), "normalized_aav"
    ].sum()
    remaining_capital = max(0.0, inputs.market.initial_remaining_capital - sum(sale.price for sale in sales))
    remaining_baseline = inputs.market.initial_remaining_baseline_value - float(purchased_value)
    factor = market_inflation(remaining_capital, remaining_baseline)
    available["inflated_aav"] = (available["normalized_aav"] * factor).clip(lower=1).round(1)
    scarcity = calculate_scarcity(inputs.players, state, inputs.rules, inputs.target_manager)
    available["replacement_points"] = available.position.map(scarcity.league_replacement_levels)
    available["vor"] = (available.projected_points - available.replacement_points).fillna(0.0)
    target = state.managers[inputs.target_manager]
    owned = _owned_projection_rows(inputs.players, target.roster)
    lineup_result = optimize_roster_completion(
        available.rename(columns={"inflated_aav": "price"}), owned,
        target.budget_remaining, target.roster_slots_remaining,
        target.position_capacity, inputs.rules.roster_rules(),
    )
    board = _recalculate_bid_board(available, owned, target, inputs)
    return RecalculationResult(
        state, available, remaining_capital, remaining_baseline, factor,
        scarcity, lineup_result.active, board,
    )


def canonical_snapshot(result: RecalculationResult) -> dict[str, object]:
    return {
        "managers": {
            name: {
                "budget": manager.budget_remaining,
                "max_bid": manager.maximum_legal_bid,
                "roster": sorted((entry.player_key, entry.position, entry.price) for entry in manager.roster),
            }
            for name, manager in sorted(result.state.managers.items())
        },
        "scarcity": {key: round(value, 8) for key, value in sorted(result.scarcity.league_replacement_levels.items())},
        "lineup": sorted(result.target_lineup.player_key.tolist()),
        "bid_up_to": {
            row.player_key: int(row.bid_up_to)
            for row in result.board.dropna(subset=["bid_up_to"]).sort_values("player_key").itertuples()
        },
    }
```

Implement `_owned_projection_rows` and `_recalculate_bid_board` in the same file. The latter sorts candidates by `vor`, projected points, then `player_key`, calls `bid_up_to_remaining` for at most `inputs.top_n`, and writes nullable integer Bid-Up-To values for the remaining board rows.

- [ ] **Step 5: Run focused, legacy, and full tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_live_recalculation.py tests/test_bid_up_to.py tests/test_optimizer.py tests/test_replacement.py -q`

Expected: dynamic and legacy calculations pass.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the recalculation increment**

```powershell
git add -- src/auction_engine/bid_up_to.py src/auction_engine/live_draft.py tests/test_live_recalculation.py
git commit -m "feat: recalculate live auction board"
```

---

### Task 6: Validated Persisted Session and 30–50 Sale Acceptance

**Files:**
- Modify: `src/auction_engine/live_draft.py`
- Create: `tests/test_live_session_acceptance.py`

**Interfaces:**
- Consumes: `DraftInputs`, ledger append/fold/save functions, and `recalculate_draft`.
- Produces: `LiveDraftSession.load`, `snapshot`, `record_sale`, `edit_sale`, and `undo_sale`.

- [ ] **Step 1: Add failing acceptance and rollback tests**

```python
# tests/test_live_session_acceptance.py
import pytest

from auction_engine.draft_state import DraftValidationError
from auction_engine.live_draft import LiveDraftSession, canonical_snapshot
from tests.fixtures import acceptance_inputs, legal_sale_sequence


def test_forty_sales_reload_undo_edit_and_replay_identically(tmp_path):
    path = tmp_path / "draft.json"
    session = LiveDraftSession.create(path, acceptance_inputs(), draft_id="synthetic-2026")
    sale_ids = []
    for player_key, manager, price in legal_sale_sequence(count=40):
        sale_ids.append(session.record_sale(player_key, manager, price).sale_id)

    after_sales = canonical_snapshot(session.snapshot())
    assert canonical_snapshot(LiveDraftSession.load(path, acceptance_inputs()).snapshot()) == after_sales

    for sale_id in sale_ids[-3:]:
        session.undo_sale(sale_id)
    after_undo = canonical_snapshot(session.snapshot())
    assert canonical_snapshot(LiveDraftSession.load(path, acceptance_inputs()).snapshot()) == after_undo

    session.edit_sale(sale_ids[4], price=2)
    after_edit = canonical_snapshot(session.snapshot())
    reloaded = LiveDraftSession.load(path, acceptance_inputs())
    assert canonical_snapshot(reloaded.snapshot()) == after_edit
    assert canonical_snapshot(reloaded.snapshot()) == canonical_snapshot(reloaded.snapshot())


def test_invalid_historical_edit_does_not_replace_valid_ledger(tmp_path):
    path = tmp_path / "draft.json"
    session = LiveDraftSession.create(path, acceptance_inputs(), draft_id="synthetic-2026")
    first = session.record_sale("rb_00", "Manager_01", 20)
    session.record_sale("wr_00", "Manager_01", 168)
    before = path.read_bytes()

    with pytest.raises(DraftValidationError):
        session.edit_sale(first.sale_id, price=30)

    assert path.read_bytes() == before
```

- [ ] **Step 2: Run and verify failure**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_live_session_acceptance.py -q`

Expected: collection fails because `LiveDraftSession` and acceptance fixtures do not exist.

- [ ] **Step 3: Implement validate-before-save session operations**

```python
# src/auction_engine/live_draft.py
class LiveDraftSession:
    @classmethod
    def create(cls, path: Path, inputs: DraftInputs, draft_id: str) -> "LiveDraftSession":
        ledger = empty_ledger(draft_id)
        result = recalculate_draft(inputs, ())
        save_ledger_atomic(path, ledger)
        return cls(path, inputs, ledger, result)

    @classmethod
    def load(cls, path: Path, inputs: DraftInputs) -> "LiveDraftSession":
        ledger = load_ledger(path)
        result = recalculate_draft(inputs, fold_sales(ledger))
        return cls(path, inputs, ledger, result)

    def snapshot(self) -> RecalculationResult:
        return self.result

    def _commit(self, candidate: DraftLedger) -> None:
        result = recalculate_draft(self.inputs, fold_sales(candidate))
        save_ledger_atomic(self.path, candidate)
        self.ledger, self.result = candidate, result

    def record_sale(self, player_key: str, manager: str, price: int) -> Sale:
        order = max(
            (event.sale.order for event in self.ledger.events if event.event_type == "sale_recorded" and event.sale is not None),
            default=0,
        ) + 1
        sale = self._canonical_sale(player_key, manager, price, order)
        self._commit(ledger_record_sale(self.ledger, sale))
        return sale

    def edit_sale(self, sale_id: str, *, player_key: str | None = None, manager: str | None = None, price: int | None = None) -> Sale:
        current = next(sale for sale in fold_sales(self.ledger) if sale.sale_id == sale_id)
        corrected = self._canonical_sale(
            player_key or current.player_key, manager or current.manager,
            current.price if price is None else price, current.order, sale_id=sale_id,
        )
        self._commit(ledger_edit_sale(self.ledger, sale_id, corrected))
        return corrected

    def undo_sale(self, sale_id: str) -> None:
        self._commit(ledger_undo_sale(self.ledger, sale_id))
```

Implement `__init__` to store `path`, `inputs`, `ledger`, and `result`. Implement `_canonical_sale` by selecting exactly one projection row for `player_key`, taking display name and position from that row, generating a UUID sale ID only when one is not supplied, and returning `Sale`. The shared `_commit` folds the candidate, runs complete recalculation, saves atomically only after success, and then replaces the in-memory ledger/result. Player display name and position always come from the canonical projection pool, never from UI input.

Add deterministic `acceptance_inputs` and `legal_sale_sequence` helpers to `tests/fixtures.py`. Use ten anonymized managers, a roster size that admits at least 50 legal sales, and a sufficiently deep pool at every enabled position. Keep test `top_n` small enough for fast CI while still comparing recalculated Bid-Up-To values.

- [ ] **Step 4: Run the acceptance test repeatedly**

Run: `1..3 | ForEach-Object { & '.\.venv\Scripts\python.exe' -m pytest tests/test_live_session_acceptance.py -q }`

Expected: all three runs pass with identical canonical snapshots.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: the complete suite passes.

- [ ] **Step 5: Commit the persisted-session increment**

```powershell
git add -- src/auction_engine/live_draft.py tests/fixtures.py tests/test_live_session_acceptance.py
git commit -m "feat: validate and replay persisted draft sessions"
```

---

### Task 7: Build Artifacts and Minimal Streamlit Record/Edit/Undo Workflow

**Files:**
- Modify: `src/auction_engine/live_draft.py`
- Modify: `scripts/build_draft_board.py`
- Modify: `app/streamlit_app.py`
- Create: `tests/test_build_artifacts.py`

**Interfaces:**
- Consumes: `DraftInputs`, `MarketBaseline`, and `LiveDraftSession`.
- Produces: `load_draft_inputs`, `data/processed/draft_pool_2026.csv`, `data/processed/draft_context_2026.json`, initial `draft_board_2026.csv`, and a persistent Streamlit workflow.

- [ ] **Step 1: Add failing artifact test around a pure builder helper**

```python
# tests/test_build_artifacts.py
import json

from scripts.build_draft_board import write_live_artifacts
from tests.fixtures import acceptance_inputs


def test_live_artifacts_include_full_pool_and_market_context(tmp_path):
    inputs = acceptance_inputs()
    write_live_artifacts(inputs, tmp_path)
    context = json.loads((tmp_path / "draft_context_2026.json").read_text())
    assert (tmp_path / "draft_pool_2026.csv").exists()
    assert (tmp_path / "draft_board_2026.csv").exists()
    assert context["target_manager"] == "Manager_01"
    assert context["initial_remaining_capital"] == inputs.market.initial_remaining_capital
```

- [ ] **Step 2: Run and verify failure**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_build_artifacts.py -q`

Expected: import fails because `write_live_artifacts` does not exist.

- [ ] **Step 3: Extract artifact output from the build script**

```python
# scripts/build_draft_board.py
def write_live_artifacts(inputs: DraftInputs, output_dir: Path) -> RecalculationResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = recalculate_draft(inputs, ())
    inputs.players.to_csv(output_dir / "draft_pool_2026.csv", index=False)
    (output_dir / "draft_context_2026.json").write_text(
        json.dumps({
            "draft_id": "cbxii-2026",
            "target_manager": inputs.target_manager,
            "initial_remaining_capital": inputs.market.initial_remaining_capital,
            "initial_remaining_baseline_value": inputs.market.initial_remaining_baseline_value,
            "top_n": inputs.top_n,
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result.board.to_csv(output_dir / "draft_board_2026.csv", index=False)
    return result
```

Modify `main()` to retain every normalized projection row in `DraftInputs.players`, construct anonymized-agnostic manager names from the keeper input, and call this helper. Remove real manager defaults from public code; require `--target-manager` or obtain it from a gitignored private input.

Add this loader to `src/auction_engine/live_draft.py` and cover its round trip in `tests/test_build_artifacts.py`:

```python
def load_draft_inputs(
    config_path: Path,
    pool_path: Path,
    context_path: Path,
    keepers_path: Path,
) -> DraftInputs:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    players = pd.read_csv(pool_path)
    keeper_rows = pd.read_csv(keepers_path)
    managers = tuple(keeper_rows.manager.drop_duplicates())
    rules = league_rules_from_mapping(config, managers)
    active = keeper_rows.loc[
        keeper_rows.status.isin(["likely", "confirmed"]) & keeper_rows.player.notna()
    ].copy()
    active["player_key"] = active.player.map(normalize_player_key)
    keepers = _keeper_entries_by_manager(active, managers, players)
    return DraftInputs(
        rules=rules,
        keepers=keepers,
        players=players,
        target_manager=context["target_manager"],
        market=MarketBaseline(
            context["initial_remaining_capital"],
            context["initial_remaining_baseline_value"],
        ),
        top_n=int(context.get("top_n", 80)),
    )
```

Implement `normalize_player_key`, `league_rules_from_mapping`, and `_keeper_entries_by_manager` beside the loader. `normalize_player_key` uses the suffix-stripping behavior currently local to `scripts/build_draft_board.py`; modify that script to import the shared function. Keeper matching uses the pool's existing `player_key`; unmatched active keepers raise `DraftValidationError` rather than silently disappearing.

- [ ] **Step 4: Replace Streamlit budget bookkeeping with persisted session calls**

Update `app/streamlit_app.py` to:

```python
ledger_path = ROOT / "state" / "draft_2026.json"
session = LiveDraftSession.load(ledger_path, inputs) if ledger_path.exists() else LiveDraftSession.create(ledger_path, inputs, context["draft_id"])
result = session.snapshot()
```

The purchase form must select from `result.available`, select from configured managers, cap price entry at the selected manager's `maximum_legal_bid`, call `session.record_sale`, and rerun. Add an immediately visible “Undo last sale” action and an edit expander that selects an active sale and calls `session.edit_sale`. Display the recalculated board, all manager summaries, and the active ledger. Catch domain errors and show their messages without overwriting the ledger.

- [ ] **Step 5: Run artifact, full, and import checks**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_build_artifacts.py -q`

Expected: artifact test passes.

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: complete suite passes.

Run: `& '.\.venv\Scripts\python.exe' -m compileall -q src app scripts`

Expected: exit code 0.

- [ ] **Step 6: Commit the minimal application integration**

```powershell
git add -- src/auction_engine/live_draft.py scripts/build_draft_board.py app/streamlit_app.py tests/test_build_artifacts.py
git commit -m "feat: connect Streamlit to live draft ledger"
```

---

### Task 8: Documentation, Privacy Guard, and Final Acceptance

**Files:**
- Modify: `.gitignore`
- Modify: `docs/build-status.md`
- Modify: `.github/workflows/test-engine.yml`
- Create: `tests/test_privacy.py`

**Interfaces:**
- Consumes: all Phase 1 behavior.
- Produces: verified documentation and a regression guard against committed identities/state.

- [ ] **Step 1: Add a failing public-source privacy test**

```python
# tests/test_privacy.py
from pathlib import Path
import subprocess


def test_public_application_source_uses_no_embedded_manager_roster():
    source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
    assert "Stretz" not in source
    assert "Tornabene" not in source


def test_live_state_is_not_tracked():
    tracked = subprocess.run(
        ["git", "-c", f"safe.directory={Path.cwd().as_posix()}", "ls-files"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert not any(path.startswith("state/") for path in tracked)
```

- [ ] **Step 2: Run the privacy test and verify it catches the current hardcoded identities before the app change, or passes after Task 7 removed them**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_privacy.py -q`

Expected: pass after Task 7; if it fails, remove only the hardcoded public identity source and rerun.

- [ ] **Step 3: Harden ignore patterns for generated metadata and known private root inputs**

Add these public-safe patterns to `.gitignore` without moving or deleting user files:

```gitignore
*.egg-info/
~$*.xlsx

# Private league source files that may exist in a local workspace root
/*keeper*.xlsx
/*Keeper*.xlsx
/*Draft History.txt
/*Draft Results by year.xlsx
/*Draft*Tracker*.xlsx
/*Manager History.txt
/*manager_aliases.yaml
/*pre-draft rosters.txt
/*League Settings*.md
```

- [ ] **Step 4: Update CI and build status with verified commands**

Change `.github/workflows/test-engine.yml` to run `pytest -q` so every new state and acceptance test runs in CI. Update `docs/build-status.md` to mark only the implemented Phase 1 items complete and record the synthetic replay count exercised by the acceptance test.

- [ ] **Step 5: Run final acceptance and privacy verification**

Run: `& '.\.venv\Scripts\python.exe' -m pytest -q`

Expected: all tests pass.

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/test_live_session_acceptance.py -q`

Expected: the 40-sale reload/undo/edit test passes.

Run: `& '.\.venv\Scripts\python.exe' -m compileall -q src app scripts`

Expected: exit code 0.

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short`

Expected: only the intentional tracked Phase 1 files appear; private league files and `state/` do not appear.

- [ ] **Step 6: Commit the verified Phase 1 completion**

```powershell
git add -- .gitignore docs/build-status.md .github/workflows/test-engine.yml tests/test_privacy.py
git commit -m "docs: mark replayable live draft phase complete"
```
