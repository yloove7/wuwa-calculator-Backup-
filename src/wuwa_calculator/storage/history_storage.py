"""Local rotation-history storage without UI or network dependencies."""

# * EDITAVEL: altere o formato do historico junto com app/history_tab.py.
# ! Valide JSON importado antes de usa-lo na interface.

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, TypeGuard

from src.wuwa_calculator.utils.paths import get_legacy_data_path, get_user_data_path

ROTATION_HISTORY_FILE = get_user_data_path("rotation_history.json")


def _is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _dict_records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [record for record in value if _is_string_object_dict(record)]


def _integer_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _float_value(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _migrate_legacy_history(path: Path) -> None:
    legacy_path = get_legacy_data_path("rotation_history.json")
    if path != ROTATION_HISTORY_FILE or not legacy_path.exists():
        return
    try:
        current = read_json_file(path, None)
        legacy = read_json_file(legacy_path, None)
        current_has_data = isinstance(current, dict) and any(
            isinstance(current.get(key), list) and current.get(key)
            for key in ("teams", "rotations", "comparisons")
        )
        legacy_has_data = isinstance(legacy, dict) and any(
            isinstance(legacy.get(key), list) and legacy.get(key)
            for key in ("teams", "rotations", "comparisons")
        )
        if not current_has_data and legacy_has_data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return


def read_json_file(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def write_json_file(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def empty_rotation_document() -> dict[str, object]:
    return {"schema_version": 2, "updated_at": "", "teams": [], "rotations": [], "comparisons": []}


def load_rotation_document(path: Path = ROTATION_HISTORY_FILE) -> dict[str, object]:
    _migrate_legacy_history(path)
    stored = read_json_file(path, None)
    document = empty_rotation_document()
    if isinstance(stored, list):
        document["rotations"] = [record for record in stored if isinstance(record, dict)]
    elif isinstance(stored, dict):
        document.update({key: value for key, value in stored.items() if key in document})
        for key in ("teams", "rotations", "comparisons"):
            if not isinstance(document.get(key), list):
                document[key] = []
    return document


def save_rotation_document(document: dict[str, object], path: Path = ROTATION_HISTORY_FILE) -> None:
    normalized = {**empty_rotation_document(), **document}
    normalized["schema_version"] = 2
    normalized["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json_file(path, normalized)


def load_rotation_history(path: Path = ROTATION_HISTORY_FILE) -> list[dict[str, object]]:
    rotations = load_rotation_document(path).get("rotations", [])
    return _dict_records(rotations)


def load_rotation_teams(path: Path = ROTATION_HISTORY_FILE) -> list[dict[str, object]]:
    teams = load_rotation_document(path).get("teams", [])
    return _dict_records(teams)


def save_rotation_test(
    team: str,
    rotation: str,
    damage: float,
    video: str = "",
    path: Path = ROTATION_HISTORY_FILE,
    skills: list[dict[str, object]] | None = None,
    practical_damage: float | None = None,
) -> dict[str, object]:
    document = load_rotation_document(path)
    history = _dict_records(document.get("rotations"))
    valid_ids = [_integer_value(record.get("id")) for record in history]
    next_id = max(valid_ids, default=0) + 1
    record: dict[str, object] = {
        "id": next_id,
        "team": team.strip() or "Time sem nome",
        "rotation": rotation.strip() or "Rotação sem nome",
        "damage": float(damage),
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "video": video.strip(),
        "skills": skills or [],
    }
    if practical_damage is not None:
        record["practical_damage"] = float(practical_damage)
    history.append(record)
    document["rotations"] = history
    comparisons = document.get("comparisons", [])
    if not isinstance(comparisons, list):
        comparisons = []
    comparisons.append({
        "rotation_id": next_id,
        "theoretical": float(damage),
        "practical": practical_damage,
        "skills": skills or [],
    })
    document["comparisons"] = comparisons
    save_rotation_document(document, path)
    return record


def import_rotation_history(
    source_path: Path,
    destination_path: Path = ROTATION_HISTORY_FILE,
) -> list[dict[str, object]]:
    imported_data = read_json_file(source_path, None)
    if imported_data is None:
        raise ValueError("O arquivo JSON não pôde ser lido ou está inválido.")
    imported_document = imported_data if _is_string_object_dict(imported_data) else {}
    candidates: list[object]
    if isinstance(imported_data, list):
        candidates = imported_data
    elif _is_string_object_dict(imported_data):
        selected_candidates = next(
            (value for key, value in imported_data.items() if key.casefold() in {"history", "rotations", "tests", "records"} and isinstance(value, list)),
            None,
        )
        if isinstance(selected_candidates, list):
            candidates = selected_candidates
        else:
            candidates = [imported_data] if any(key in imported_data for key in ("team", "rotation", "damage", "total_damage")) else []
    else:
        candidates = []
    imported_candidates = _dict_records(candidates)
    if not imported_candidates:
        raise ValueError("O JSON não contém testes de rotação reconhecíveis.")

    destination_document = load_rotation_document(destination_path)
    history = _dict_records(destination_document.get("rotations"))
    imported_teams = imported_document.get("teams", [])
    if isinstance(imported_teams, list):
        existing_teams = _dict_records(destination_document.get("teams"))
        existing_names = {str(team.get("name", "")).casefold() for team in existing_teams}
        for team in imported_teams:
            if isinstance(team, dict) and str(team.get("name", "")).casefold() not in existing_names:
                existing_teams.append(team)
                existing_names.add(str(team.get("name", "")).casefold())
        destination_document["teams"] = existing_teams
    used_ids = [_integer_value(record.get("id")) for record in history]
    next_id = max(used_ids, default=0) + 1
    imported_records: list[dict[str, object]] = []
    for item in imported_candidates:
        source = item
        raw_damage = source.get("damage", source.get("total_damage", source.get("totalDamage", 0)))
        try:
            if isinstance(raw_damage, bool) or not isinstance(raw_damage, (str, int, float)):
                raise ValueError
            damage = float(raw_damage)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Dano inválido no registro importado: {raw_damage!r}.") from error
        record: dict[str, object] = {
            "id": next_id,
            "team": str(source.get("team", source.get("team_name", source.get("name", "Time sem nome")))).strip() or "Time sem nome",
            "rotation": str(source.get("rotation", source.get("rotation_name", source.get("title", "Rotação sem nome")))).strip() or "Rotação sem nome",
            "damage": damage,
            "date": str(source.get("date", source.get("timestamp", datetime.now().astimezone().isoformat(timespec="seconds")))),
            "video": str(source.get("video", source.get("video_path", ""))).strip(),
            "skills": source.get("skills", source.get("skill_details", [])) if isinstance(source.get("skills", source.get("skill_details", [])), list) else [],
        }
        practical_value = source.get("practical_damage", source.get("practicalDamage"))
        if practical_value not in (None, ""):
            try:
                if isinstance(practical_value, bool) or not isinstance(practical_value, (str, int, float)):
                    raise ValueError
                record["practical_damage"] = float(practical_value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(f"Dano prático inválido no registro importado: {practical_value!r}.") from error
        imported_records.append(record)
        history.append(record)
        next_id += 1
    destination_document["rotations"] = history
    destination_comparisons = destination_document.get("comparisons", [])
    if not isinstance(destination_comparisons, list):
        destination_comparisons = []
    imported_comparisons = imported_document.get("comparisons")
    if isinstance(imported_comparisons, list):
        destination_comparisons.extend(item for item in imported_comparisons if isinstance(item, dict))
    else:
        destination_comparisons.extend(
            {
                "rotation_id": _integer_value(record.get("id")),
                "theoretical": _float_value(record.get("damage")),
                "practical": record.get("practical_damage"),
                "skills": record.get("skills", []),
            }
            for record in imported_records
        )
    destination_document["comparisons"] = destination_comparisons
    save_rotation_document(destination_document, destination_path)
    return imported_records


def export_rotation_history(source: Path = ROTATION_HISTORY_FILE, destination: Path | None = None) -> None:
    target = destination or source
    save_rotation_document(load_rotation_document(source), target)
