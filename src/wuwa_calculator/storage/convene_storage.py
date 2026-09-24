"""Persistent local storage and cache readers for Convene history."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.wuwa_calculator.utils.convene_datetime import parse_convene_datetime
from src.wuwa_calculator.utils.paths import get_user_data_path

CONVENE_HISTORY_FILE = get_user_data_path("convene_history.json")
_CACHE_DIR_NAMES = {"webcache", "krksdkwebview", "krsdkwebview"}
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_WUWA_TRACKER_POOLS = {
    1: "resonator",
    2: "weapon",
    3: "standard_character",
    4: "standard_weapon",
}


def _context_pool_type(value: object) -> int:
    if value is None or value == "":
        return 1
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return 1
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 1


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


class ConveneStorageManager:
    """Owns local Convene history, JSON backups, and cache extraction."""

    def __init__(self, path: Path = CONVENE_HISTORY_FILE) -> None:
        self.path = Path(path)
        self.last_import_report: ConveneJsonImportReport | None = None

    def load(self) -> list[dict[str, object]]:
        try:
            if not self.path.exists() or os.path.getsize(self.path) <= 0:
                return []
        except OSError:
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return self._sort_records(self._deduplicate(self._extract_records(payload)))

    def load_context(self) -> dict[str, object] | None:
        try:
            if not self.path.exists() or os.path.getsize(self.path) <= 0:
                return None
        except OSError:
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        context = payload.get("convene_context")
        if not isinstance(context, dict):
            return None
        required = (
            "player_id",
            "record_id",
            "server_id",
            "card_pool_id",
            "language_code",
        )
        if not all(str(key) in context for key in required):
            return None
        normalized = {
            "player_id": str(context.get("player_id") or ""),
            "record_id": str(context.get("record_id") or ""),
            "server_id": str(context.get("server_id") or ""),
            "card_pool_id": str(context.get("card_pool_id") or ""),
            "language_code": str(context.get("language_code") or "en"),
            "card_pool_type": _context_pool_type(context.get("card_pool_type")),
        }
        if not all(normalized[key] for key in ("player_id", "record_id", "server_id", "card_pool_id")):
            return None
        return normalized

    def save_context(self, context: Mapping[str, object] | None) -> None:
        if not isinstance(context, dict):
            return
        required = (
            "player_id",
            "record_id",
            "server_id",
            "card_pool_id",
        )
        if not all(context.get(key) not in (None, "") for key in required):
            return
        document: dict[str, object] = {}
        try:
            if self.path.exists() and os.path.getsize(self.path) > 0:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    document = existing
        except (OSError, json.JSONDecodeError):
            document = {}
        document["schema_version"] = 1
        document["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        document["convene_context"] = {
            "player_id": str(context.get("player_id") or ""),
            "record_id": str(context.get("record_id") or ""),
            "server_id": str(context.get("server_id") or ""),
            "card_pool_id": str(context.get("card_pool_id") or ""),
            "language_code": str(context.get("language_code") or "en"),
            "card_pool_type": _context_pool_type(context.get("card_pool_type")),
        }
        if "pulls" not in document or not isinstance(document["pulls"], list):
            document["pulls"] = self.load()
        self._write_document(document)

    def merge(self, records: Iterable[object]) -> list[dict[str, object]]:
        merged, _new_records_count = self.merge_with_metadata(records)
        return merged

    def merge_with_metadata(
        self,
        records: Iterable[object],
    ) -> tuple[list[dict[str, object]], int]:
        existing = self.load()
        incoming = [
            record for record in self._extract_records(list(records))
            if self._is_pull_record(record)
        ]
        existing_keys = {
            key for key in (self._record_key(record) for record in existing) if key
        }
        incoming_keys = {
            key for key in (self._record_key(record) for record in incoming) if key
        }
        merged = self._sort_records(
            self._deduplicate([*existing, *incoming])
        )
        document = {
            "schema_version": 1,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "pulls": merged,
        }
        self._write_document(document)
        return merged, len(incoming_keys - existing_keys)

    def _write_document(self, document: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(document, ensure_ascii=False, indent=2)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def import_json(self, source: Path) -> list[dict[str, object]]:
        source = Path(source)
        if not source.exists() or os.path.getsize(source) <= 0:
            raise ValueError("O backup JSON está vazio ou não existe.")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("O backup JSON não pôde ser lido.") from error
        if self._looks_like_wuwa_tracker(payload):
            self.last_import_report = self._import_wuwa_tracker(payload)
            return self.last_import_report.records
        records = self._extract_records(payload)
        if not records:
            raise ValueError("O JSON não contém registros de Convene reconhecíveis.")
        return self.merge(records)

    def import_json_with_report(self, source: Path) -> ConveneJsonImportReport:
        """Import JSON and return diagnostics; use this for WuWa Tracker files."""
        source = Path(source)
        if not source.exists() or os.path.getsize(source) <= 0:
            raise ValueError("Backup JSON is empty or does not exist.")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Backup JSON could not be read.") from error
        if self._looks_like_wuwa_tracker(payload):
            report = self._import_wuwa_tracker(payload)
            self.last_import_report = report
            return report
        records = self._extract_records(payload)
        if not records:
            raise ValueError("JSON contains no recognizable Convene records.")
        merged, count = self.merge_with_metadata(records)
        report = ConveneJsonImportReport(records=merged, format="generic", imported_count=count)
        self.last_import_report = report
        return report

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

    def _import_wuwa_tracker(self, payload: object) -> ConveneJsonImportReport:
        if not isinstance(payload, dict):
            raise ValueError("WuWa Tracker export must be a JSON object.")
        player_value = payload.get("playerId")
        if not isinstance(player_value, (str, int)) or isinstance(player_value, bool) or not str(player_value).strip():
            raise ValueError("WuWa Tracker export has no valid playerId.")
        player_id = str(player_value).strip()
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
                normalized.append(self._normalize_wuwa_tracker_pull(pull, player_id, source_metadata))
            except ValueError as error:
                invalid.append({"index": index, "raw": dict(pull), "reason": str(error)})

        if normalized:
            merged, count = self._merge_wuwa_tracker_records(normalized, player_id)
        else:
            merged, count = self.load(), 0
        report = ConveneJsonImportReport(
            records=merged,
            format="wuwa_tracker",
            player_id=player_id,
            imported_count=count,
            source_metadata=source_metadata,
            unsupported_pools=unsupported,
            invalid_records=invalid,
        )
        self.last_import_report = report
        return report

    def _merge_wuwa_tracker_records(
        self,
        incoming: list[dict[str, object]],
        player_id: str,
    ) -> tuple[list[dict[str, object]], int]:
        document: dict[str, object] = {}
        if self.path.exists():
            try:
                text = self.path.read_text(encoding="utf-8")
                existing_payload = json.loads(text) if text.strip() else {}
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("Cannot validate existing history; import cancelled.") from error
            if not isinstance(existing_payload, dict):
                raise ValueError("Existing history has an invalid format; import cancelled.")
            document = dict(existing_payload)
        existing = self._extract_records(document)
        context = document.get("convene_context")
        context_player = str(context.get("player_id") or "").strip() if isinstance(context, dict) else ""
        tagged_players = {
            str(record.get("player_id", record.get("playerId"))).strip()
            for record in existing
            if record.get("player_id", record.get("playerId")) not in (None, "")
        }
        if any(existing_player != player_id for existing_player in tagged_players):
            raise ValueError("Existing history belongs to another playerId; import cancelled.")
        untagged_existing = any(
            record.get("player_id", record.get("playerId")) in (None, "")
            for record in existing
        )
        if untagged_existing and context_player != player_id:
            raise ValueError("Cannot establish owner of existing history; import cancelled.")
        if context_player and context_player != player_id:
            raise ValueError("Existing convene_context belongs to another playerId; import cancelled.")

        existing_keys = {self._record_key(record) for record in existing if self._record_key(record)}
        incoming_keys = {self._record_key(record) for record in incoming if self._record_key(record)}
        merged = self._sort_records(self._deduplicate([*existing, *incoming]))
        document["schema_version"] = document.get("schema_version", 1)
        document["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        document["pulls"] = merged
        self._write_document(document)
        return merged, len(incoming_keys - existing_keys)

    def scan_local_cache(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for root in self._cache_roots():
            if not root.exists():
                continue
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.casefold() in {".json", ".log", ".txt", ".localstorage"}:
                    records.extend(self._records_from_text_file(file_path))
                elif file_path.suffix.casefold() in {".sqlite", ".db", ".sqlite3"}:
                    records.extend(self._records_from_sqlite(file_path))
        if not records:
            return self.load()
        return self.merge(records)

    @staticmethod
    def _cache_roots() -> list[Path]:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        roots = [
            local_app_data / "Wuthering Waves" / "Saved" / "webcache",
            local_app_data / "Wuthering Waves" / "Saved" / "KRSDKWebView",
            local_app_data / "Wuthering Waves" / "Saved" / "KRKSDKWebview",
        ]
        return list(dict.fromkeys(roots))

    @classmethod
    def _records_from_text_file(cls, path: Path) -> list[dict[str, object]]:
        try:
            if os.path.getsize(path) <= 0:
                return []
        except OSError:
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        records: list[dict[str, object]] = []
        try:
            payload = json.loads(text)
            records.extend(cls._extract_records(payload))
        except json.JSONDecodeError:
            pass
        for url in _URL_RE.findall(text):
            if "/record?" in url:
                records.append({"record_url": url, "source": str(path)})
        return records

    @staticmethod
    def _records_from_sqlite(path: Path) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            for (table_name,) in tables:
                columns = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                names = [str(column[1]) for column in columns]
                if not names:
                    continue
                rows = connection.execute(f'SELECT * FROM "{table_name}" LIMIT 5000').fetchall()
                for row in rows:
                    values = {names[index]: value for index, value in enumerate(row)}
                    text = " ".join(str(value) for value in values.values() if value is not None)
                    if "record" in text.casefold() or "player_id" in text.casefold():
                        records.append(values)
            connection.close()
        except (OSError, sqlite3.Error):
            return []
        return records

    @classmethod
    def _extract_records(cls, payload: object) -> list[dict[str, object]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("pulls", "records", "history", "items", "list", "data"):
            value = payload.get(key)
            records = cls._extract_records(value)
            if records:
                return records
        if any(key in payload for key in ("seq_id", "seqId", "id", "name", "time", "timestamp", "record_url")):
            return [payload]
        return []

    @staticmethod
    def _record_key(record: dict[str, object]) -> str:
        explicit_key = record.get("dedup_key")
        if explicit_key not in (None, ""):
            return str(explicit_key)
        for key in ("seq_id", "seqId", "pull_id", "id"):
            value = record.get(key)
            if value not in (None, ""):
                return f"id:{value}"
        time_value = record.get("time", record.get("timestamp", record.get("date", "")))
        name = record.get("name", record.get("item", record.get("title", "")))
        pool = record.get("pool", record.get("type", record.get("gacha_type", "")))
        rarity = record.get("rarity", record.get("quality", record.get("rank", "")))
        if all(value not in (None, "") for value in (time_value, pool, name, rarity)):
            return f"fields:{time_value}|{pool}|{name}|{rarity}"
        signature_fields = {
            key: record.get(key)
            for key in ("timestamp", "pool", "name", "rarity", "item", "title")
            if record.get(key) not in (None, "")
        }
        if all(key in signature_fields for key in ("timestamp", "pool", "name", "rarity")):
            payload = json.dumps(signature_fields, ensure_ascii=False, sort_keys=True)
            return f"signature:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
        return ""

    @classmethod
    def _is_pull_record(cls, record: dict[str, object]) -> bool:
        if record.get("is_pull") is False:
            return False
        return bool(cls._record_key(record))

    @classmethod
    def _deduplicate(cls, records: Iterable[object]) -> list[dict[str, object]]:
        unique: dict[str, dict[str, object]] = {}
        unkeyed: list[dict[str, object]] = []
        for item in records:
            if isinstance(item, dict):
                key = cls._record_key(item)
                if key:
                    unique[key] = dict(item)
                else:
                    unkeyed.append(dict(item))
        return [*unique.values(), *unkeyed]

    @staticmethod
    def _sort_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
        def sort_key(item: tuple[int, dict[str, object]]) -> tuple[int, float, int]:
            index, record = item
            value = record.get("timestamp", record.get("time", record.get("date")))
            parsed = parse_convene_datetime(value)
            if parsed is None:
                return (1, 0.0, index)
            return (0, parsed.timestamp(), index)

        return [record for _, record in sorted(enumerate(records), key=sort_key)]
