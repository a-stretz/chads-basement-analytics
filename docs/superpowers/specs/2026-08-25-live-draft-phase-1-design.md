# Live Draft Phase 1 Design

## Purpose

Phase 1 turns the existing static auction board into a reliable, replayable live-draft decision engine. A saved transaction ledger becomes the only mutable draft input. Every budget, roster, scarcity measure, optimization result, and Bid-Up-To value is derived from league configuration, keeper inputs, projections, and that ledger.

Phase 1 is complete only when a 30–50 purchase synthetic draft can be saved, reloaded after an application refresh, partially undone, historically edited, and replayed with identical manager budgets, rosters, and Bid-Up-To values at every equivalent ledger state.

## Scope

Phase 1 includes:

- an append-only, replayable draft ledger under the gitignored `state/` directory;
- deterministic reconstruction of all managers' budgets, rosters, open slots, positional counts, remaining needs, and maximum legal bids;
- transaction validation before persistence;
- atomic ledger persistence;
- removal of purchased players from the available pool;
- dynamic remaining purchasing power and market inflation using the existing market methodology;
- two-layer scarcity recalculation;
- target-manager optimization that locks acquired players onto the roster while maximizing active starter scoring;
- recalculated Bid-Up-To values after every active transaction change;
- deterministic optimizer tie-breaking;
- undo and historical edit operations expressed as ledger events;
- state-transition, persistence, recalculation, and acceptance tests;
- current `docs/build-status.md` documentation.

Phase 1 does not include:

- a new projection aggregation method;
- a new player valuation formula;
- expected clearing-price heuristics;
- bench-point utility;
- scenario simulation or uncertainty objectives;
- manager-behavior priors;
- keeper confirmation controls or kicker fallback work assigned to Phase 2;
- the complete draft-night interface redesign assigned to Phase 3;
- additional reproducibility or migration infrastructure beyond the minimal ledger schema version required to read Phase 1 state safely.

## Existing Methodology Preserved

The implementation must preserve these existing model decisions unless a failing test exposes a specific defect:

1. Public AAV is normalized to the league's historically deployed auction capital.
2. Keeper salaries and normalized keeper values adjust the remaining market.
3. Replacement level is solved dynamically rather than taken from hard-coded positional ranks.
4. The target objective maximizes projected active starter points.
5. Unfilled bench positions reserve the legal minimum bid and contribute no projected points to the objective.
6. Bid-Up-To is an opportunity-cost ceiling: the maximum legal candidate price that preserves the best attainable active-lineup points relative to the alternative without that candidate.

Dynamic recalculation changes the inputs to these methods after a transaction; it does not replace the methods.

## Component Boundaries

### Ledger

The ledger owns event serialization, append operations, atomic persistence, and event folding. It does not calculate budgets, optimize rosters, or value players.

The on-disk document has a minimal envelope:

```json
{
  "schema_version": 1,
  "draft_id": "cbxii-2026",
  "events": []
}
```

Every event contains:

- a stable event ID;
- a strictly increasing integer sequence number;
- an event type;
- the event payload required by that type.

Wall-clock timestamps may be retained for display, but sequence number is the only ordering authority.

Supported event types are:

- `sale_recorded`: creates a sale with a stable sale ID, normalized player identity, display name, position, manager, and integer price;
- `sale_edited`: references an active sale ID and supplies its complete corrected sale payload;
- `sale_undone`: references an active sale ID and makes it inactive.

Edits and undo operations append events. They never rewrite or delete earlier events. An edit replaces the referenced sale's complete active payload during folding. An undone sale cannot be edited or undone again unless a future design explicitly adds restoration; restoration is outside Phase 1.

### Draft state

Draft state is an immutable replay result. It contains the ordered active sales and a state object for every manager. Each manager state contains:

- initial cap;
- keeper spend;
- auction spend;
- remaining budget;
- keeper and purchased roster entries;
- total roster slots remaining;
- position counts;
- position capacity remaining;
- outstanding base starter needs;
- outstanding FLEX need;
- maximum legal bid.

Maximum legal bid is:

