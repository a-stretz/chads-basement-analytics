# Methodology

The engine separates three concepts that generic auction sheets often blend together.

1. **Projection value** — expected fantasy production under league scoring.
2. **Market price** — what a player is likely to cost in the current auction environment.
3. **Intrinsic bid ceiling** — the highest price at which the player still belongs in the target manager's best feasible roster.

## Projection aggregation

Current seasonal projections are ingested through the open-source `ffanalytics` R package. The default MVP uses the simple cross-source average and retains source disagreement for later uncertainty modeling. Small CBXII per-game yardage bonuses are intentionally excluded.

## Keeper market state

Confirmed or likely keepers are removed from the auction pool. Their keeper salaries reduce league purchasing power. Historical league data is used to estimate the fraction of theoretical auction capital that is actually deployed; the last five drafts are the default calibration window. The generated context stores this market before keeper deductions, and the loader derives the current keeper-adjusted baseline from the private CSV on every reload. A likely-to-confirmed transition intentionally leaves value unchanged because both statuses are active.

## Replacement level

Replacement ranks are not hard-coded. A league-wide MILP selects the highest-projected modeled starting pool for all teams simultaneously. The lowest selected player at each modeled position defines that position's current replacement level. This naturally lets the two FLEX slots determine how many RBs, WRs, and TEs are starter-caliber. DST and K are legal roster requirements but do not enter this projected pool.

## Starter-core optimization

The draft-night MVP optimizes the QB/RB/WR/TE starting lineup while reserving the minimum legal salary for every other open roster slot, including bench, DST, and K. This avoids inventing an arbitrary bench-points or special-teams weight. A future simulation layer will value bench players by injury/replacement utility.

## Bid-Up-To

For a candidate player, the engine solves the best legal roster without that player to establish the opportunity-cost points threshold. It then forces the candidate into a legal roster and minimizes the known cost of the other starters while requiring at least that threshold. The remaining starter budget is the player's intrinsic Bid-Up-To ceiling. This requires roughly two MILP solves per candidate rather than repeated trial-price solves.

## Legal versus modeled positions

`starters` and `position_max` define legal roster accounting. The separate
`model.modeled_positions` list defines which positions enter projection-based
scarcity, lineup optimization, recommendations, and Bid-Up-To. CBXII models
QB/RB/WR/TE only. A DST/K purchase still reduces budget, consumes a roster slot,
fills the corresponding need, and can reduce maximum legal bid when it costs
more than the reserved minimum.

## Projection limitations

The 2026 MVP intentionally omits the small offensive per-game yardage bonuses.
DST and K projections are intentionally excluded instead of approximated from
incomplete upstream data.

