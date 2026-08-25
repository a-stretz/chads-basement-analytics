from __future__ import annotations

from pathlib import Path
import subprocess


def _tracked_files() -> list[str]:
    workspace = Path.cwd().as_posix()
    return subprocess.run(
        ["git", "-c", f"safe.directory={workspace}", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def test_public_application_has_no_embedded_manager_roster():
    source = (
        Path("app/streamlit_app.py").read_text(encoding="utf-8")
        + Path("scripts/build_draft_board.py").read_text(encoding="utf-8")
    )
    assert "Stretz" not in source
    assert "Tornabene" not in source


def test_private_inputs_generated_outputs_and_live_state_are_not_tracked():
    tracked = _tracked_files()
    private_prefixes = ("data/private/", "data/processed/", "state/")
    assert not any(path.startswith(private_prefixes) for path in tracked)
    assert not any(path.endswith("manager_aliases.yaml") for path in tracked)