```text
max(0, remaining budget - minimum bid × (remaining roster slots - 1))
```

It is zero when no roster slot remains. Keepers occupy roster slots and position capacity from the initial state.

### Recalculation service

The recalculation service is a pure orchestration layer. Given config, projections, keepers, target manager, and folded active sales, it returns one result containing:

- the rebuilt draft state;
- the available player pool;
- remaining league purchasing power;
- current market inflation;
- league-wide scarcity;
- target-manager scarcity;
- the target's optimal active lineup;
- the current recommendation board and Bid-Up-To values.

The service performs no disk writes and contains no Streamlit state. Equal normalized inputs must produce equal canonical outputs.

## Replay and Validation

Replay starts from an empty auction plus configured keepers. It applies ledger events in sequence and derives the active sale set. Manager state is then rebuilt from scratch from the active sales; replay never reuses previously calculated budgets or rosters.

Before an event is persisted, the candidate ledger is folded and replayed completely. Persistence is rejected if any active sale would cause:

- an unknown manager or player;
- a player to be actively sold more than once;
- a price below the configured minimum bid;
- a price above the manager's maximum legal bid at that event's effective position in the active sale sequence;
- a negative remaining budget;
- more players than the configured roster size;
- a position count above its configured maximum;
- acquisition of a disabled position;
- an edit or undo reference to a missing or inactive sale;
- a malformed or non-contiguous event sequence.

Historical edits are replayed as corrections to the referenced sale while preserving that sale's original position in the active sale order. All later sales are then validated against the corrected earlier state. An edit that makes any later transaction illegal is rejected atomically.

## Atomic Persistence

Ledger saves target a JSON file beneath `state/`. The writer:

1. serializes the complete validated ledger with stable key ordering;
2. writes it to a temporary sibling file;
3. flushes and closes the temporary file;
4. atomically replaces the destination;
5. removes the temporary file created by the current write attempt if that attempt fails.

The existing ledger remains intact if validation or serialization fails. Tests must inject a replacement failure and prove the prior file remains readable and unchanged.

## Dynamic Market Recalculation

Purchased players and active keepers are removed from the open market. The existing normalization and keeper-inflation method remains the starting point.

After active sales, the recalculation service derives:

```text
remaining deployable capital
  = initial historically deployed capital
  - active keeper salaries
  - active auction sale prices
```

```text
remaining baseline market value
  = normalized open-market value after keepers
  - normalized value of actively purchased players
```

Current market inflation is the existing `market_inflation` ratio applied to those remaining quantities. The denominator must remain positive; an exhausted pool returns a clearly typed terminal result rather than silently inventing values.

## Two-Layer Scarcity

### League-wide scarcity

League-wide scarcity uses the remaining player pool and the outstanding starter and FLEX demand across all managers. It must account for keeper and purchase rosters instead of assuming ten empty, identical teams.

The league optimization assigns active starter slots while respecting each manager's already-owned roster and remaining needs. Its selected remaining pool defines position replacement levels and outstanding demand pressure for QB, RB, WR, TE, DST, and K when enabled. FLEX remains coupled across RB, WR, and TE.

### Manager-specific scarcity

Manager-specific scarcity uses only the target manager's roster and outstanding base starter and FLEX needs. It is derived through the target optimization and opportunity costs, not through a new hand-tuned multiplier. A position with no remaining target starting or FLEX path must not receive artificial scarcity value merely because league-wide demand is high.

Both layers are returned separately so the interface and tests can distinguish market pressure from target roster need.

## Target Roster Optimization

All target keepers and active purchases are locked onto the final roster. Their paid costs are sunk and already removed from the target's remaining budget. They consume roster slots and position capacity.

The optimizer chooses the best active starting assignment from target-owned players plus feasible future acquisitions. An owned player may be assigned to the bench. Bench players contribute zero points to the objective, while every unfilled future bench or roster slot retains its minimum-bid reserve.

The optimization must respect:

- exact active requirements for QB, DST, and K when enabled;
- minimum RB, WR, and TE starter requirements;
- exact total FLEX-eligible active starters;
- roster size and per-position maxima;
- the target's remaining budget and required minimum-bid reserve;
- all target-owned roster commitments.

