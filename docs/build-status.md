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
- [x] Add live draft-board UI skeleton
- [x] Add current-season `ffanalytics` ingestion script
- [x] Add GitHub Actions projection-refresh workflow
- [x] Unit-test optimizer, replacement model, history parser, and Bid-Up-To threshold

## External state still required

- [ ] Validate the first live 2026 projection artifact and working-source summary
- [ ] Replace likely keepers with confirmed keepers after keeper lock
- [ ] Set `K: 0` if the league removes kickers before draft night

## Next model work

- [ ] Generate the initial real CBXII draft board and Bid-Up-To values from live 2026 projections
- [ ] Make live sale entry trigger full recalculation, not only budget bookkeeping
- [ ] Add opponent roster need and max-bid calculation
- [ ] Add expected clearing price using league-specific manager behavior
- [ ] Add scenario simulation / uncertainty objective
