"""Weapons database."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.wuwa_calculator.data.images import CHARACTER_IMAGE_FALLBACKS

_DATA_ROOT = Path(__file__).resolve().parent
_WEAPONS_ROOT = _DATA_ROOT / "weapons"
_LEGACY_WEAPONS_ROOT = _WEAPONS_ROOT / "Weapons"
_CHARACTER_ROOT = _DATA_ROOT / "characters"
_CHARACTER_DATA_ROOT = _CHARACTER_ROOT / "data"
_CHARACTER_WEAPONS_ROOT = _CHARACTER_ROOT / "Weapons"


def _normalize_weapon_id(value: str) -> str:
    return str(value).strip().replace("_", " ").lower()


def _stringify_passive_block(locale_payload: Any, *, locale: str) -> str:
    if isinstance(locale_payload, str):
        return locale_payload

    if not isinstance(locale_payload, dict):
        return ""

    base_atk = locale_payload.get("base_atk")
    if base_atk is None:
        base_atk = locale_payload.get("base_atk_lv_90") or 412

    energy_regen = locale_payload.get("energy_regen")
    if energy_regen is None:
        energy_regen = locale_payload.get("energy_regen_pct") or locale_payload.get("regen") or 76.9

    passive_name = locale_payload.get("passive_name") or locale_payload.get("name") or ""
    description = locale_payload.get("description") or locale_payload.get("text") or ""
    effects = locale_payload.get("effects") or []

    if locale == "PT-BR":
        header_1 = "ATQ BASE (NV. 90):"
        header_2 = "REGEN. DE ENERGIA:"
    else:
        header_1 = "BASE ATK (LV. 90):"
        header_2 = "ENERGY REGEN:"

    lines: list[str] = [
        f"{header_1} {base_atk}",
        f"{header_2} {energy_regen}%",
        "",
        str(passive_name),
        "",
    ]

    if description:
        lines.append(str(description))

    for effect in effects:
        if not effect:
            continue
        lines.append("")
        lines.append(str(effect))

    return "\n".join(lines).strip()


def _safe_json_load(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _read_character_weapon_passives() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}

    roots = [
        _WEAPONS_ROOT,
        _LEGACY_WEAPONS_ROOT,
        _CHARACTER_WEAPONS_ROOT,
        _CHARACTER_DATA_ROOT,
    ]

    for root in roots:
        if not root.exists():
            continue
        for character_dir in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if not character_dir.is_dir():
                continue

            json_files = sorted(
                [path for path in character_dir.iterdir() if path.is_file() and path.suffix.lower() == ".json"],
                key=lambda path: path.name.lower(),
            )
            if not json_files:
                continue

            payload = None
            for json_path in json_files:
                candidate = _safe_json_load(json_path)
                if candidate:
                    payload = candidate
                    break

            if not payload:
                continue

            weapon_id = _normalize_weapon_id(character_dir.name)
            name_value = str(payload.get("name") or payload.get("weapon_name") or "").strip()
            pt_br_value = payload.get("PT-BR") or payload.get("pt_br") or payload.get("description") or payload.get("passive") or ""
            en_value = payload.get("EN") or payload.get("en") or payload.get("description") or payload.get("passive") or ""
            candidate = {
                "name": name_value,
                "PT-BR": _stringify_passive_block(pt_br_value, locale="PT-BR"),
                "EN": _stringify_passive_block(en_value, locale="EN"),
            }
            if not candidate["name"] and not candidate["PT-BR"] and not candidate["EN"]:
                continue
            existing = result.get(weapon_id)
            if existing and (existing.get("name") or existing.get("PT-BR") or existing.get("EN")):
                continue
            result[weapon_id] = candidate
    return result


def _read_registry_from_disk() -> dict[str, Any]:
    registry_path = _WEAPONS_ROOT / "registry.json"
    if not registry_path.exists():
        return {}
    payload = _safe_json_load(registry_path)
    if not isinstance(payload, dict):
        return {}
    return payload


def _read_passives_from_disk() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    result.update(_read_character_weapon_passives())
    return result


def _build_weapon_name_map() -> dict[str, str]:
    registry = _read_passives_from_disk()
    name_map: dict[str, str] = {}
    for weapon_id, values in registry.items():
        weapon_name = str(values.get("name") or "").strip()
        if weapon_name:
            name_map[str(weapon_id)] = weapon_name
    return name_map


_LOCAL_KIT_WEAPON_NAMES: dict[str, str] = _build_weapon_name_map()


def resolve_weapon_fallback(character_id: str, default: str = "") -> str:
    fallback = CHARACTER_IMAGE_FALLBACKS.get(character_id, {})
    if isinstance(fallback, dict):
        weapon_value = fallback.get("weapon")
        if weapon_value:
            return str(weapon_value)
    return default


MANUAL_WEAPONS: dict[str, dict[str, Any]] = _read_passives_from_disk()
WEAPON_REGISTRY: dict[str, Any] = _read_registry_from_disk()
