"""Persistent local storage and cache readers for Convene history."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.wuwa_calculator.storage.convene_import_export import (
    ConveneImportExport,
    ConveneJsonImportReport,
)
from src.wuwa_calculator.utils.convene_datetime import parse_convene_datetime
from src.wuwa_calculator.utils.paths import (
    LEGACY_USER_DATA_ROOT,
    copy_legacy_user_data_file,
    get_user_data_path,
)

CONVENE_HISTORY_FILE = get_user_data_path("convene_history.json")
LEGACY_CONVENE_HISTORY_FILE = (
    LEGACY_USER_DATA_ROOT / "convene_history.json"
)
_CACHE_DIR_NAMES = {"webcache", "krksdkwebview", "krsdkwebview"}
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_PLAYER_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")


def _context_pool_type(value: object) -> int:
    if value is None or value == "":
        return 1
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return 1
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 1


class ConveneStorageManager:
    """Owns local Convene history, JSON backups, and cache extraction."""

    def __init__(self, path: Path = CONVENE_HISTORY_FILE) -> None:
        self.path = Path(path)
        if self.path == CONVENE_HISTORY_FILE:
            try:
                copy_legacy_user_data_file(
                    LEGACY_CONVENE_HISTORY_FILE,
                    self.path,
                )
            except OSError:
                # Keep startup usable if migration storage is unavailable;
                # the legacy source remains untouched for a later retry.
                logging.getLogger(__name__).warning(
                    "Could not migrate legacy Convene history to %s; "
                    "the legacy file was left untouched.",
                    self.path,
                    exc_info=True,
                )
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

    def load_for_player(self, player_id: str) -> list[dict[str, object]]:
        """Load only pulls explicitly associated with one game player.

        Legacy and manually imported rows without an owner remain persisted,
        but are not assigned to whichever player is currently active.
        """
        normalized_player_id = self._validate_player_id(player_id)
        return [
            record for record in self.load()
            if self._record_player_id(record) == normalized_player_id
        ]

    def merge_active_player_with_metadata(
        self,
        records: Iterable[object],
        player_id: str,
        *,
        previous_context_player_id: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        """Merge a live sync into its player's history and return that history.

        Unowned legacy rows are promoted only when the caller preserved the
        immediately preceding context and it identifies this same player.
        """
        normalized_player_id = self._validate_player_id(player_id)
        tagged_records: list[dict[str, object]] = []
        for record in self._extract_records(list(records)):
            if not self._is_pull_record(record):
                continue
            tagged_record = self._without_local_record_id(record)
            # The URL is authoritative for the active sync's player identity.
            tagged_record["player_id"] = normalized_player_id
            tagged_records.append(tagged_record)
        if previous_context_player_id == normalized_player_id:
            merged, new_count = self.merge_with_metadata(
                tagged_records,
                promote_legacy_player=normalized_player_id,
            )
        else:
            merged, new_count = self.merge_with_metadata(tagged_records)
        active_records = [
            record for record in merged
            if self._record_player_id(record) == normalized_player_id
        ]
        return active_records, new_count

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
        if not all(key in context for key in required):
            return None
        raw_player_id = context.get("player_id")
        if (
            isinstance(raw_player_id, bool)
            or not isinstance(raw_player_id, (str, int))
        ):
            return None
        player_id = str(raw_player_id).strip()
        if not player_id or not _PLAYER_ID_RE.fullmatch(player_id):
            return None
        normalized = {
            "player_id": player_id,
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
        # This is the current session/player context, not ownership for old pulls.
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
        *,
        promote_legacy_player: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        existing = self.load()
        incoming = [
            self._without_local_record_id(record)
            for record in self._extract_records(list(records))
            if self._is_pull_record(record)
        ]
        if promote_legacy_player is not None:
            existing = self._promote_matching_legacy_records(
                existing,
                incoming,
                promote_legacy_player,
            )
        existing_keys = {
            key for key in (self._record_key(record) for record in existing) if key
        }
        incoming_keys = {
            key for key in (self._record_key(record) for record in incoming) if key
        }
        merged = self._sort_records(self._deduplicate([*existing, *incoming]))
        self._preserve_or_assign_local_record_ids(existing, incoming, merged)
        document: dict[str, object] = {}
        try:
            if self.path.exists() and os.path.getsize(self.path) > 0:
                stored_payload: object = json.loads(
                    self.path.read_text(encoding="utf-8")
                )
                if isinstance(stored_payload, dict):
                    document = {
                        str(key): value for key, value in stored_payload.items()
                    }
        except (OSError, json.JSONDecodeError):
            document = {}
        document["schema_version"] = 1
        document["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        document["pulls"] = merged
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
        return ConveneImportExport.import_json(self, source)

    def import_json_with_report(self, source: Path) -> ConveneJsonImportReport:
        return ConveneImportExport.import_json_with_report(self, source)

    def export_tethys_history(
        self,
        destination: Path,
        *,
        player_id: str | None = None,
    ) -> dict[str, object]:
        return ConveneImportExport.export_tethys_history(
            self,
            destination,
            player_id=player_id,
        )

    def import_tethys_history(self, source: Path) -> ConveneJsonImportReport:
        return ConveneImportExport.import_tethys_history(self, source)

    @staticmethod
    def _to_tethys_pull(
        record: dict[str, object],
        index: int,
    ) -> dict[str, object]:
        return ConveneImportExport.to_tethys_pull(record, index)

    def _merge_wuwa_tracker_records(
        self,
        incoming: list[dict[str, object]],
        player_id: str,
    ) -> tuple[list[dict[str, object]], int]:
        incoming = [self._without_local_record_id(record) for record in incoming]
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
        untagged_existing = any(
            record.get("player_id", record.get("playerId")) in (None, "")
            for record in existing
        )
        if untagged_existing and context_player != player_id:
            raise ValueError("Cannot establish owner of existing history; import cancelled.")
        if context_player and context_player != player_id:
            raise ValueError("Existing convene_context belongs to another playerId; import cancelled.")
        if not context_player and any(existing_player != player_id for existing_player in tagged_players):
            raise ValueError("Existing history belongs to another playerId; import cancelled.")

        existing_keys = {
            self._record_key(record)
            for record in existing
            if self._record_key(record)
        }
        incoming_keys = {
            self._record_key(record)
            for record in incoming
            if self._record_key(record)
        }
        merged = self._sort_records(self._deduplicate([*existing, *incoming]))
        self._preserve_or_assign_local_record_ids(existing, incoming, merged)
        document["schema_version"] = document.get("schema_version", 1)
        document["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        document["pulls"] = merged
        self._write_document(document)
        return merged, len(incoming_keys - existing_keys)

    def ensure_local_record_ids(
        self,
        record_indexes: list[int],
    ) -> list[dict[str, object]]:
        """Persist local UUIDs for selected history rows without changing pull data."""
        if not record_indexes:
            raise ValueError("Select at least one pull.")
        if len(set(record_indexes)) != len(record_indexes):
            raise ValueError("A pull was selected more than once.")

        pulls = self.load()
        for index in record_indexes:
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("Pull indexes must be integers.")
            if index < 0 or index >= len(pulls):
                raise ValueError("A selected pull index is out of range.")

        self._validate_local_record_ids(pulls)
        changed = False
        for index in record_indexes:
            if not pulls[index].get("local_record_id"):
                pulls[index]["local_record_id"] = str(uuid.uuid4())
                changed = True
        if not changed:
            return pulls

        document: dict[str, object] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError("Cannot validate existing history; sync registration cancelled.") from error
            if not isinstance(payload, dict):
                raise ValueError("Existing history has an invalid format; sync registration cancelled.")
            document = payload
        raw_pulls = document.get("pulls")
        if not isinstance(raw_pulls, list):
            raise ValueError("Existing history has no pull list; sync registration cancelled.")
        for index in record_indexes:
            selected_pull = pulls[index]
            selected_key = self._record_key(selected_pull)
            matching_raw_indexes = [
                raw_index
                for raw_index, raw_pull in enumerate(raw_pulls)
                if isinstance(raw_pull, dict)
                and self._record_key(raw_pull) == selected_key
            ]
            if not matching_raw_indexes:
                raise ValueError("Selected pull could not be found in stored history.")
            survivor_index = matching_raw_indexes[-1]
            raw_survivor = raw_pulls[survivor_index]
            if not isinstance(raw_survivor, dict):
                raise ValueError("Selected pull is invalid in stored history.")
            raw_pulls[survivor_index] = {
                **raw_survivor,
                "local_record_id": selected_pull["local_record_id"],
            }
        document.setdefault("schema_version", 1)
        document["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        document["pulls"] = raw_pulls
        self._write_document(document)
        return pulls

    @staticmethod
    def _without_local_record_id(record: dict[str, object]) -> dict[str, object]:
        cleaned = dict(record)
        cleaned.pop("local_record_id", None)
        return cleaned

    @classmethod
    def _preserve_or_assign_local_record_ids(
        cls,
        existing: list[dict[str, object]],
        incoming: list[dict[str, object]],
        merged: list[dict[str, object]],
    ) -> None:
        cls._validate_local_record_ids(existing)
        existing_ids = {
            cls._record_key(record): record["local_record_id"]
            for record in existing
            if cls._record_key(record) and isinstance(record.get("local_record_id"), str)
        }
        existing_keys = {cls._record_key(record) for record in existing}
        incoming_new_keys = {
            cls._record_key(record)
            for record in incoming
            if cls._record_key(record) and cls._record_key(record) not in existing_keys
        }
        for record in merged:
            key = cls._record_key(record)
            existing_id = existing_ids.get(key)
            if existing_id is not None:
                record["local_record_id"] = existing_id
            elif key in incoming_new_keys:
                record["local_record_id"] = str(uuid.uuid4())

    @classmethod
    def _promote_matching_legacy_records(
        cls,
        existing: list[dict[str, object]],
        incoming: list[dict[str, object]],
        player_id: str,
    ) -> list[dict[str, object]]:
        """Enrich a unique matching legacy row only within continuous context."""
        legacy_indexes = [
            index
            for index, record in enumerate(existing)
            if cls._record_player_id(record) is None
        ]
        incoming_indexes = [
            index
            for index, record in enumerate(incoming)
            if cls._record_player_id(record) == player_id
        ]
        matching_legacy_by_incoming = {
            incoming_index: [
                legacy_index
                for legacy_index in legacy_indexes
                if cls._same_pull_occurrence(
                    existing[legacy_index], incoming[incoming_index]
                )
            ]
            for incoming_index in incoming_indexes
        }
        matching_incoming_by_legacy = {
            legacy_index: [
                incoming_index
                for incoming_index in incoming_indexes
                if legacy_index in matching_legacy_by_incoming[incoming_index]
            ]
            for legacy_index in legacy_indexes
        }

        remove_legacy_indexes: set[int] = set()
        for incoming_index, candidates in matching_legacy_by_incoming.items():
            if len(candidates) != 1:
                continue
            legacy_index = candidates[0]
            if len(matching_incoming_by_legacy[legacy_index]) != 1:
                continue
            incoming_record = incoming[incoming_index]
            if any(
                cls._record_player_id(record) not in (None, player_id)
                and cls._same_pull_occurrence(record, incoming_record)
                for record in existing
            ):
                continue

            same_player_indexes = [
                index
                for index, record in enumerate(existing)
                if cls._record_player_id(record) == player_id
                and cls._same_pull_occurrence(record, incoming_record)
            ]
            if same_player_indexes:
                remove_legacy_indexes.add(legacy_index)
                continue

            legacy_record = existing[legacy_index]
            promoted_record = {**legacy_record, **incoming_record}
            if "local_record_id" in legacy_record:
                promoted_record["local_record_id"] = legacy_record["local_record_id"]
            existing[legacy_index] = promoted_record

        return [
            record
            for index, record in enumerate(existing)
            if index not in remove_legacy_indexes
        ]

    @classmethod
    def _same_pull_occurrence(
        cls,
        first: dict[str, object],
        second: dict[str, object],
    ) -> bool:
        """Require an upstream ID or identical raw observation plus pull fields."""
        def value(record: dict[str, object], keys: tuple[str, ...]) -> object | None:
            return next(
                (record[key] for key in keys if record.get(key) not in (None, "")),
                None,
            )

        event_fields = (
            ("timestamp", "time", "date"),
            ("pool", "type", "gacha_type"),
            ("name", "item", "title"),
            ("rarity", "quality", "rank", "qualityLevel"),
        )
        first_values = tuple(value(first, keys) for keys in event_fields)
        second_values = tuple(value(second, keys) for keys in event_fields)
        if any(item is None for item in first_values) or first_values != second_values:
            return False

        first_resource_id = first.get("resourceId")
        second_resource_id = second.get("resourceId")
        if (
            first_resource_id not in (None, "")
            and second_resource_id not in (None, "")
            and first_resource_id != second_resource_id
        ):
            return False

        first_official_id = first.get("official_id")
        second_official_id = second.get("official_id")
        if (
            first_official_id not in (None, "")
            and second_official_id not in (None, "")
            and first_official_id != second_official_id
        ):
            return False
        if (
            first_official_id not in (None, "")
            and first_official_id == second_official_id
        ):
            return True

        first_raw = first.get("raw")
        second_raw = second.get("raw")
        return (
            isinstance(first_raw, dict)
            and bool(first_raw)
            and first_raw == second_raw
        )

    @staticmethod
    def _validate_local_record_ids(records: list[dict[str, object]]) -> None:
        local_ids: list[str] = []
        for record in records:
            value = record.get("local_record_id")
            if value is None:
                continue
            if not isinstance(value, str) or not ConveneStorageManager._is_uuid(value):
                raise ValueError("History contains an invalid local_record_id.")
            local_ids.append(value)
        if len(local_ids) != len(set(local_ids)):
            raise ValueError("History contains duplicate local_record_id values.")

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            return str(uuid.UUID(value)) == value
        except (ValueError, AttributeError):
            return False

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
            base_key = str(explicit_key)
            player_id = ConveneStorageManager._record_player_id(record)
            return f"player:{player_id}|{base_key}" if player_id is not None else base_key
        for key in ("seq_id", "seqId", "pull_id", "id"):
            value = record.get(key)
            if value not in (None, ""):
                base_key = f"id:{value}"
                player_id = ConveneStorageManager._record_player_id(record)
                return f"player:{player_id}|{base_key}" if player_id is not None else base_key
        time_value = record.get("time", record.get("timestamp", record.get("date", "")))
        name = record.get("name", record.get("item", record.get("title", "")))
        pool = record.get("pool", record.get("type", record.get("gacha_type", "")))
        rarity = record.get("rarity", record.get("quality", record.get("rank", "")))
        if all(value not in (None, "") for value in (time_value, pool, name, rarity)):
            base_key = f"fields:{time_value}|{pool}|{name}|{rarity}"
            player_id = ConveneStorageManager._record_player_id(record)
            return f"player:{player_id}|{base_key}" if player_id is not None else base_key
        signature_fields = {
            key: record.get(key)
            for key in ("timestamp", "pool", "name", "rarity", "item", "title")
            if record.get(key) not in (None, "")
        }
        if all(key in signature_fields for key in ("timestamp", "pool", "name", "rarity")):
            payload = json.dumps(signature_fields, ensure_ascii=False, sort_keys=True)
            base_key = f"signature:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
            player_id = ConveneStorageManager._record_player_id(record)
            return f"player:{player_id}|{base_key}" if player_id is not None else base_key
        return ""

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
    def _validate_player_id(player_id: str) -> str:
        if (
            not isinstance(player_id, str)
            or not player_id.strip()
            or not _PLAYER_ID_RE.fullmatch(player_id.strip())
        ):
            raise ValueError("A valid player_id is required for active Convene history.")
        return player_id.strip()

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
