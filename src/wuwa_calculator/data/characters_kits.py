"""Character kits database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.wuwa_calculator.data.characters_ids import KNOWN_CHARACTER_IDS

_DATA_ROOT = Path(__file__).resolve().parent
_SKILLS_ROOT = _DATA_ROOT / "characters" / "skills"
_SKILL_FILES = (
    "basic_attack.json",
    "resonance_skill.json",
    "forte_circuit.json",
    "resonance_liberation.json",
    "intro_skill.json",
    "outro_skill.json",
)


def _normalize_character_id(value: str) -> str:
    return str(value).strip().replace("_", " ").lower()


def _safe_json_load(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_character_kits_from_disk() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not _SKILLS_ROOT.exists():
        return result

    known_aliases = {
        _normalize_character_id(character_id): character_id
        for character_id in KNOWN_CHARACTER_IDS
    }

    for skill_dir in sorted(_SKILLS_ROOT.iterdir(), key=lambda path: path.name.lower()):
        if not skill_dir.is_dir():
            continue

        normalized_dir = _normalize_character_id(skill_dir.name)
        canonical_id = known_aliases.get(normalized_dir, normalized_dir)
        if canonical_id not in KNOWN_CHARACTER_IDS and normalized_dir not in known_aliases:
            continue

        skills: list[dict[str, str]] = []
        for file_name in _SKILL_FILES:
            payload = _safe_json_load(skill_dir / file_name)
            if not payload:
                continue

            name = str(payload.get("name") or "").strip()
            description = str(payload.get("description") or "").strip()
            if name or description:
                skills.append({"name": name, "description": description})

        if not skills:
            continue

        result[canonical_id] = {
            "kit_name": canonical_id,
            "weapon_name": "",
            "weapon_passive": "",
            "skills": skills,
            "team_buffs": [],
            "personal_buffs": [],
            "markers": [],
        }

    return result


CHARACTER_KITS_DB: dict[str, dict[str, Any]] = _load_character_kits_from_disk()
MANUAL_CHARACTER_KITS: dict[str, dict[str, Any]] = CHARACTER_KITS_DB
