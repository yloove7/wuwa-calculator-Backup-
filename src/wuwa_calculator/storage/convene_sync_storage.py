"""Local-only metadata and outbox for future Convene synchronization."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager
from src.wuwa_calculator.utils.paths import get_user_data_path

CONVENE_SYNC_FILE = get_user_data_path("convene_sync.json")
_SYNC_VERSION = 2
_LEGACY_SYNC_VERSION = 1

SyncState = Literal["local_only", "pending", "synced", "conflict"]
OperationState = Literal["pending", "completed", "conflict"]


class ConveneSyncStorageError(ValueError):
    """Raised when local Convene sync metadata is invalid or cannot be read."""


@dataclass(frozen=True)
class LocalPullSyncMetadata:
    """Sync identifiers linked to one persistent local history row."""

    local_record_id: str
    client_record_id: str
    remote_pull_id: str | None
    sync_state: SyncState


@dataclass(frozen=True)
class OrphanedPullSyncMetadata:
    """Legacy sync metadata that could not be linked without guessing."""

    client_record_id: str
    remote_pull_id: str | None
    sync_state: SyncState
    local_fingerprint: str
    occurrence: int


@dataclass(frozen=True)
class SyncOperation:
    """A persisted upload operation; no network request is performed here."""

    operation_id: str
    operation_type: Literal["upload_pulls"]
    client_record_ids: tuple[str, ...]
    created_at: str
    state: OperationState
    attempt_count: int


@dataclass
class _SyncDocument:
    records: list[LocalPullSyncMetadata]
    orphaned_records: list[OrphanedPullSyncMetadata]
    operations: list[SyncOperation]
    legacy_version: bool = False


class ConveneSyncStorage:
    """Store per-install sync metadata separately from the pull history."""

    def __init__(self, path: Path = CONVENE_SYNC_FILE) -> None:
        self.path = Path(path)

    def metadata_for_history(
        self,
        pulls: list[dict[str, object]],
    ) -> list[LocalPullSyncMetadata | None]:
        """Return metadata by local_record_id without generating identifiers."""
        document = self._read_document()
        if document.legacy_version:
            # Migration needs persisted local IDs; a read must not invent them.
            return [None for _ in pulls]
        metadata_by_local_id = {
            entry.local_record_id: entry for entry in document.records
        }
        result: list[LocalPullSyncMetadata | None] = []
        for pull in pulls:
            local_record_id = pull.get("local_record_id")
            result.append(
                metadata_by_local_id.get(local_record_id)
                if isinstance(local_record_id, str)
                else None
            )
        return result

    def register_records_for_sync(
        self,
        history: ConveneStorageManager,
        record_indexes: list[int],
    ) -> list[LocalPullSyncMetadata]:
        """Persist local IDs and create client IDs for explicitly selected rows."""
        if not record_indexes:
            raise ConveneSyncStorageError("Select at least one pull for synchronization.")
        if len(set(record_indexes)) != len(record_indexes):
            raise ConveneSyncStorageError("A pull was selected more than once.")

        document = self._read_document()
        try:
            pulls = history.ensure_local_record_ids(record_indexes)
        except ValueError as error:
            raise ConveneSyncStorageError(str(error)) from error

        records_changed = False
        if document.legacy_version:
            self._migrate_legacy_records(document)
            records_changed = True

        existing_by_local_id = {
            entry.local_record_id: entry for entry in document.records
        }
        selected: list[LocalPullSyncMetadata] = []
        for index in record_indexes:
            local_record_id = pulls[index].get("local_record_id")
            if not isinstance(local_record_id, str) or not self._is_uuid(local_record_id):
                raise ConveneSyncStorageError("Selected pull has no valid local_record_id.")
            entry = existing_by_local_id.get(local_record_id)
            if entry is None:
                entry = LocalPullSyncMetadata(
                    local_record_id=local_record_id,
                    client_record_id=str(uuid.uuid4()),
                    remote_pull_id=None,
                    sync_state="local_only",
                )
                document.records.append(entry)
                existing_by_local_id[local_record_id] = entry
                records_changed = True
            selected.append(entry)

        if records_changed:
            self._write_document(document)
        return selected

    def queue_upload(self, client_record_ids: list[str]) -> SyncOperation:
        """Persist an upload operation and move selected records to pending."""
        if not client_record_ids:
            raise ConveneSyncStorageError("An upload operation must contain pulls.")
        if len(set(client_record_ids)) != len(client_record_ids):
            raise ConveneSyncStorageError("An upload operation contains duplicate pull IDs.")

        document = self._read_document()
        records_by_id = {entry.client_record_id: entry for entry in document.records}
        selected: list[LocalPullSyncMetadata] = []
        for client_record_id in client_record_ids:
            entry = records_by_id.get(client_record_id)
            if entry is None:
                raise ConveneSyncStorageError("Unknown or orphaned client_record_id.")
            selected.append(entry)

        existing_operations = [
            operation
            for operation in document.operations
            if operation.state == "pending"
            and set(operation.client_record_ids).intersection(client_record_ids)
        ]
        if existing_operations:
            if (
                len(existing_operations) == 1
                and existing_operations[0].client_record_ids == tuple(client_record_ids)
                and all(entry.sync_state == "pending" for entry in selected)
            ):
                return existing_operations[0]
            raise ConveneSyncStorageError(
                "Selected pulls already belong to another pending operation."
            )

        if any(entry.sync_state != "local_only" for entry in selected):
            raise ConveneSyncStorageError(
                "Only local_only pulls can start a new upload operation."
            )

        selected_ids = set(client_record_ids)
        document.records = [
            LocalPullSyncMetadata(
                local_record_id=entry.local_record_id,
                client_record_id=entry.client_record_id,
                remote_pull_id=entry.remote_pull_id,
                sync_state="pending",
            )
            if entry.client_record_id in selected_ids
            else entry
            for entry in document.records
        ]
        operation = SyncOperation(
            operation_id=str(uuid.uuid4()),
            operation_type="upload_pulls",
            client_record_ids=tuple(client_record_ids),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            state="pending",
            attempt_count=0,
        )
        document.operations.append(operation)
        self._write_document(document)
        return operation

    def record_attempt(self, operation_id: str) -> SyncOperation:
        """Persist an attempted send count without performing network I/O."""
        document = self._read_document()
        for index, operation in enumerate(document.operations):
            if operation.operation_id != operation_id:
                continue
            if operation.state != "pending":
                raise ConveneSyncStorageError("Only pending operations can be retried.")
            updated = SyncOperation(
                operation_id=operation.operation_id,
                operation_type=operation.operation_type,
                client_record_ids=operation.client_record_ids,
                created_at=operation.created_at,
                state=operation.state,
                attempt_count=operation.attempt_count + 1,
            )
            document.operations[index] = updated
            self._write_document(document)
            return updated
        raise ConveneSyncStorageError("Unknown operation_id.")

    def associate_remote_pull_id(
        self,
        client_record_id: str,
        remote_pull_id: str,
    ) -> LocalPullSyncMetadata:
        """Persist an opaque server-assigned ID for one local pull."""
        normalized_remote_id = remote_pull_id.strip()
        if not normalized_remote_id:
            raise ConveneSyncStorageError("remote_pull_id must not be empty.")

        document = self._read_document()
        target_index = next(
            (
                index
                for index, entry in enumerate(document.records)
                if entry.client_record_id == client_record_id
            ),
            None,
        )
        if target_index is None:
            raise ConveneSyncStorageError("Unknown or orphaned client_record_id.")

        target = document.records[target_index]
        if target.sync_state == "conflict":
            raise ConveneSyncStorageError("Conflicted pulls require explicit resolution.")
        if target.sync_state not in {"pending", "synced"}:
            raise ConveneSyncStorageError(
                "A remote_pull_id can only be associated with a pending pull."
            )
        if target.remote_pull_id not in (None, normalized_remote_id):
            raise ConveneSyncStorageError("A different remote_pull_id is already assigned.")
        if any(
            entry.client_record_id != client_record_id
            and entry.remote_pull_id == normalized_remote_id
            for entry in (*document.records, *document.orphaned_records)
        ):
            raise ConveneSyncStorageError("remote_pull_id is already assigned to another pull.")

        updated = LocalPullSyncMetadata(
            local_record_id=target.local_record_id,
            client_record_id=target.client_record_id,
            remote_pull_id=normalized_remote_id,
            sync_state="synced",
        )
        document.records[target_index] = updated
        document.operations = [
            self._operation_with_state(operation, document)
            for operation in document.operations
        ]
        self._write_document(document)
        return updated

    def mark_conflict(self, client_record_id: str) -> LocalPullSyncMetadata:
        """Mark a pull conflicted without deleting or resolving it."""
        document = self._read_document()
        target_index = next(
            (
                index
                for index, entry in enumerate(document.records)
                if entry.client_record_id == client_record_id
            ),
            None,
        )
        if target_index is None:
            raise ConveneSyncStorageError("Unknown or orphaned client_record_id.")
        target = document.records[target_index]
        updated = LocalPullSyncMetadata(
            local_record_id=target.local_record_id,
            client_record_id=target.client_record_id,
            remote_pull_id=target.remote_pull_id,
            sync_state="conflict",
        )
        document.records[target_index] = updated
        document.operations = [
            self._operation_with_state(operation, document)
            for operation in document.operations
        ]
        self._write_document(document)
        return updated

    def load_operations(self) -> list[SyncOperation]:
        """Load persisted operations for a future sync coordinator."""
        return self._read_document().operations

    def _migrate_legacy_records(
        self,
        document: _SyncDocument,
    ) -> None:
        orphan_ids = {item.client_record_id for item in document.orphaned_records}
        document.operations = [
            SyncOperation(
                operation_id=operation.operation_id,
                operation_type=operation.operation_type,
                client_record_ids=operation.client_record_ids,
                created_at=operation.created_at,
                state=(
                    "conflict"
                    if operation.state == "pending"
                    and any(record_id in orphan_ids for record_id in operation.client_record_ids)
                    else operation.state
                ),
                attempt_count=operation.attempt_count,
            )
            for operation in document.operations
        ]
        document.legacy_version = False

    def _read_document(self) -> _SyncDocument:
        if not self.path.exists():
            return _SyncDocument(records=[], orphaned_records=[], operations=[])
        try:
            payload: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ConveneSyncStorageError("Cannot read Convene sync metadata.") from error
        if not isinstance(payload, dict):
            raise ConveneSyncStorageError("Convene sync metadata must be a JSON object.")
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConveneSyncStorageError("Unsupported Convene sync metadata version.")
        raw_records = payload.get("records")
        raw_operations = payload.get("operations")
        if not isinstance(raw_records, list) or not isinstance(raw_operations, list):
            raise ConveneSyncStorageError("Convene sync metadata has invalid collections.")

        if version == _LEGACY_SYNC_VERSION:
            orphaned_records = [self._parse_orphaned_record(item) for item in raw_records]
            operations = [self._parse_operation(item) for item in raw_operations]
            self._validate_document([], orphaned_records, operations)
            return _SyncDocument(
                records=[],
                orphaned_records=orphaned_records,
                operations=operations,
                legacy_version=True,
            )
        if version != _SYNC_VERSION:
            raise ConveneSyncStorageError("Unsupported Convene sync metadata version.")
        raw_orphans = payload.get("orphaned_records")
        if not isinstance(raw_orphans, list):
            raise ConveneSyncStorageError("Convene sync metadata has invalid orphaned records.")
        records = [self._parse_record(item) for item in raw_records]
        orphaned_records = [self._parse_orphaned_record(item) for item in raw_orphans]
        operations = [self._parse_operation(item) for item in raw_operations]
        self._validate_document(records, orphaned_records, operations)
        return _SyncDocument(records, orphaned_records, operations)

    def _write_document(self, document: _SyncDocument) -> None:
        content = json.dumps(
            {
                "version": _SYNC_VERSION,
                "records": [self._record_payload(entry) for entry in document.records],
                "orphaned_records": [
                    self._orphan_payload(entry) for entry in document.orphaned_records
                ],
                "operations": [
                    self._operation_payload(operation)
                    for operation in document.operations
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    @staticmethod
    def _operation_with_state(
        operation: SyncOperation,
        document: _SyncDocument,
    ) -> SyncOperation:
        orphaned_ids = {
            entry.client_record_id for entry in document.orphaned_records
        }
        if any(record_id in orphaned_ids for record_id in operation.client_record_ids):
            state: OperationState = (
                "conflict" if operation.state == "pending" else operation.state
            )
            return SyncOperation(
                operation_id=operation.operation_id,
                operation_type=operation.operation_type,
                client_record_ids=operation.client_record_ids,
                created_at=operation.created_at,
                state=state,
                attempt_count=operation.attempt_count,
            )
        records_by_id = {
            entry.client_record_id: entry.sync_state for entry in document.records
        }
        states = [records_by_id[record_id] for record_id in operation.client_record_ids]
        if "conflict" in states:
            state: OperationState = "conflict"
        elif all(item == "synced" for item in states):
            state = "completed"
        else:
            state = "pending"
        return SyncOperation(
            operation_id=operation.operation_id,
            operation_type=operation.operation_type,
            client_record_ids=operation.client_record_ids,
            created_at=operation.created_at,
            state=state,
            attempt_count=operation.attempt_count,
        )

    @staticmethod
    def _parse_record(value: object) -> LocalPullSyncMetadata:
        if not isinstance(value, dict):
            raise ConveneSyncStorageError("Invalid sync record metadata entry.")
        local_record_id = value.get("local_record_id")
        client_record_id = value.get("client_record_id")
        remote_pull_id = value.get("remote_pull_id")
        state = value.get("sync_state")
        if not isinstance(local_record_id, str) or not ConveneSyncStorage._is_uuid(local_record_id):
            raise ConveneSyncStorageError("Invalid local_record_id in sync metadata.")
        client_record_id, remote_pull_id, state = ConveneSyncStorage._validate_record_values(
            client_record_id, remote_pull_id, state
        )
        return LocalPullSyncMetadata(
            local_record_id=local_record_id,
            client_record_id=client_record_id,
            remote_pull_id=remote_pull_id,
            sync_state=state,
        )

    @staticmethod
    def _parse_orphaned_record(value: object) -> OrphanedPullSyncMetadata:
        if not isinstance(value, dict):
            raise ConveneSyncStorageError("Invalid orphaned sync metadata entry.")
        client_record_id = value.get("client_record_id")
        remote_pull_id = value.get("remote_pull_id")
        state = value.get("sync_state")
        fingerprint = value.get("local_fingerprint")
        occurrence = value.get("occurrence")
        client_record_id, remote_pull_id, state = ConveneSyncStorage._validate_record_values(
            client_record_id, remote_pull_id, state
        )
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in fingerprint
        ):
            raise ConveneSyncStorageError("Invalid legacy local locator in sync metadata.")
        if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
            raise ConveneSyncStorageError("Invalid legacy local locator occurrence.")
        return OrphanedPullSyncMetadata(
            client_record_id=client_record_id,
            remote_pull_id=remote_pull_id,
            sync_state=state,
            local_fingerprint=fingerprint,
            occurrence=occurrence,
        )

    @staticmethod
    def _validate_record_values(
        client_record_id: object,
        remote_pull_id: object,
        state: object,
    ) -> tuple[str, str | None, SyncState]:
        if not isinstance(client_record_id, str) or not ConveneSyncStorage._is_uuid(client_record_id):
            raise ConveneSyncStorageError("Invalid client_record_id in sync metadata.")
        if remote_pull_id is not None and (
            not isinstance(remote_pull_id, str) or not remote_pull_id.strip()
        ):
            raise ConveneSyncStorageError("Invalid remote_pull_id in sync metadata.")
        if state == "local_only":
            normalized_state: SyncState = "local_only"
        elif state == "pending":
            normalized_state = "pending"
        elif state == "synced":
            normalized_state = "synced"
        elif state == "conflict":
            normalized_state = "conflict"
        else:
            raise ConveneSyncStorageError("Invalid sync_state in sync metadata.")
        if normalized_state == "synced" and remote_pull_id is None:
            raise ConveneSyncStorageError("Synced metadata must contain remote_pull_id.")
        if normalized_state == "local_only" and remote_pull_id is not None:
            raise ConveneSyncStorageError("Local-only metadata cannot contain remote_pull_id.")
        return client_record_id, remote_pull_id, normalized_state

    @staticmethod
    def _parse_operation(value: object) -> SyncOperation:
        if not isinstance(value, dict):
            raise ConveneSyncStorageError("Invalid sync operation entry.")
        operation_id = value.get("operation_id")
        operation_type = value.get("operation_type")
        raw_record_ids = value.get("client_record_ids")
        created_at = value.get("created_at")
        state = value.get("state")
        attempt_count = value.get("attempt_count")
        if not isinstance(operation_id, str) or not ConveneSyncStorage._is_uuid(operation_id):
            raise ConveneSyncStorageError("Invalid operation_id in sync metadata.")
        if operation_type != "upload_pulls":
            raise ConveneSyncStorageError("Unsupported sync operation type.")
        if not isinstance(raw_record_ids, list) or not raw_record_ids:
            raise ConveneSyncStorageError("Sync operation must contain pull IDs.")
        if any(
            not isinstance(record_id, str) or not ConveneSyncStorage._is_uuid(record_id)
            for record_id in raw_record_ids
        ):
            raise ConveneSyncStorageError("Invalid client_record_id in sync operation.")
        if not isinstance(created_at, str) or not created_at:
            raise ConveneSyncStorageError("Invalid operation timestamp.")
        if state == "pending":
            operation_state: OperationState = "pending"
        elif state == "completed":
            operation_state = "completed"
        elif state == "conflict":
            operation_state = "conflict"
        else:
            raise ConveneSyncStorageError("Invalid operation state.")
        if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 0:
            raise ConveneSyncStorageError("Invalid operation attempt_count.")
        record_ids = tuple(raw_record_ids)
        if len(set(record_ids)) != len(record_ids):
            raise ConveneSyncStorageError("Duplicate client_record_id in sync operation.")
        return SyncOperation(
            operation_id=operation_id,
            operation_type="upload_pulls",
            client_record_ids=record_ids,
            created_at=created_at,
            state=operation_state,
            attempt_count=attempt_count,
        )

    @staticmethod
    def _validate_document(
        records: list[LocalPullSyncMetadata],
        orphaned_records: list[OrphanedPullSyncMetadata],
        operations: list[SyncOperation],
    ) -> None:
        client_ids = [
            entry.client_record_id for entry in (*records, *orphaned_records)
        ]
        local_ids = [entry.local_record_id for entry in records]
        remote_ids = [
            entry.remote_pull_id for entry in (*records, *orphaned_records)
            if entry.remote_pull_id is not None
        ]
        operation_ids = [operation.operation_id for operation in operations]
        if len(client_ids) != len(set(client_ids)):
            raise ConveneSyncStorageError("Duplicate client_record_id in sync metadata.")
        if len(local_ids) != len(set(local_ids)):
            raise ConveneSyncStorageError("Duplicate local_record_id in sync metadata.")
        if len(remote_ids) != len(set(remote_ids)):
            raise ConveneSyncStorageError("Duplicate remote_pull_id in sync metadata.")
        if len(operation_ids) != len(set(operation_ids)):
            raise ConveneSyncStorageError("Duplicate operation_id in sync metadata.")
        known_ids = set(client_ids)
        for operation in operations:
            if any(record_id not in known_ids for record_id in operation.client_record_ids):
                raise ConveneSyncStorageError("Sync operation references an unknown pull.")

    @staticmethod
    def _record_payload(entry: LocalPullSyncMetadata) -> dict[str, object]:
        return {
            "local_record_id": entry.local_record_id,
            "client_record_id": entry.client_record_id,
            "remote_pull_id": entry.remote_pull_id,
            "sync_state": entry.sync_state,
        }

    @staticmethod
    def _orphan_payload(entry: OrphanedPullSyncMetadata) -> dict[str, object]:
        return {
            "client_record_id": entry.client_record_id,
            "remote_pull_id": entry.remote_pull_id,
            "sync_state": entry.sync_state,
            "local_fingerprint": entry.local_fingerprint,
            "occurrence": entry.occurrence,
        }

    @staticmethod
    def _operation_payload(operation: SyncOperation) -> dict[str, object]:
        return {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "client_record_ids": list(operation.client_record_ids),
            "created_at": operation.created_at,
            "state": operation.state,
            "attempt_count": operation.attempt_count,
        }

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            return str(uuid.UUID(value)) == value
        except (ValueError, AttributeError):
            return False
