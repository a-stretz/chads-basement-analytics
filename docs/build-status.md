# Build status — Draft-night MVP

## Complete

- [x] Normalize 2016–2025 ESPN salary-cap draft history
- [x] Validate 1,600 transactions and 160 nominations per season
- [x] Resolve historical team names to persistent manager identities
- [x] Preserve Hackett → Eanes manager transition in team slot 9
- [x] Encode 2026 league configuration
- [x] Encode provisional 2026 keeper state locally
- [x] Build manager behavior features
- [x] Add recent historical capital-deployment calibration
- [x] Build FLEX-aware league replacement-level optimizer
- [x] Build target-roster salary-cap MILP
- [x] Build opportunity-cost Bid-Up-To calculation
- [x] Normalize ESPN/FFA player identity suffix differences for keeper matching
- [x] Normalize public AAV to the CBXII auction economy before applying keeper inflation
- [x] Add live draft-board UI skeleton
- [x] Add current-season `ffanalytics` ingestion script
- [x] Add GitHub Actions projection-refresh workflow
- [x] Validate first live 2026 projection artifact
- [x] Confirm working projection sources: CBS, ESPN, FFToday, FantasyPros
- [x] Generate first real kickerless CBXII preview board from 2026 projections
- [x] Unit-test optimizer, replacement model, and Bid-Up-To threshold in passing GitHub CI

## External state still required

- [ ] Replace likely keepers with confirmed keepers after keeper lock
- [ ] Set `K: 0` if the league removes kickers before draft night
- [ ] If K remains, add a kicker projection fallback because the current `ffanalytics` aggregate drops K despite successful raw K scrapes

## Current preview calibration

- Last-five-draft capital deployment: 99.26%
- Likely keeper salary removed: $166
- Normalized public market value removed by likely keepers: about $208
- Keeper-driven remaining-market inflation: about 1.024x
- Current preview uses K=0 pending league decision

## Next model work

- [ ] Make live sale entry trigger full recalculation, not only budget bookkeeping
- [ ] Add opponent roster need and max-bid calculation
- [ ] Add expected clearing price using league-specific manager behavior
- [ ] Add scenario simulation / uncertainty objective
