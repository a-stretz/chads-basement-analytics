# Phase 2 Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reload keeper decisions deterministically and support DST/K as legal, salary-reserving roster requirements without projecting or valuing them.

**Architecture:** Generated context stores pre-keeper market inputs; the loader derives the active keeper-adjusted baseline on every reload. Full league rules drive replay and legal bids, while derived modeled rules drive scarcity, active-lineup optimization, recommendations, and Bid-Up-To.

**Tech Stack:** Python 3.12, pandas, PyYAML, scipy MILP, Streamlit, pytest

**Spec:** `docs/superpowers/specs/2026-08-26-phase-2-configuration-design.md`

## Global Constraints

- Preserve the Phase 1 append-only ledger, atomic persistence, and canonical replay behavior.
- Keep private keeper selections and non-anonymized manager data untracked.
- Maximize active modeled starter/FLEX points; do not add bench-point weights.
- Do not add DST/K projections, fallback values, or valuation heuristics.
- Run the full test suite after every independently testable production change.

---

### Task 1: Dynamic keeper market context

**Files:**
- Modify: `src/auction_engine/live_draft.py`
- Modify: `scripts/build_draft_board.py`
- Modify: `tests/test_build_artifacts.py`

**Interfaces:**
- Consumes: existing `MarketBaseline`, normalized pool, and private keeper CSV.
- Produces: context schema 2 fields `deployable_league_capital` and `full_baseline_value`; loader-derived current `MarketBaseline`.

- [x] **Step 1: Write failing loader tests**

Add tests that write one active keeper, generate one schema-2 context, then
reload the same pool after `likely -> confirmed` and `confirmed -> opt_out`.
Assert the confirmed snapshot is identical and the opt-out baseline gains the
literal keeper cost and normalized value. Add explicit failures for an unknown
status and a schema-1 context.

- [x] **Step 2: Run the focused tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_artifacts.py -q`

Expected: failures because context has no schema/pre-keeper fields and the
loader reuses baked keeper-adjusted values.

- [x] **Step 3: Implement current keeper derivation**

Normalize keeper statuses, validate the supported status set, build active
entries, and derive:

```python
MarketBaseline(
    initial_remaining_capital=deployable_league_capital - active_keeper_spend,
    initial_remaining_baseline_value=full_baseline_value - active_keeper_normalized_aav,
)
```

Make `write_live_artifacts` reconstruct and store pre-keeper values plus
`schema_version: 2`. Reject older contexts with an actionable rebuild error.

- [x] **Step 4: Run focused and full tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_artifacts.py -q`

Run: `.venv/Scripts/python.exe -m pytest -q`

- [x] **Step 5: Commit**

```bash
git add src/auction_engine/live_draft.py scripts/build_draft_board.py tests/test_build_artifacts.py
git commit -m "feat: recalculate keeper market state on load"
```

### Task 2: Separate legal roster rules from modeled positions

**Files:**
- Modify: `src/auction_engine/draft_state.py`
- Modify: `src/auction_engine/live_draft.py`
- Modify: `src/auction_engine/scarcity.py`
- Modify: `tests/fixtures.py`
- Modify: `tests/test_draft_state.py`
- Modify: `tests/test_live_recalculation.py`
- Modify: `tests/test_scarcity.py`
- Modify: `tests/test_optimizer_live.py`

**Interfaces:**
- Consumes: `model.modeled_positions` and full `LeagueRules`.
- Produces: `LeagueRules.modeled_roster_rules() -> RosterRules` and modeled-only live board/scarcity.

- [x] **Step 1: Write failing K/DST separation tests**

Add a live recalculation fixture with `DST: 1`, `K: 1`, full roster size, and no
DST/K projection rows. Assert recalculation succeeds, only QB/RB/WR/TE appear in
the board and scarcity, DST/K remain in manager needs, and maximum legal bid
reserves all remaining slots. Parameterize K as zero and one.

