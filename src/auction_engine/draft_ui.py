from __future__ import annotations

from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd


_DRAFT_RESOURCES_KEY = "_draft_resources"


def get_or_load_draft_resources(
    state: Any,
    input_version: str,
    loader: Callable[[], tuple[Any, Any, Any]],
) -> tuple[Any, Any, Any]:
    """Reuse the calculated session until a draft input actually changes."""
    cached = state.get(_DRAFT_RESOURCES_KEY)
    if cached is None or cached[0] != input_version:
        resources = loader()
        state[_DRAFT_RESOURCES_KEY] = (input_version, resources)
        return resources
    return cached[1]


def draft_input_version(paths: Sequence[str | Path]) -> str:
    """Fingerprint inputs whose edits require a fresh replay calculation."""
    digest = sha256()
    for value in paths:
        path = Path(value)
        digest.update(str(path.resolve()).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_nomination_pool(
    available: pd.DataFrame,
    modeled_positions: Sequence[str],
) -> pd.DataFrame:
    """Return modeled available players in permanent auction-market order."""
    ranked = available.loc[
        available.position.isin(tuple(modeled_positions))
    ].copy()
    ranked["normalized_aav"] = pd.to_numeric(
        ranked["normalized_aav"],
        errors="coerce",
    )
    return ranked.sort_values(
        ["normalized_aav", "player", "player_key"],
        ascending=[False, True, True],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def nomination_labels(ranked: pd.DataFrame) -> dict[str, str]:
    """Build searchable labels with the market anchor visible."""
    return {
        str(row.player_key): (
            f"{row.player} — {row.position} — "
            f"AAV ${int(round(float(row.normalized_aav)))}"
        )
        for row in ranked.itertuples(index=False)
    }