If the owned roster makes a legal active lineup impossible, the result is a typed infeasible result with a useful message; the service must not return a partial lineup as if it were valid.

## Bid-Up-To Recalculation

Bid-Up-To is recalculated from the rebuilt state after every recorded, edited, or undone sale.

For each candidate considered on the current board:

1. solve the target's best attainable active lineup without acquiring the candidate;
2. require the candidate to occupy one remaining target roster slot, without requiring the candidate to start;
3. minimize the cost of the other required acquisitions while reaching the alternative active-points threshold;
4. assign the remaining legal dollars to the candidate;
5. cap the result at the target manager's current maximum legal bid;
6. return zero when the candidate cannot fit a legal final roster.

Bench points never increase a candidate's ceiling. A bench-only candidate can still have a ceiling above the minimum bid when those dollars are surplus after funding the best attainable active lineup and every remaining legal roster reserve; this is the existing opportunity-cost behavior, not bench-point utility.

## Deterministic Optimization

The current MILP objective can have multiple equally optimal rosters. Phase 1 adds deterministic tie resolution without changing the primary valuation objective:

1. maximize active projected points;
2. among solutions at the same points threshold, minimize completion cost;
3. among exact point-and-cost ties, select lexicographically by stable normalized player identity order.

Solver inputs are sorted by normalized player identity before matrix construction. Point and cost comparisons use explicit tolerances, and monetary Bid-Up-To outputs remain integer dollars. Canonical result serialization sorts managers, roster entries, scarcity keys, and board player identities before comparison.

## Error Handling

Domain validation failures return specific exceptions or typed failure results that identify the event and violated rule. The UI layer will be able to show these messages without parsing generic solver text.

Solver infeasibility, exhausted-market conditions, corrupt JSON, unsupported ledger schema, and interrupted persistence are distinct errors. A failed recalculation never persists the candidate event and never replaces the last valid in-memory or on-disk result.

## Tests and Acceptance

Tests use anonymized synthetic managers and players only.

Required test groups are:

1. Ledger folding: record, edit, undo, invalid references, ordering, and schema validation.
2. Draft-state transitions: keeper initialization, sale application, budgets, slots, position needs, disabled positions, and maximum legal bid.
3. Validation: duplicate player, insufficient funds, roster full, position maximum, minimum bid, and edits that invalidate later sales.
4. Atomic persistence: save/load equality and preservation of the prior file on write or replacement failure.
5. Deterministic optimization: repeated equal-input runs, exact-tie roster selection, owned starters, owned bench players, and remaining-budget feasibility.
6. Dynamic market and scarcity: purchased-player removal, capital/value removal, league-wide outstanding demand, and target-specific needs.
7. Bid-Up-To transitions: values change after relevant opponent and target purchases and return after undo.
8. End-to-end acceptance: generate 30–50 deterministic synthetic sales, persist, reload, compare canonical state and board, undo several sales, edit an old sale, reload after each operation, and prove every replay matches a fresh calculation from the same ledger.

The full existing test suite runs after each meaningful implementation increment. `docs/build-status.md` is updated in the same increment as behavior changes.

## Privacy

Ledger files, live draft state, private manager names, keeper selections, mappings, generated boards, and non-anonymized historical data remain untracked. Production code and tests must not embed real manager identities. Public fixtures use names such as `Manager_01` and synthetic player identities.

Phase 1 must not stage or commit any pre-existing untracked league files in the repository root.

## Completion Gate

Phase 1 is complete only when all of the following are true:

- 30–50 synthetic purchases can be entered and persisted;
- a fresh process can load and replay the entire ledger;
- several purchases can be undone;
- an old purchase can be edited;
- invalid corrections are rejected without damaging the saved ledger;
- equivalent ledger states yield identical canonical budgets, rosters, scarcity outputs, active lineup, and Bid-Up-To values;
- the complete test suite passes;
- `docs/build-status.md` accurately describes the implemented state;
- no private league data is tracked or committed.
