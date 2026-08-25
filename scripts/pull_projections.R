#!/usr/bin/env Rscript

# Current-season projection ingestion. This deliberately isolates scraping from
# the Python optimization engine so upstream site changes do not affect model code.

if (!requireNamespace("remotes", quietly = TRUE)) install.packages("remotes", repos = "https://cloud.r-project.org")
if (!requireNamespace("ffanalytics", quietly = TRUE)) remotes::install_github("FantasyFootballAnalytics/ffanalytics")
if (!requireNamespace("readr", quietly = TRUE)) install.packages("readr", repos = "https://cloud.r-project.org")
if (!requireNamespace("dplyr", quietly = TRUE)) install.packages("dplyr", repos = "https://cloud.r-project.org")

library(ffanalytics)
library(dplyr)

sources <- c("CBS", "ESPN", "FantasyPros", "FantasySharks", "FFToday", "NumberFire", "Yahoo", "FantasyFootballNerd", "NFL", "RTSports", "Walterfootball")
positions <- c("QB", "RB", "WR", "TE", "DST", "K")

cbxii_scoring <- custom_scoring(
  pass_yds = 0.04,
  pass_tds = 4,
  pass_int = -2,
  rush_yds = 0.1,
  rush_tds = 6,
  rec = 0.5,
  rec_yds = 0.1,
  rec_tds = 6,
  fumbles_lost = -2,
  two_pts = 2,
  return_tds = 6,
  dst_fum_rec = 2,
  dst_int = 2,
  dst_safety = 2,
  dst_sacks = 1,
  dst_td = 6,
  dst_blk = 2
)
cbxii_scoring$pts_bracket <- list(
  list(threshold = 0, points = 8),
  list(threshold = 6, points = 5),
  list(threshold = 13, points = 3),
  list(threshold = 17, points = 1),
  list(threshold = 27, points = 0),
  list(threshold = 34, points = -1),
  list(threshold = 45, points = -3),
  list(threshold = 99, points = -5)
)

message("Scraping current-season projections. Individual source failures will be reported by ffanalytics.")
raw <- scrape_data(src = sources, pos = positions, season = NULL, week = 0)

source_summary <- dplyr::bind_rows(raw, .id = "position") %>%
  dplyr::count(position, data_src, name = "rows") %>%
  dplyr::arrange(position, data_src)
working_sources <- unique(source_summary$data_src)
if (length(working_sources) < 3) {
  stop("Fewer than three projection sources succeeded; refusing to build a consensus projection.")
}
message("Working projection sources: ", paste(sort(working_sources), collapse = ", "))

proj <- projections_table(
  raw,
  scoring_rules = cbxii_scoring,
  avg_type = c("average", "robust", "weighted"),
  return_raw_stats = FALSE
)

proj <- tryCatch(add_player_info(proj), error = function(e) { message("add_player_info failed: ", e$message); proj })
if (all(c("first_name", "last_name") %in% names(proj))) {
  proj <- proj %>% mutate(player = trimws(paste(first_name, last_name)))
}
proj <- tryCatch(add_ecr(proj), error = function(e) { message("add_ecr failed: ", e$message); proj })
proj <- tryCatch(add_aav(proj), error = function(e) { message("add_aav failed: ", e$message); proj })
proj <- tryCatch(add_uncertainty(proj), error = function(e) { message("add_uncertainty failed: ", e$message); proj })

out_dir <- file.path("data", "processed")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
readr::write_csv(proj, file.path(out_dir, "projections_2026.csv"))
readr::write_csv(source_summary, file.path(out_dir, "projection_source_summary_2026.csv"))
message("Wrote data/processed/projections_2026.csv")
message("Wrote data/processed/projection_source_summary_2026.csv")
