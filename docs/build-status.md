# Build status — Draft-night MVP

## Complete

- [x] Normalize 2016–2025 ESPN salary-cap draft history
- [x] Validate 1,600 transactions and 160 nominations per season
- [x] Resolve historical team names to persistent manager identifiers
- [x] Preserve the mid-history manager transition in the anonymized slot model
- [x] Encode 2026 league configuration
- [x] Encode provisional 2026 keeper state locally
- [x] Build manager behavior features
- [x] Add recent historical capital-deployment calibration
- [x] Build FLEX-aware league replacement-level optimizer
- [x] Build target-roster salary-cap MILP
- [x] Build opportunity-cost Bid-Up-To calculation
- [x] Normalize ESPN/FFA player identity suffix differences for keeper matching
- [x] Normalize public AAV to the CBXII auction economy before applying keeper inflation
- [x] Add persisted live draft-board record/edit/undo workflow
- [x] Add current-season `ffanalytics` ingestion script
- [x] Add GitHub Actions projection-refresh workflow
- [x] Validate first live 2026 projection artifact
- [x] Confirm working projection sources: CBS, ESPN, FFToday, FantasyPros
- [x] Generate first real kickerless CBXII preview board from 2026 projections
- [x] Build a versioned append-only sale ledger with stable JSON and atomic replacement
- [x] Replay keepers and active sales into every manager's budget, roster, needs, capacity, and maximum legal bid
- [x] Recalculate available players, remaining league purchasing power, and market inflation after each transaction
- [x] Separate league-wide remaining-pool scarcity from target-manager starter/FLEX needs
- [x] Lock target-owned players into roster completion while maximizing active starter points only
- [x] Recalculate opportunity-cost Bid-Up-To from the target's remaining budget and roster on every replay
- [x] Reject invalid record/edit/undo candidates before replacing the persisted ledger or in-memory snapshot
- [x] Emit the full normalized pool and market context required to replay the live draft
- [x] Run the complete public test suite in GitHub CI
- [x] Store pre-keeper market context and recalculate active keeper deductions on every reload
- [x] Validate configurable keeper statuses: likely, confirmed, opt-out, and none
- [x] Separate full legal roster accounting from projection-modeled positions
- [x] Support `K: 0` and `K: 1` without requiring kicker projections
- [x] Keep DST/K slots and minimum dollars in roster state and maximum legal bid
- [x] Exclude DST/K from scarcity, active points, recommendations, and Bid-Up-To
- [x] Record, persist, edit, replay, and undo projection-free DST/K purchases

## Phase 1 acceptance verified

- [x] Enter 40 synthetic purchases across 10 anonymized managers
- [x] Reload the persisted ledger and reproduce identical budgets, rosters, scarcity, lineup, and Bid-Up-To values
- [x] Undo three purchases, reload, and reproduce the same canonical snapshot
- [x] Edit an old purchase while preserving its original order, reload, and reproduce the same canonical snapshot
- [x] Repeat the end-to-end acceptance test three consecutive times without solver-order drift
- [x] Preserve the last valid file and in-memory snapshot after invalid historical edits or persistence failure

## External state still required

- [ ] Change likely keepers to confirmed or opt-out in the private keeper CSV after keeper lock

## Current preview calibration

- Last-five-draft capital deployment: 99.26%
- Likely keeper salary removed: $166
- Normalized public market value removed by likely keepers: about $208
- Keeper-driven remaining-market inflation: about 1.024x
- Current public configuration requires one DST and one K roster slot; both are unmodeled and reserve salary only

## Phase 2 acceptance verified

- [x] Reload likely and confirmed keeper states from the private CSV without code changes
- [x] Recalculate keeper ownership, purchasing power, normalized baseline, inflation, and Bid-Up-To after an opt-out
- [x] Reject unknown keeper statuses and stale pre-Phase-2 context explicitly
- [x] Solve valid live optimization problems for both `K: 0` and `K: 1` with no K projections
- [x] Preserve DST/K needs, roster slots, budgets, position capacity, and maximum legal bid outside the scoring model
- [x] Replay projection-free K purchases identically through record, reload, edit, undo, and reload
- [x] Preserve all Phase 1 deterministic ledger and atomic persistence acceptance tests

## Next model work

- [ ] Phase 3: tune the draft-night interaction for one purchase in a few seconds
- [ ] Add expected clearing price using league-specific manager behavior
- [ ] Add scenario simulation / uncertainty objective

