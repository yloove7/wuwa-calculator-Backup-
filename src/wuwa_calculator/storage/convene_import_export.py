"""Import and export adapters for local Convene history formats."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.wuwa_calculator.domain.pity import record_pool
from src.wuwa_calculator.utils.convene_datetime import parse_convene_datetime

_WUWA_TRACKER_POOLS = {
    1: "resonator",
    2: "weapon",
    3: "standard_character",
    4: "standard_weapon",
}
_TETHYS_HISTORY_FORMAT = "tethys_convene_history"
_TETHYS_HISTORY_VERSION = 1
_TETHYS_HISTORY_POOLS = {
    "resonator",
    "weapon",
    "standard_character",
    "standard_weapon",
}


@dataclass
class ConveneJsonImportReport:
    """Detailed outcome for importing a generic or WuWa Tracker JSON file."""

    records: list[dict[str, object]]
    format: str
    player_id: str | None = None
    imported_count: int = 0
    source_metadata: dict[str, object] = field(default_factory=dict)
    unsupported_pools: list[dict[str, object]] = field(default_factory=list)
    invalid_records: list[dict[str, object]] = field(default_factory=list)


class _ConveneStoragePort(Protocol):
    path: Path
    last_import_report: ConveneJsonImportReport | None

    def load(self) -> list[dict[str, object]]: ...

    def merge(self, records: list[dict[str, object]]) -> list[dict[str, object]]: ...

    def merge_with_metadata(
        self,
        records: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int]: ...

    def _extract_records(self, payload: object) -> list[dict[str, object]]: ...

    def _record_key(self, record: dict[str, object]) -> str: ...

    def _validate_player_id(self, player_id: str) -> str: ...

    def _merge_wuwa_tracker_records(
        self,
        incoming: list[dict[str, object]],
        player_id: str,
    ) -> tuple[list[dict[str, object]], int]: ...


class ConveneImportExport:
    """Parse portable formats and delegate persistence to ConveneStorageManager."""

    @classmethod
    def import_json(
        cls,
        storage: _ConveneStoragePort,
        source: Path,
    ) -> list[dict[str, object]]:
        report = cls._import_json_internal(
            storage,
            source,
            with_report=False,
            empty_message="O backup JSON está vazio ou não existe.",
            read_error_message="O backup JSON não pôde ser lido.",
            invalid_message="O JSON não contém registros de Convene reconhecíveis.",
        )
        if report.format != "generic":
            storage.last_import_report = report
        return report.records

    @classmethod
    def import_json_with_report(
        cls,
        storage: _ConveneStoragePort,
        source: Path,
    ) -> ConveneJsonImportReport:
        """Import JSON and return diagnostics; use this for WuWa Tracker files."""
        report = cls._import_json_internal(
            storage,
            source,
            with_report=True,
            empty_message="Backup JSON is empty or does not exist.",
            read_error_message="Backup JSON could not be read.",
            invalid_message="JSON contains no recognizable Convene records.",
        )
        storage.last_import_report = report
        return report

    @classmethod
    def _import_json_internal(
        cls,
        storage: _ConveneStoragePort,
        source: Path,
        *,
        with_report: bool,
        empty_message: str,
        read_error_message: str,
        invalid_message: str,
    ) -> ConveneJsonImportReport:
        source = Path(source)
        if not source.exists() or os.path.getsize(source) <= 0:
            raise ValueError(empty_message)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(read_error_message) from error
        if isinstance(payload, dict) and payload.get("format") == _TETHYS_HISTORY_FORMAT:
            return cls._import_tethys_history_payload(storage, payload)
        if cls._looks_like_wuwa_tracker(payload):
            return cls._import_wuwa_tracker(storage, payload)
        records = storage._extract_records(payload)
        if not records:
            raise ValueError(invalid_message)
        if with_report:
            merged, imported_count = storage.merge_with_metadata(records)
        else:
            merged = storage.merge(records)
            imported_count = 0
        return ConveneJsonImportReport(
            records=merged,
            format="generic",
            imported_count=imported_count,
        )

    @classmethod
    def import_tethys_history(
        cls,
        storage: _ConveneStoragePort,
        source: Path,
    ) -> ConveneJsonImportReport:
        """Import a file that must explicitly use the Tethys history format."""
        source = Path(source)
        if not source.exists() or os.path.getsize(source) <= 0:
            raise ValueError("Tethys history JSON is empty or does not exist.")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Tethys history JSON could not be read.") from error
        report = cls._import_tethys_history_payload(storage, payload)
        storage.last_import_report = report
        return report

    @classmethod
    def _import_tethys_history_payload(
        cls,
        storage: _ConveneStoragePort,
        payload: object,
    ) -> ConveneJsonImportReport:
        if not isinstance(payload, dict):
            raise ValueError("Tethys history must be a JSON object.")
        if payload.get("format") != _TETHYS_HISTORY_FORMAT:
            raise ValueError("Unsupported Tethys history format.")
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Tethys history version must be an integer.")
        if version != _TETHYS_HISTORY_VERSION:
            raise ValueError(f"Unsupported Tethys history version: {version}.")
        pulls = payload.get("pulls")
        if not isinstance(pulls, list):
            raise ValueError("Tethys history pulls must be a list.")

        normalized: list[dict[str, object]] = []
        for index, pull in enumerate(pulls):
            if not isinstance(pull, dict):
                raise ValueError(f"Tethys pull at index {index} must be an object.")
            normalized.append(cls._normalize_tethys_pull(pull, index))
        existing_keys = {storage._record_key(record) for record in storage.load()}
        new_records = [
            record for record in normalized
            if storage._record_key(record) not in existing_keys
        ]
        merged, count = storage.merge_with_metadata(new_records)
        return ConveneJsonImportReport(
            records=merged,
            format=_TETHYS_HISTORY_FORMAT,
            imported_count=count,
        )

    @staticmethod
    def _normalize_tethys_pull(
        pull: dict[str, object],
        index: int,
    ) -> dict[str, object]:
        required = ("timestamp", "pool", "name", "rarity")
        missing = [key for key in required if key not in pull]
        if missing:
            raise ValueError(
                f"Tethys pull at index {index} is missing required field(s): "
                f"{', '.join(missing)}."
            )
        parsed_timestamp = parse_convene_datetime(pull["timestamp"])
        if parsed_timestamp is None:
            raise ValueError(f"Tethys pull at index {index} has an invalid timestamp.")
        pool = pull["pool"]
        if not isinstance(pool, str) or pool not in _TETHYS_HISTORY_POOLS:
            raise ValueError(f"Tethys pull at index {index} has an invalid pool.")
        name = pull["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Tethys pull at index {index} has an invalid name.")
        rarity = pull["rarity"]
        if isinstance(rarity, bool) or not isinstance(rarity, int) or rarity not in {3, 4, 5}:
            raise ValueError(f"Tethys pull at index {index} has an invalid rarity.")
        return {
            "timestamp": parsed_timestamp.isoformat(),
            "pool": pool,
            "name": name.strip(),
            "rarity": rarity,
        }

    @staticmethod
    def to_tethys_pull(
        record: dict[str, object],
        index: int,
    ) -> dict[str, object]:
        """Build the portable Tethys pull projection used by sync metadata."""
        timestamp_value = record.get("timestamp", record.get("time", record.get("date")))
        parsed_timestamp = parse_convene_datetime(timestamp_value)
        if parsed_timestamp is None:
            raise ValueError(f"Local pull at index {index} has an invalid timestamp.")
        pool_value = record.get("pool")
        pool = (
            pool_value
            if isinstance(pool_value, str) and pool_value in _TETHYS_HISTORY_POOLS
            else record_pool(record)
        )
        name = record.get("name", record.get("item", record.get("title")))
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Local pull at index {index} has an invalid name.")
        rarity = record.get("rarity", record.get("quality", record.get("rank")))
        if isinstance(rarity, bool) or not isinstance(rarity, int) or rarity not in {3, 4, 5}:
            raise ValueError(f"Local pull at index {index} has an invalid rarity.")
        return {
            "timestamp": parsed_timestamp.isoformat(),
            "pool": pool,
            "name": name.strip(),
            "rarity": rarity,
        }

    @staticmethod
    def _looks_like_wuwa_tracker(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if "playerId" in payload:
            return True
        pulls = payload.get("pulls")
        return isinstance(pulls, list) and any(
            isinstance(pull, dict)
            and any(key in pull for key in ("cardPoolType", "qualityLevel", "resourceId"))
            for pull in pulls
        )

    @staticmethod
    def _normalize_wuwa_tracker_pull(
        pull: dict[str, object],
        player_id: str,
        source_metadata: dict[str, object],
    ) -> dict[str, object]:
        pool_type = pull.get("cardPoolType")
        if isinstance(pool_type, bool) or not isinstance(pool_type, int) or pool_type not in _WUWA_TRACKER_POOLS:
            raise ValueError(f"Unsupported cardPoolType: {pool_type!r}")
        timestamp = pull.get("time")
        parsed_timestamp = parse_convene_datetime(timestamp)
        if parsed_timestamp is None:
            raise ValueError("Missing or invalid time")
        name = pull.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing or invalid name")
        rarity_value = pull.get("qualityLevel")
        if isinstance(rarity_value, bool):
            raise ValueError("Invalid qualityLevel")
        if not isinstance(rarity_value, (str, int, float)):
            raise ValueError("Missing or invalid qualityLevel")
        try:
            rarity = int(rarity_value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Missing or invalid qualityLevel") from error
        if rarity <= 0 or (isinstance(rarity_value, float) and rarity_value != rarity):
            raise ValueError("Invalid qualityLevel")

        raw = dict(pull)
        identity = {
            "player_id": player_id,
            "pool": _WUWA_TRACKER_POOLS[pool_type],
            "timestamp": parsed_timestamp.isoformat(),
            "name": name.strip(),
            "rarity": rarity,
        }
        identity_json = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        normalized: dict[str, object] = {
            **raw,
            "timestamp": timestamp,
            "name": name.strip(),
            "rarity": rarity,
            "pool": _WUWA_TRACKER_POOLS[pool_type],
            "player_id": player_id,
            "source": "wuwa_tracker",
            "source_metadata": dict(source_metadata),
            "raw": raw,
            "dedup_key": "wuwa_tracker:" + hashlib.sha256(identity_json.encode("utf-8")).hexdigest(),
        }
        # resourceId remains source data and is never promoted to official_id.
        for key in ("seq_id", "seqId", "pull_id", "id"):
            if raw.get(key) not in (None, ""):
                normalized["official_id"] = raw[key]
                break
        return normalized

    @classmethod
    def _import_wuwa_tracker(
        cls,
        storage: _ConveneStoragePort,
        payload: object,
    ) -> ConveneJsonImportReport:
        if not isinstance(payload, dict):
            raise ValueError("WuWa Tracker export must be a JSON object.")
        player_value = payload.get("playerId")
        if not isinstance(player_value, (str, int)) or isinstance(player_value, bool) or not str(player_value).strip():
            raise ValueError("WuWa Tracker export has no valid playerId.")
        try:
            player_id = storage._validate_player_id(str(player_value).strip())
        except ValueError as error:
            raise ValueError("WuWa Tracker export has no valid playerId.") from error
        pulls = payload.get("pulls")
        if not isinstance(pulls, list):
            raise ValueError("WuWa Tracker export pulls must be a list.")
        source_metadata = {
            key: payload[key]
            for key in ("siteVersion", "version", "date")
            if key in payload
        }
        normalized: list[dict[str, object]] = []
        unsupported: list[dict[str, object]] = []
        invalid: list[dict[str, object]] = []
        for index, pull in enumerate(pulls):
            if not isinstance(pull, dict):
                invalid.append({"index": index, "raw": pull, "reason": "pull is not an object"})
                continue
            pool_type = pull.get("cardPoolType")
            if isinstance(pool_type, bool) or not isinstance(pool_type, int) or pool_type not in _WUWA_TRACKER_POOLS:
                unsupported.append({"index": index, "cardPoolType": pool_type, "raw": dict(pull)})
                continue
            try:
                normalized.append(cls._normalize_wuwa_tracker_pull(pull, player_id, source_metadata))
            except ValueError as error:
                invalid.append({"index": index, "raw": dict(pull), "reason": str(error)})

        if normalized:
            merged, count = storage._merge_wuwa_tracker_records(normalized, player_id)
        else:
            merged, count = storage.load(), 0
        report = ConveneJsonImportReport(
            records=merged,
            format="wuwa_tracker",
            player_id=player_id,
            imported_count=count,
            source_metadata=source_metadata,
            unsupported_pools=unsupported,
            invalid_records=invalid,
        )
        storage.last_import_report = report
        return report

    @classmethod
    def export_tethys_history(
        cls,
        storage: _ConveneStoragePort,
        destination: Path,
        *,
        player_id: str | None = None,
    ) -> dict[str, object]:
        """Write a WuWa Tracker-shaped history file without changing storage."""
        destination = Path(destination)
        if destination.resolve() == storage.path.resolve():
            raise ValueError("History export destination must differ from local history storage.")
        try:
            payload: object = (
                json.loads(storage.path.read_text(encoding="utf-8"))
                if storage.path.exists() and os.path.getsize(storage.path) > 0
                else {}
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Cannot read local history for export.") from error
        context = payload.get("convene_context") if isinstance(payload, dict) else None
        records = storage._extract_records(payload)
        active_player_id = (
            storage._validate_player_id(player_id)
            if player_id is not None
            else cls._record_player_id(context)
            if isinstance(context, dict)
            else None
        )
        if active_player_id is not None:
            records = [
                record for record in records
                if cls._record_player_id(record) == active_player_id
            ]
        else:
            # Without an active identity, export only unowned legacy/manual rows.
            records = [record for record in records if cls._record_player_id(record) is None]
        exported_player_id = cls._export_player_id(records, {"player_id": active_player_id})
        document: dict[str, object] = {
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        if exported_player_id is not None:
            document["playerId"] = exported_player_id
        timestamped_records = [
            (index, record, cls._wuwa_export_timestamp(record, index))
            for index, record in enumerate(records)
        ]
        timestamped_records.sort(key=lambda item: (item[2].timestamp(), item[0]))
        pulls = [
            cls._to_wuwa_tracker_pull(record, index, export_time)
            for index, record, export_time in timestamped_records
        ]
        document["pulls"] = pulls
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return document

    @staticmethod
    def _record_player_id(record: object) -> str | None:
        if not isinstance(record, dict):
            return None
        value = record.get("player_id", record.get("playerId"))
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _wuwa_export_timestamp(record: dict[str, object], index: int) -> datetime:
        timestamp_value = record.get("time", record.get("timestamp", record.get("date")))
        parsed_timestamp = parse_convene_datetime(timestamp_value)
        if parsed_timestamp is None:
            raise ValueError(f"Local pull at index {index} has an invalid timestamp.")
        return parsed_timestamp

    @staticmethod
    def _export_player_id(records: list[dict[str, object]], context: object) -> str | None:
        if not records or not isinstance(context, dict):
            return None
        context_player_id = context.get("player_id")
        if not isinstance(context_player_id, (str, int)) or isinstance(context_player_id, bool):
            return None
        player_id = str(context_player_id).strip()
        if not player_id:
            return None
        for record in records:
            pull_player_id = record.get("player_id", record.get("playerId"))
            if (
                not isinstance(pull_player_id, (str, int))
                or isinstance(pull_player_id, bool)
                or str(pull_player_id).strip() != player_id
            ):
                return None
        return player_id

    @staticmethod
    def _export_pool_type(record: dict[str, object], index: int) -> int:
        pool_value = record.get("pool")
        if isinstance(pool_value, str) and pool_value in _TETHYS_HISTORY_POOLS:
            pool = pool_value
        else:
            card_pool_type = record.get("cardPoolType")
            numeric_pool = None
            if isinstance(card_pool_type, bool):
                raise ValueError(f"Local pull at index {index} has an unsupported pool.")
            if isinstance(card_pool_type, int):
                if card_pool_type not in _WUWA_TRACKER_POOLS:
                    raise ValueError(f"Local pull at index {index} has an unsupported pool.")
                numeric_pool = _WUWA_TRACKER_POOLS[card_pool_type]

            structural_values = [
                record.get(key)
                for key in ("type", "pool", "banner", "gacha_type", "resource", "cardPoolType")
            ]
            classified: set[str] = set()
            for value in structural_values:
                if not isinstance(value, str) or not value.strip():
                    continue
                text_value = value.casefold()
                if not any(
                    token in text_value
                    for token in ("resonator", "weapon", "arma", "standard", "permanent", "novice")
                ):
                    continue
                classified.add(record_pool({"pool": value}))

            if numeric_pool is not None:
                if classified and classified != {numeric_pool}:
                    raise ValueError(f"Local pull at index {index} has an unsupported or ambiguous pool.")
                pool = numeric_pool
            elif len(classified) == 1:
                pool = next(iter(classified))
            else:
                raise ValueError(f"Local pull at index {index} has an unsupported or ambiguous pool.")

        pool_type = next(
            (tracker_type for tracker_type, mapped_pool in _WUWA_TRACKER_POOLS.items() if mapped_pool == pool),
            None,
        )
        if pool_type is None:
            raise ValueError(f"Local pull at index {index} has an unsupported pool.")
        return pool_type

    @staticmethod
    def _valid_resource_id(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None

    @classmethod
    def _to_wuwa_tracker_pull(
        cls,
        record: dict[str, object],
        index: int,
        parsed_timestamp: datetime,
    ) -> dict[str, object]:
        pool_type = cls._export_pool_type(record, index)
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Local pull at index {index} has an invalid name.")
        quality = record.get("qualityLevel", record.get("rarity", record.get("quality", record.get("rank"))))
        if isinstance(quality, bool) or not isinstance(quality, (int, float, str)):
            raise ValueError(f"Local pull at index {index} has an invalid quality level.")
        try:
            quality_level = int(quality)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Local pull at index {index} has an invalid quality level.") from error
        if quality_level <= 0 or (isinstance(quality, float) and quality != quality_level):
            raise ValueError(f"Local pull at index {index} has an invalid quality level.")

        exported: dict[str, object] = {
            "cardPoolType": pool_type,
            "time": parsed_timestamp.isoformat(),
            "name": name.strip(),
            "qualityLevel": quality_level,
        }
        resource_id = cls._valid_resource_id(record.get("resourceId"))
        if resource_id is not None:
            exported["resourceId"] = resource_id
        return exported


def to_tethys_pull(record: dict[str, object], index: int) -> dict[str, object]:
    """Compatibility helper for internal sync metadata projections."""
    return ConveneImportExport.to_tethys_pull(record, index)