- [x] **Step 2: Run focused tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_recalculation.py tests/test_scarcity.py tests/test_draft_state.py -q`

Expected: MILP infeasibility because Phase 1 requires DST/K active rows.

- [x] **Step 3: Implement modeled rule derivation**

Add `modeled_positions` to `LeagueRules` and return a `RosterRules` copy with
unmodeled starter positions set to zero. Read and validate the field from YAML.
When an unmodeled required position has starter count zero, set its effective
position maximum to zero so `K: 0` disables K acquisitions.

- [x] **Step 4: Route live scoring through modeled rules**

Keep replay on full rules. Filter scarcity assignments, target-owned scoring
rows, candidate board rows, and Bid-Up-To inputs to modeled positions. Preserve
`roster_slots_remaining` and full budget in completion calls so every unfilled
slot still reserves `min_bid`.

- [x] **Step 5: Run focused and full tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_recalculation.py tests/test_scarcity.py tests/test_draft_state.py tests/test_optimizer_live.py -q`

Run: `.venv/Scripts/python.exe -m pytest -q`

- [x] **Step 6: Commit**

```bash
git add src/auction_engine/draft_state.py src/auction_engine/live_draft.py src/auction_engine/scarcity.py tests
git commit -m "feat: separate legal and modeled roster positions"
```

### Task 3: Projection-free DST/K ledger entries

**Files:**
- Modify: `src/auction_engine/live_draft.py`
- Modify: `tests/test_live_session_acceptance.py`

**Interfaces:**
- Consumes: `LiveDraftSession`, ledger replay, and `LeagueRules.modeled_positions`.
- Produces: `LiveDraftSession.record_unmodeled_sale(player, position, manager, price) -> Sale`.

- [x] **Step 1: Write a failing replay test**

Record a projection-free K sale at $1, assert its deterministic key starts with
`unmodeled-k-`, budget and slots each fall by one, K need becomes zero, and the
maximum legal bid is unchanged because one reserved dollar and one open slot
were both consumed. Reload, edit the price, undo the sale, and compare canonical
snapshots after each persistence transition.

- [x] **Step 2: Run focused test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_session_acceptance.py -q`

Expected: failure because the session has no projection-free sale API and owned
players must exist in the projection pool.

- [x] **Step 3: Implement the minimal session API**

Generate a key from `unmodeled-{position}-{normalize_player_key(player)}`. Permit
only enabled positions outside `modeled_positions`, validate non-empty names,
and send the resulting `Sale` through the unchanged append-only ledger and full
recalculation. Allow price/manager edits of an existing projection-free sale and
skip projection identity validation only for enabled unmodeled positions.

- [x] **Step 4: Run focused and full tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_session_acceptance.py -q`

Run: `.venv/Scripts/python.exe -m pytest -q`

- [x] **Step 5: Commit**

```bash
git add src/auction_engine/live_draft.py tests/test_live_session_acceptance.py
git commit -m "feat: record projection-free roster purchases"
```

### Task 4: Configuration, Streamlit, and documentation

**Files:**
- Modify: `config/cbxii.yaml`
- Modify: `app/streamlit_app.py`
- Modify: `README.md`
- Modify: `docs/methodology.md`
- Modify: `docs/build-status.md`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Consumes: loader keeper status summary and `record_unmodeled_sale`.
- Produces: offense-only recommendation UI plus a compact DST/K accounting form.

- [x] **Step 1: Add the public configuration**

Set `model.modeled_positions: [QB, RB, WR, TE]` and remove the duplicate
`kicker_enabled`/`defense_enabled` flags. Keep `starters.DST` and `starters.K`
as the legal switches.

- [x] **Step 2: Integrate the app**

Keep the primary searchable sale selector on modeled players. Add a collapsed
`Record DST/K purchase` form that calls `record_unmodeled_sale`, show keeper
status counts read-only, and make the edit labels support active manual sales.

- [x] **Step 3: Update human documentation**

Document current keeper reload behavior, legal-versus-modeled positions, K zero
or one, projection-free entries, and the Phase 2 acceptance evidence. Remove
README/methodology claims that D/ST is optimized.

- [x] **Step 4: Run verification**

Run: `.venv/Scripts/python.exe -m pytest -q`

Run: `.venv/Scripts/python.exe -m compileall -q src scripts app`

Run: `git status --short`

- [x] **Step 5: Commit**

```bash
git add config/cbxii.yaml app/streamlit_app.py README.md docs tests/test_privacy.py
git commit -m "docs: complete phase 2 configuration workflow"
```

