from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

SEASON_SPLIT = re.compile(r"Draft Recap[^\n]*Season:\s*\n(20\d{2})\s*\n")
PLAYER_LINE = re.compile(r"^(.*?)\s+([^,\s]+),\s*(QB|RB|WR|TE|K|D/ST)$")


def load_manager_mapping(path: str | Path) -> dict[int, dict[str, dict[str, Any]]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    mapping: dict[int, dict[str, dict[str, Any]]] = {}
    for manager in raw["managers"]:
        for team in manager["team_names"]:
            for season in team["years"]:
                mapping.setdefault(int(season), {})[team["name"]] = {
                    "manager": manager["manager"],
                    "team_slot": int(manager["team_slot"]),
                }
    for historical in raw.get("deactivated_manager_history", []):
        for season, team_name in historical["team_names_by_year"].items():
            mapping.setdefault(int(season), {})[team_name] = {
                "manager": historical["manager"],
                "team_slot": int(historical["team_slot"]),
            }
    return mapping


def parse_draft_history(draft_path: str | Path, mapping_path: str | Path) -> pd.DataFrame:
    mapping = load_manager_mapping(mapping_path)
    text = Path(draft_path).read_text(encoding="utf-8")
    parts = SEASON_SPLIT.split(text)
    rows: list[dict[str, Any]] = []

    for i in range(1, len(parts), 2):
        season = int(parts[i])
        content = parts[i + 1]
        teams = mapping[season]
        locations = []
        for team_name, info in teams.items():
            match = re.search(r"(?m)^" + re.escape(team_name) + r"\s*$", content)
            if match is None:
                raise ValueError(f"Missing team heading for {season}: {team_name!r}")
            locations.append((match.start(), match.end(), team_name, info))
        locations.sort()
        if len(locations) != 10:
            raise ValueError(f"Expected 10 teams in {season}, found {len(locations)}")

        for idx, (_, end, team_name, info) in enumerate(locations):
            section_end = locations[idx + 1][0] if idx + 1 < len(locations) else len(content)
            lines = [line.strip() for line in content[end:section_end].splitlines() if line.strip()]
            if "OFFER AMOUNT" in lines:
                lines = lines[lines.index("OFFER AMOUNT") + 1 :]

            cursor = 0
            team_count = 0
            while cursor + 2 < len(lines):
                if re.fullmatch(r"\d+", lines[cursor]) and re.fullmatch(r"\$\d+", lines[cursor + 2]):
                    player_match = PLAYER_LINE.match(lines[cursor + 1])
                    if player_match is None:
                        raise ValueError(f"Could not parse player line: {season} {team_name} {lines[cursor + 1]!r}")
                    player, nfl_team, position = player_match.groups()
                    rows.append({
                        "season": season,
                        "team_slot": info["team_slot"],
                        "manager": info["manager"],
                        "fantasy_team": team_name,
                        "nomination_order": int(lines[cursor]),
                        "player": player,
                        "nfl_team": nfl_team,
                        "position": position,
                        "cost": int(lines[cursor + 2][1:]),
                    })
                    cursor += 3
                    team_count += 1
                else:
                    cursor += 1
            if team_count != 16:
                raise ValueError(f"Expected 16 players for {season} {team_name}, found {team_count}")

    df = pd.DataFrame(rows).sort_values(["season", "nomination_order"]).reset_index(drop=True)
    counts = df.groupby("season").size()
    if len(df) != 1600 or not counts.eq(160).all():
        raise ValueError(f"History validation failed. rows={len(df)}, counts={counts.to_dict()}")
    if df.duplicated(["season", "nomination_order"]).any():
        raise ValueError("Duplicate nomination orders detected within a season")
    return df


def manager_profiles(history: pd.DataFrame) -> pd.DataFrame:
    df = history.copy()
    totals = df.groupby(["season", "manager"], as_index=False)["cost"].sum().rename(columns={"cost": "season_spend"})
    pos = df.pivot_table(index=["season", "manager"], columns="position", values="cost", aggfunc="sum", fill_value=0).reset_index()
    top3 = (
        df.sort_values(["season", "manager", "cost"], ascending=[True, True, False])
        .groupby(["season", "manager"]).head(3)
        .groupby(["season", "manager"], as_index=False)["cost"].sum()
        .rename(columns={"cost": "top3_spend"})
    )
    early = (
        df[df["nomination_order"] <= 40]
        .groupby(["season", "manager"], as_index=False)["cost"].sum()
        .rename(columns={"cost": "first40_spend"})
    )
    season = totals.merge(pos, on=["season", "manager"], how="left").merge(top3, on=["season", "manager"]).merge(early, on=["season", "manager"], how="left")
    season["first40_spend"] = season["first40_spend"].fillna(0)
    season["stars_scrubs_share"] = season["top3_spend"] / season["season_spend"]
    season["early_spend_share"] = season["first40_spend"] / season["season_spend"]
    for p in ["QB", "RB", "WR", "TE", "D/ST", "K"]:
        if p not in season:
            season[p] = 0
        season[f"{p.lower().replace('/', '')}_spend_share"] = season[p] / season["season_spend"]

    metric_cols = [
        "season_spend", "stars_scrubs_share", "early_spend_share",
        "qb_spend_share", "rb_spend_share", "wr_spend_share", "te_spend_share",
        "dst_spend_share", "k_spend_share",
    ]
    profile = season.groupby("manager")[metric_cols].agg(["mean", "std", "count"])
    profile.columns = [f"{a}_{b}" for a, b in profile.columns]
    return profile.reset_index()
