# Methodology

The engine separates three concepts that generic auction sheets often blend together.

1. **Projection value** — expected fantasy production under league scoring.
2. **Market price** — what a player is likely to cost in the current auction environment.
3. **Intrinsic bid ceiling** — the highest price at which the player still belongs in the target manager's best feasible roster.

## Projection aggregation

Current seasonal projections are ingested through the open-source `ffanalytics` R package. The default MVP uses the simple cross-source average and retains source disagreement for later uncertainty modeling. Small CBXII per-game yardage bonuses are intentionally excluded.

## Keeper market state

Confirmed or likely keepers are removed from the auction pool. Their keeper salaries reduce league purchasing power. Historical league data is used to estimate the fraction of theoretical auction capital that is actually deployed; the last five drafts are the default calibration window.

## Replacement level

Replacement ranks are not hard-coded. A league-wide MILP selects the highest-projected legal starting pool for all teams simultaneously. The lowest selected player at each position defines that position's current replacement level. This naturally lets the two FLEX slots determine how many RBs, WRs, and TEs are starter-caliber.

## Starter-core optimization

The draft-night MVP optimizes the starting lineup while reserving the minimum legal salary for bench slots. This avoids inventing an arbitrary bench-points weight. A future simulation layer will value bench players by injury/replacement utility.

## Bid-Up-To

For a candidate player, the engine solves the best legal roster without that player to establish the opportunity-cost points threshold. It then forces the candidate into a legal roster and minimizes the known cost of the other starters while requiring at least that threshold. The remaining starter budget is the player's intrinsic Bid-Up-To ceiling. This requires roughly two MILP solves per candidate rather than repeated trial-price solves.

## Defense

D/ST is treated as a normal optimized roster position, not automatically constrained to $1. If the projection advantage of an elite defense supports a $3–$5 bid without reducing total optimized roster output, the model is free to recommend it.

## Projection limitations

The 2026 MVP intentionally omits the small offensive per-game yardage bonuses. D/ST is scored from projected sacks, turnovers, touchdowns, blocks, safeties and points allowed. ESPN's separate yards-allowed scoring bands are not yet modeled because the upstream consensus sources do not expose those bands consistently across sources; this is tracked as a model limitation rather than silently approximated.
