# Phase 2 Configuration Design

## Goal

Make keeper decisions reloadable from private data and make DST/K legal roster
requirements independent from the projection and valuation engine.

## Existing issues

The Phase 1 artifact context stores `initial_remaining_capital` and
`initial_remaining_baseline_value` after likely/confirmed keepers have already
been applied. Reloading a changed private keeper CSV updates roster ownership,
but it cannot reconstruct the corresponding market baseline. An opt-out, player
change, or salary correction can therefore leave league purchasing power,
inflation, and Bid-Up-To values stale.

The Phase 1 optimizer also uses one set of starter requirements for both legal
roster accounting and active-lineup scoring. With `DST: 1` or `K: 1`, the MILP
requires projected DST/K rows. That conflicts with the draft-night requirement:
DST and K must consume roster slots and salary-cap reserve without contributing
to projections, scarcity, recommendations, or Bid-Up-To.

## Keeper source of truth

`data/private/provisional_keepers_2026.csv` remains the only editable keeper
source. Supported statuses are `likely`, `confirmed`, `opt_out`, and `none`.
Status comparison is case-insensitive after trimming whitespace.

- `likely` and `confirmed` are active keeper decisions.
- `opt_out` and `none` are inactive.
- A likely-to-confirmed transition intentionally leaves calculations unchanged;
  it changes the auditable status, not the active keeper set.
- Any change to active player, manager, cost, or status is applied on the next
  application load without rebuilding code.
- Unknown statuses fail before a draft session is opened.

Generated context schema version 2 stores the pre-keeper deployable league
capital and pre-keeper normalized pool value. `load_draft_inputs` subtracts the
currently active keeper salaries and normalized values every time it reads the
private CSV, producing the same `MarketBaseline` contract used by Phase 1 live
recalculation. Legacy context fails with an instruction to rebuild artifacts;
it is never interpreted as current keeper state.

## Required versus modeled positions

The public league YAML gains:

```yaml
model:
  modeled_positions: [QB, RB, WR, TE]
```

The existing `starters`, `position_max`, `roster_size`, `salary_cap`, and
`min_bid` values remain the source of legal roster rules. `starters.K: 0`
disables K acquisitions; `starters.K: 1` reserves the required K roster slot.
DST follows the same legal accounting behavior.

Replay and manager state continue to use the full rules. Consequently, every
required DST/K slot is included in:

- remaining roster slots;
- starter needs and roster completeness;
- the minimum-bid reserve behind maximum legal bid;
- budget and position-capacity changes after a DST/K purchase.

Optimization receives a derived rule set whose DST/K starter counts are zero.
The explicit `roster_slots_remaining` and full remaining budget still force the
optimizer to reserve `min_bid` for every unfilled roster slot. Therefore the
active objective remains offensive starter/FLEX points while legal cap reserve
remains exact.

League-wide scarcity and manager-specific modeled scarcity use only configured
modeled positions. The recommendation board and Bid-Up-To candidates also use
only those positions. This does not change the existing offensive projection,
replacement, market-inflation, or opportunity-cost formulas.

## Projection-free DST/K purchases

If an unmodeled player exists in the generated pool, the normal sale workflow
can record the purchase. The session also exposes a projection-free sale method
for DST/K names missing from upstream projections. It creates a deterministic
position-prefixed player key, replays through the same ledger validation, and
updates budget, slots, needs, and maximum legal bid.

Projection-free DST/K purchases have no normalized player value to remove from
the market baseline. Their actual winning price still reduces league remaining
capital, matching the Phase 1 rule that every purchase reduces purchasing
power. They never enter scarcity or optimization. The Streamlit app provides a
small separate entry form for this case so the primary player search remains an
offensive recommendation workflow.

## Determinism and persistence

No keeper edit is written by the application; keeper changes stay auditable in
the private CSV. The sale ledger remains append-only and atomic. A reload always
reconstructs keeper inputs first and then replays the complete sale ledger.
Manual DST/K sales use stable keys derived only from position and normalized
name, so reload, edit, undo, and canonical snapshots remain deterministic.

## Validation

Tests must prove:

- likely and confirmed rows are active while opt-out and none rows are inactive;
- changing likely to confirmed reloads identically;
- changing an active keeper to opt-out recomputes keeper ownership, market
  capital, market baseline, availability, inflation, and Bid-Up-To from the same
  generated artifacts;
- unsupported status and legacy context fail explicitly;
- K set to zero or one creates a valid live optimization with no K projections;
- DST/K remain in legal needs, slots, budget reserve, and maximum bid while
  being absent from scarcity, active points, recommendations, and Bid-Up-To;
- projection-free DST/K record, edit, undo, persistence, and replay are stable;
- all Phase 1 replay, atomicity, optimizer determinism, and privacy tests remain
  green.

## Out of scope

- Editing keeper decisions inside Streamlit.
- Adding DST or kicker projection fallbacks.
- Assigning placeholder DST/K fantasy points.
- Changing offensive projection aggregation, replacement-level methodology, or
  opportunity-cost Bid-Up-To.
- Phase 3 interaction-speed redesign.

