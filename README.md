# Chad's Basement Analytics

A league-specific salary-cap fantasy football decision engine built for a 10-team keeper auction league. It combines current multi-source projections, custom scoring, keeper-adjusted market state, mixed-integer roster optimization, historical auction behavior, and dynamic Bid-Up-To calculations.

## Why this exists

Generic AAV answers what the public tends to pay. An auction manager needs a different answer: **what is the maximum price at which this player still belongs in my best feasible roster, given the players, money, and positional scarcity that remain?**

The engine is inspired by the optimization concepts in Fantasy Football Analytics while replacing the 2013-era implementation with a smaller modern pipeline designed for live draft-state recalculation.

## Current MVP

- Parses ten seasons of raw ESPN salary-cap draft recaps into a normalized transaction table.
- Separates manager identity from changing fantasy-team names and preserves nomination order.
- Pulls current projections through the actively maintained `FantasyFootballAnalytics/ffanalytics` R package and records which public source scrapers succeeded.
- Scores projections for CBXII half-PPR settings while intentionally ignoring minor per-game yardage bonuses.
- Supports keeper removal and keeper salaries.
- Uses `scipy.optimize.milp` for binary roster optimization with two FLEX slots.
- Derives replacement levels from a league-wide optimization instead of hard-coded positional ranks.
- Reserves minimum bench dollars instead of treating bench points as weekly starter points.
- Calculates player-specific Bid-Up-To ceilings from opportunity cost with roughly two constrained optimization problems per candidate.
- Includes a Streamlit draft board and purchase log scaffold.

## Historical data

The private league dataset contains 1,600 auction transactions across ten drafts from 2016–2025. Raw manager/team identities and source files stay outside Git through `.gitignore`. The repository includes the parser, anonymization tooling, and an anonymized keeper example so the data model is visible without publishing league-member identities.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .
```

The historical parser expects private source files under `data/private/raw/` and is not required to run the public optimizer tests.

Projection ingestion requires R because `ffanalytics` is an R package. The included GitHub Action installs the public package directly from its repository and produces a downloadable projection artifact.

```bash
Rscript scripts/pull_projections.R
python scripts/build_draft_board.py
streamlit run app/streamlit_app.py
```

## Modeling notes

### Keeper-adjusted market

Confirmed or likely keepers are removed from the open player pool and their salaries are removed from league purchasing power. Historical Chad's Basement spending is used to estimate how much of theoretical auction capital is actually deployed.

### Starter-core optimization

The MVP maximizes projected starter points under salary, positional, FLEX, and minimum bench-reserve constraints. Bench upside and injury replacement utility are intentionally deferred rather than assigned arbitrary weights.

### Bid-Up-To

For a candidate player, the engine first solves the best legal roster without that player. It then forces the candidate into the roster and minimizes the cost of the other starters while requiring at least the alternative roster's projected points. The dollars left in the starter budget are the candidate's intrinsic bid ceiling.

### Defense

D/ST remains a normal optimized position. The model does not force defenses to $1–$2, so an elite unit can justify a higher bid when its projected marginal points are a better use of auction capital.

## Next iterations

- Recompute values after every live sale using all managers' remaining budgets and roster needs.
- Estimate expected clearing price from ten years of league-specific behavior.
- Add manager-level spending priors by position, early-auction aggression, and stars-and-scrubs tendency.
- Add scenario simulation and uncertainty-aware objectives.
- Add nomination strategy and price-anomaly alerts.
- Add bench/injury utility based on replacement probability rather than a fixed bench weight.

## Data privacy

`config/cbxii.yaml` contains scoring and roster rules only and is safe to publish. Raw manager mappings, live keeper selections, normalized non-anonymized history, generated draft boards, and draft-night state stay under gitignored `data/private/`, `data/processed/`, and `state/` paths.
