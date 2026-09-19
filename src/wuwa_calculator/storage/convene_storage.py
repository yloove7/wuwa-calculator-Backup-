"""Persistent local storage and cache readers for Convene history."""

from __future__ import annotations

import json
import os
import re
import sqlite3
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
        return self._deduplicate(self._extract_records(payload))

    def merge(self, records: Iterable[object]) -> list[dict[str, object]]:
        merged = self._deduplicate([*self.load(), *self._extract_records(list(records))])
        document = {
            "schema_version": 1,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "pulls": merged,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged

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
        for key in ("seq_id", "seqId", "pull_id", "id"):
            value = record.get(key)
            if value not in (None, ""):
                return f"id:{value}"
        time_value = record.get("time", record.get("timestamp", record.get("date", "")))
        name = record.get("name", record.get("item", record.get("title", "")))
        return f"time-name:{time_value}|{name}"

    @classmethod
    def _deduplicate(cls, records: Iterable[object]) -> list[dict[str, object]]:
        unique: dict[str, dict[str, object]] = {}
        for item in records:
            if isinstance(item, dict):
                unique[cls._record_key(item)] = dict(item)
        return list(unique.values())
