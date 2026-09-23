"""Local team storage for the Tethys PySide6 application."""

# * EDITAVEL: altere o formato dos registros junto com app/teams_tab.py.
# ! Preserve compatibilidade ao mudar as chaves dos JSON salvos pelo usuario.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.wuwa_calculator.utils.paths import get_legacy_data_path, get_user_data_path

TEAMS_FILE = get_user_data_path("teams.json")
DEFAULT_TEAMS: list[dict[str, Any]] = [
    {"name": "Fusion quickswap", "status": "Not started", "characters": ["Augusta", "Brant", "Shorekeeper"]},
    {"name": "Glacio control", "status": "Not started", "characters": []},
    {"name": "Aero burst", "status": "Not started", "characters": []},
]


def _migrate_legacy_teams(path: Path) -> None:
    legacy_path = get_legacy_data_path("teams.json")
    if path != TEAMS_FILE or not legacy_path.exists():
        return
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        if isinstance(current, list) and current:
            return
        if isinstance(legacy, list) and legacy:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return


def load_teams(path: Path = TEAMS_FILE) -> list[dict[str, Any]]:
    _migrate_legacy_teams(path)
    if not path.exists():
        return [dict(team) for team in DEFAULT_TEAMS]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [dict(team) for team in DEFAULT_TEAMS]
    if not isinstance(value, list):
        return [dict(team) for team in DEFAULT_TEAMS]
    return [team for team in value if isinstance(team, dict) and str(team.get("name", "")).strip()]


def save_teams(teams: list[dict[str, Any]], path: Path = TEAMS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(teams, ensure_ascii=False, indent=2), encoding="utf-8")
