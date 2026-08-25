# Chad's Basement Analytics

A league-specific salary-cap fantasy football decision engine built for a 10-team keeper auction league. It combines current multi-source projections, custom scoring, keeper-adjusted market state, mixed-integer roster optimization, historical auction behavior, and dynamic Bid-Up-To calculations.

## Why this exists

Generic AAV answers what the public tends to pay. An auction manager needs a different answer: **what is the maximum price at which this player still belongs in my best feasible roster, given the players, money, and positional scarcity that remain?**

The engine is inspired by the optimization concepts in Fantasy Football Analytics while replacing the 2013-era implementation with a smaller modern pipeline designed for live draft-state recalculation.

## Current MVP

- Parses ten seasons of raw ESPN salary-cap draft recaps into a normalized transaction table.
- Separates manager identity from changing fantasy-team names.
- Preserves nomination order for behavioral analysis.
- Pulls current projections through the actively maintained `FantasyFootballAnalytics/ffanalytics` R package and records which public source scrapers succeeded.
- Scores projections for half-PPR league settings while intentionally ignoring minor per-game yardage bonuses.
- Supports keeper removal and keeper salaries.
- Uses `scipy.optimize.milp` for binary roster optimization with two FLEX slots.
- Reserves minimum bench dollars instead of treating bench points as weekly starter points.
- Calculates player-specific Bid-Up-To ceilings from opportunity cost with roughly two constrained optimization problems per candidate.
- Includes a Streamlit draft board and purchase log.

## Historical data

The private league dataset contains 1,600 auction transactions across ten drafts from 2016–2025. Raw manager/team identities and private draft inputs are excluded from Git through `.gitignore`. A fully anonymized 1,600-row transaction dataset is included so the historical modeling pipeline remains reproducible.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .
python scripts/parse_history.py
```

Projection ingestion requires R because `ffanalytics` is an R package:

```bash
Rscript scripts/pull_projections.R
python scripts/build_draft_board.py
streamlit run app/streamlit_app.py
```

If R is not installed locally, run the **Refresh 2026 projections** GitHub Action and download its CSV artifact. The projection workflow uses only public sources exposed by the open-source `ffanalytics` package; individual source failures are tolerated by that package.

## Modeling notes

### Keeper-adjusted market

Confirmed keepers are removed from the player pool and their salaries are removed from league purchasing power. Public AAV is then normalized against remaining league dollars before optimization.

### Starter-core optimization

The MVP maximizes projected starter points under salary, positional, FLEX, and minimum bench-reserve constraints. Bench upside and injury replacement utility are intentionally deferred rather than given arbitrary weights.

### Bid-Up-To

For a candidate player, the engine first solves the best legal roster without that player. It then forces the candidate into the roster and minimizes the cost of the other starters while requiring at least the alternative roster's projected points. The dollars left in the starter budget are the candidate's intrinsic bid ceiling. This computes the threshold directly rather than stepping through trial prices.

## Next iterations

- Recompute values after every live sale using all managers' remaining budgets and roster needs.
- Estimate expected clearing price from ten years of league-specific behavior.
- Add manager-level spending priors by position, early-auction aggression, and stars-and-scrubs tendency.
- Add scenario simulation and uncertainty-aware objectives.
- Add nomination strategy and price-anomaly alerts.
- Add bench/injury utility based on replacement probability rather than a fixed bench weight.

## Data privacy

`config/cbxii.yaml` contains scoring and roster rules only and is safe to publish. Raw manager mappings, live keeper selections, normalized non-anonymized history, generated draft boards, and draft-night state stay under gitignored `data/private/`, `data/processed/`, and `state/` paths.
