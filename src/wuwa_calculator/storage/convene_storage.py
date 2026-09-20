"""Persistent local storage and cache readers for Convene history."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.wuwa_calculator.utils.paths import get_user_data_path

CONVENE_HISTORY_FILE = get_user_data_path("convene_history.json")
_CACHE_DIR_NAMES = {"webcache", "krksdkwebview", "krsdkwebview"}
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)


class ConveneStorageManager:
    """Owns local Convene history, JSON backups, and cache extraction."""

    def __init__(self, path: Path = CONVENE_HISTORY_FILE) -> None:
        self.path = Path(path)

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
        records = self._extract_records(payload)
        if not records:
            raise ValueError("O JSON não contém registros de Convene reconhecíveis.")
        return self.merge(records)

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
            try:
                if isinstance(value, (int, float)):
                    return (0, float(value), index)
                text = str(value or "").strip().replace("Z", "+00:00")
                return (0, datetime.fromisoformat(text).timestamp(), index)
            except (TypeError, ValueError, OverflowError):
                return (1, 0.0, index)

        return [record for _, record in sorted(enumerate(records), key=sort_key)]
