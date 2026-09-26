import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.wuwa_calculator.domain.pity import calculate_pity_state
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager
from src.wuwa_calculator.storage.convene_sync_storage import (
    ConveneSyncStorage,
    ConveneSyncStorageError,
)


class ConveneSyncStorageTests(unittest.TestCase):
    def _pull(self, name: str = "Test character", **extra: object) -> dict[str, object]:
        return {
            "timestamp": "2026-09-01T10:00:00-05:00",
            "pool": "resonator",
            "name": name,
            "rarity": 5,
            **extra,
        }

    @staticmethod
    def _legacy_fingerprint(pull: dict[str, object]) -> str:
        portable = ConveneStorageManager._to_tethys_pull(pull, 0)
        encoded = json.dumps(
            portable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def test_ids_are_created_only_for_selected_pulls_and_remain_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "convene_history.json")
            history.merge([self._pull("First"), self._pull("Second")])
            original_bytes = history.path.read_bytes()
            original_pity = calculate_pity_state(history.load())
            storage = ConveneSyncStorage(root / "convene_sync.json")
            pulls = history.load()

            self.assertEqual(storage.metadata_for_history(pulls), [None, None])
            selected = storage.register_records_for_sync(history, [0])
            first = selected[0]

            self.assertEqual(str(uuid.UUID(first.client_record_id)), first.client_record_id)
            self.assertIsNone(first.remote_pull_id)
            self.assertEqual(first.sync_state, "local_only")
            self.assertEqual(storage.metadata_for_history(pulls), [first, None])
            self.assertEqual(history.path.read_bytes(), original_bytes)
            self.assertEqual(calculate_pity_state(history.load()), original_pity)

            reloaded = ConveneSyncStorage(root / "convene_sync.json")
            self.assertEqual(reloaded.register_records_for_sync(history, [0]), [first])
            self.assertEqual(reloaded.metadata_for_history(pulls), [first, None])

    def test_duplicate_local_payloads_receive_distinct_ids_without_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            first = self._pull("Same")
            second = {**self._pull("Same"), "seq_id": "separate-local-row"}
            history.merge([first, second])
            pulls = history.load()
            storage = ConveneSyncStorage(root / "sync.json")

            metadata = storage.register_records_for_sync(history, [0, 1])

            self.assertNotEqual(metadata[0].client_record_id, metadata[1].client_record_id)
            self.assertEqual(
                [item.sync_state for item in metadata],
                ["local_only", "local_only"],
            )
            self.assertEqual(storage.metadata_for_history(pulls), metadata)
            self.assertEqual([pull["name"] for pull in history.load()], ["Same", "Same"])

    def test_persistent_ids_follow_identical_events_through_reorder_insert_remove_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([
                self._pull("Same", seq_id="event-A"),
                self._pull("Same", seq_id="event-B"),
            ])
            sync = ConveneSyncStorage(root / "sync.json")
            initial_pulls = history.load()
            initial_meta = sync.register_records_for_sync(history, [0, 1])
            expected = {
                str(pull["seq_id"]): (str(pull["local_record_id"]), meta.client_record_id)
                for pull, meta in zip(initial_pulls, initial_meta, strict=True)
            }
            self.assertNotEqual(expected["event-A"][0], expected["event-B"][0])
            self.assertNotEqual(expected["event-A"][1], expected["event-B"][1])

            operation = sync.queue_upload([item.client_record_id for item in initial_meta])
            remote = sync.associate_remote_pull_id(
                expected["event-A"][1], "remote-event-A"
            )
            self.assertEqual(remote.local_record_id, expected["event-A"][0])

            document = json.loads(history.path.read_text(encoding="utf-8"))
            document["pulls"].reverse()
            history.path.write_text(json.dumps(document), encoding="utf-8")
            reordered = ConveneStorageManager(history.path).load()
            reordered_metadata = sync.metadata_for_history(reordered)
            observed = {
                str(pull["seq_id"]): (
                    str(pull["local_record_id"]),
                    metadata.client_record_id if metadata else "",
                    metadata.remote_pull_id if metadata else None,
                )
                for pull, metadata in zip(reordered, reordered_metadata, strict=True)
            }
            self.assertEqual(observed["event-A"], (*expected["event-A"], "remote-event-A"))
            self.assertEqual(observed["event-B"], (*expected["event-B"], None))

            history.merge([self._pull("Same", seq_id="event-C")])
            inserted = history.load()
            inserted_by_event = {str(pull["seq_id"]): pull for pull in inserted}
            inserted_document = json.loads(history.path.read_text(encoding="utf-8"))
            inserted_document["pulls"] = [
                inserted_by_event[event]
                for event in ("event-A", "event-C", "event-B")
            ]
            history.path.write_text(json.dumps(inserted_document), encoding="utf-8")
            after_insert = ConveneStorageManager(history.path).load()
            self.assertEqual(
                [pull["seq_id"] for pull in after_insert],
                ["event-A", "event-C", "event-B"],
            )
            ids_after_insert = {
                str(pull["seq_id"]): str(pull["local_record_id"])
                for pull in after_insert
            }
            self.assertEqual(ids_after_insert["event-A"], expected["event-A"][0])
            self.assertEqual(ids_after_insert["event-B"], expected["event-B"][0])
            self.assertNotIn(ids_after_insert["event-C"], {
                expected["event-A"][0], expected["event-B"][0]
            })

            reordered_document = json.loads(history.path.read_text(encoding="utf-8"))
            reordered_by_event = {str(pull["seq_id"]): pull for pull in after_insert}
            reordered_document["pulls"] = [
                reordered_by_event[event]
                for event in ("event-C", "event-A", "event-B")
            ]
            history.path.write_text(json.dumps(reordered_document), encoding="utf-8")
            explicitly_reordered = ConveneStorageManager(history.path).load()
            self.assertEqual(
                [pull["seq_id"] for pull in explicitly_reordered],
                ["event-C", "event-A", "event-B"],
            )
            for pull in explicitly_reordered:
                event = str(pull["seq_id"])
                if event in expected:
                    self.assertEqual(
                        pull["local_record_id"],
                        expected[event][0],
                    )
                else:
                    self.assertEqual(
                        pull["local_record_id"],
                        ids_after_insert[event],
                    )

            current_document = json.loads(history.path.read_text(encoding="utf-8"))
            current_document["pulls"] = [
                pull for pull in explicitly_reordered if pull.get("seq_id") != "event-B"
            ]
            history.path.write_text(json.dumps(current_document), encoding="utf-8")
            reloaded = ConveneStorageManager(history.path).load()
            after_remove = sync.metadata_for_history(reloaded)
            final_by_event = {
                str(pull["seq_id"]): (str(pull["local_record_id"]), metadata)
                for pull, metadata in zip(reloaded, after_remove, strict=True)
            }
            self.assertEqual(final_by_event["event-A"][0], expected["event-A"][0])
            final_metadata = final_by_event["event-A"][1]
            if final_metadata is None:
                self.fail("Metadata disappeared after history mutation.")
            self.assertEqual(
                final_metadata.client_record_id,
                expected["event-A"][1],
            )
            self.assertEqual(final_by_event["event-C"][1], None)
            self.assertEqual(sync.load_operations()[0].operation_id, operation.operation_id)

    def test_new_merge_preserves_existing_local_ids_and_assigns_new_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = ConveneStorageManager(Path(directory) / "history.json")
            original = history.merge([self._pull("Existing")])[0]

            merged = history.merge([self._pull("Existing"), self._pull("New")])
            by_name = {str(pull["name"]): pull for pull in merged}

            self.assertEqual(
                by_name["Existing"]["local_record_id"],
                original["local_record_id"],
            )
            self.assertTrue(ConveneSyncStorage._is_uuid(str(by_name["New"]["local_record_id"])))

    def test_legacy_history_gets_local_ids_only_for_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history_path = root / "history.json"
            history_path.write_text(
                json.dumps({"pulls": [self._pull("First"), self._pull("Second")]}),
                encoding="utf-8",
            )
            history = ConveneStorageManager(history_path)
            sync = ConveneSyncStorage(root / "sync.json")

            selected = sync.register_records_for_sync(history, [0])[0]
            pulls = history.load()

            self.assertEqual(pulls[0]["local_record_id"], selected.local_record_id)
            self.assertNotIn("local_record_id", pulls[1])

    def test_assigning_legacy_id_preserves_raw_duplicate_history_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "pulls": [
                    self._pull("Duplicate", raw={"source": "first"}),
                    self._pull("Duplicate", raw={"source": "survivor"}),
                ],
            }), encoding="utf-8")
            history = ConveneStorageManager(path)
            sync = ConveneSyncStorage(Path(directory) / "sync.json")

            selected = sync.register_records_for_sync(history, [0])[0]

            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(stored["pulls"]), 2)
            self.assertNotIn("local_record_id", stored["pulls"][0])
            self.assertEqual(
                stored["pulls"][1]["local_record_id"],
                selected.local_record_id,
            )
            self.assertEqual(history.load()[0]["local_record_id"], selected.local_record_id)

    def test_external_local_record_id_is_not_imported_or_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = ConveneStorageManager(Path(directory) / "history.json")
            foreign_id = str(uuid.uuid4())

            imported = history.merge([self._pull("Imported", local_record_id=foreign_id)])

            self.assertNotEqual(imported[0]["local_record_id"], foreign_id)
            self.assertTrue(
                ConveneSyncStorage._is_uuid(str(imported[0]["local_record_id"]))
            )

    def test_legacy_unique_metadata_migrates_to_persistent_local_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("Unique")])
            pull = history.load()[0]
            client_id = str(uuid.uuid4())
            operation_id = str(uuid.uuid4())
            legacy = {
                "version": 1,
                "records": [{
                    "client_record_id": client_id,
                    "remote_pull_id": None,
                    "sync_state": "local_only",
                    "local_fingerprint": self._legacy_fingerprint(pull),
                    "occurrence": 0,
                }],
                "operations": [],
            }
            path = root / "sync.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            sync = ConveneSyncStorage(path)

            migrated = sync.register_records_for_sync(history, [0])[0]

            self.assertNotEqual(migrated.client_record_id, client_id)
            self.assertEqual(migrated.local_record_id, pull["local_record_id"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["orphaned_records"][0]["client_record_id"], client_id)

    def test_legacy_ambiguous_metadata_is_preserved_as_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([
                self._pull("Same", seq_id="event-A"),
                self._pull("Same", seq_id="event-B"),
            ])
            pulls = history.load()
            client_id = str(uuid.uuid4())
            operation_id = str(uuid.uuid4())
            legacy = {
                "version": 1,
                "records": [{
                    "client_record_id": client_id,
                    "remote_pull_id": None,
                    "sync_state": "pending",
                    "local_fingerprint": self._legacy_fingerprint(pulls[0]),
                    "occurrence": 0,
                }],
                "operations": [{
                    "operation_id": operation_id,
                    "operation_type": "upload_pulls",
                    "client_record_ids": [client_id],
                    "created_at": "2026-09-01T00:00:00+00:00",
                    "state": "pending",
                    "attempt_count": 2,
                }],
            }
            path = root / "sync.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            sync = ConveneSyncStorage(path)

            newly_linked = sync.register_records_for_sync(history, [0])[0]

            self.assertNotEqual(newly_linked.client_record_id, client_id)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["orphaned_records"][0]["client_record_id"], client_id)
            self.assertEqual(saved["operations"][0]["operation_id"], operation_id)
            self.assertEqual(saved["operations"][0]["state"], "conflict")
            self.assertEqual(saved["operations"][0]["attempt_count"], 2)
            migrated_metadata = sync.metadata_for_history(history.load())[0]
            if migrated_metadata is None:
                self.fail("New metadata was not linked to the selected pull.")
            self.assertEqual(
                migrated_metadata.client_record_id,
                newly_linked.client_record_id,
            )
            with self.assertRaisesRegex(ConveneSyncStorageError, "orphaned"):
                sync.queue_upload([client_id])

    def test_legacy_unique_metadata_migrates_even_if_its_row_is_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("Selected"), self._pull("Legacy")])
            pulls = history.load()
            legacy_client_id = str(uuid.uuid4())
            path = root / "sync.json"
            path.write_text(json.dumps({
                "version": 1,
                "records": [{
                    "client_record_id": legacy_client_id,
                    "remote_pull_id": None,
                    "sync_state": "local_only",
                    "local_fingerprint": self._legacy_fingerprint(pulls[1]),
                    "occurrence": 0,
                }],
                "operations": [],
            }), encoding="utf-8")
            sync = ConveneSyncStorage(path)

            selected = sync.register_records_for_sync(history, [0])[0]
            current = sync.metadata_for_history(history.load())

            self.assertEqual(selected.local_record_id, history.load()[0]["local_record_id"])
            self.assertNotEqual(current[1].client_record_id if current[1] else None, legacy_client_id)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["orphaned_records"][0]["client_record_id"], legacy_client_id)
            self.assertIsNone(current[1])
            self.assertEqual(
                history.load()[1]["local_record_id"],
                pulls[1]["local_record_id"],
            )

    def test_legacy_metadata_does_not_attach_to_remaining_duplicate_after_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("Same", seq_id="removed-event")])
            removed_pull = history.load()[0]
            legacy_client_id = str(uuid.uuid4())
            path = root / "sync.json"
            path.write_text(json.dumps({
                "version": 1,
                "records": [{
                    "client_record_id": legacy_client_id,
                    "remote_pull_id": None,
                    "sync_state": "local_only",
                    "local_fingerprint": self._legacy_fingerprint(removed_pull),
                    "occurrence": 0,
                }],
                "operations": [],
            }), encoding="utf-8")

            # The row currently matches the old portable fingerprint, but the
            # old duplicate group may have contained a different first event.
            history.merge([self._pull("Same", seq_id="remaining-event")])
            remaining = history.load()[0]
            storage = ConveneSyncStorage(path)
            metadata = storage.register_records_for_sync(history, [0])[0]

            self.assertNotEqual(metadata.client_record_id, legacy_client_id)
            self.assertEqual(metadata.local_record_id, remaining["local_record_id"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["orphaned_records"][0]["client_record_id"],
                legacy_client_id,
            )

    def test_tethys_import_creates_local_id_but_export_never_includes_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(json.dumps({
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [{
                    "timestamp": "2026-09-01T10:00:00-05:00",
                    "pool": "resonator",
                    "name": "Imported",
                    "rarity": 5,
                }],
            }), encoding="utf-8")
            history = ConveneStorageManager(root / "history.json")

            history.import_tethys_history(source)
            pull = history.load()[0]
            export_path = root / "export.json"
            exported = history.export_tethys_history(export_path)

            self.assertTrue(ConveneSyncStorage._is_uuid(str(pull["local_record_id"])))
            exported_pulls = exported.get("pulls")
            if not isinstance(exported_pulls, list) or not exported_pulls:
                self.fail("Tethys export did not contain the expected pull.")
            first_exported_pull = exported_pulls[0]
            if not isinstance(first_exported_pull, dict):
                self.fail("Tethys export pull was not an object.")
            self.assertEqual(
                set(first_exported_pull),
                {"cardPoolType", "time", "name", "qualityLevel"},
            )
            self.assertNotIn("local_record_id", export_path.read_text(encoding="utf-8"))

    def test_registered_id_is_not_recreated_if_its_history_row_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("One"), self._pull("Two")])
            pulls = history.load()
            storage = ConveneSyncStorage(root / "sync.json")
            original = storage.register_records_for_sync(history, [0])[0]

            history.path.write_text(json.dumps({"pulls": [pulls[0]]}), encoding="utf-8")

            self.assertEqual(storage.metadata_for_history(history.load()), [original])

    def test_remote_id_cannot_be_associated_before_upload_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = ConveneStorageManager(Path(directory) / "history.json")
            history.merge([self._pull()])
            storage = ConveneSyncStorage(Path(directory) / "sync.json")
            metadata = storage.register_records_for_sync(history, [0])[0]

            with self.assertRaisesRegex(ConveneSyncStorageError, "pending pull"):
                storage.associate_remote_pull_id(metadata.client_record_id, "remote-1")

            self.assertEqual(
                storage.metadata_for_history(history.load())[0],
                metadata,
            )

    def test_upload_operation_and_retry_keep_the_same_operation_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("One"), self._pull("Two")])
            storage = ConveneSyncStorage(root / "sync.json")
            metadata = storage.register_records_for_sync(history, [0, 1])
            pulls = history.load()
            client_ids = [entry.client_record_id for entry in metadata]

            operation = storage.queue_upload(client_ids)
            retried = storage.record_attempt(operation.operation_id)
            repeated = ConveneSyncStorage(root / "sync.json").queue_upload(client_ids)

            self.assertEqual(str(uuid.UUID(operation.operation_id)), operation.operation_id)
            self.assertEqual(operation.operation_type, "upload_pulls")
            self.assertEqual(operation.state, "pending")
            self.assertEqual(operation.attempt_count, 0)
            self.assertEqual(retried.operation_id, operation.operation_id)
            self.assertEqual(retried.attempt_count, 1)
            self.assertEqual(repeated.operation_id, operation.operation_id)
            self.assertEqual(repeated.client_record_ids, tuple(client_ids))
            self.assertEqual(
                [entry.sync_state for entry in storage.metadata_for_history(pulls) if entry],
                ["pending", "pending"],
            )
            self.assertEqual(len(storage.load_operations()), 1)

    def test_remote_ids_are_never_generated_and_are_associated_per_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull("One"), self._pull("Two")])
            pulls = history.load()
            storage = ConveneSyncStorage(root / "sync.json")
            metadata = storage.register_records_for_sync(history, [0, 1])
            operation = storage.queue_upload([item.client_record_id for item in metadata])

            first_synced = storage.associate_remote_pull_id(
                metadata[0].client_record_id,
                "remote-opaque-1",
            )
            current = storage.metadata_for_history(pulls)

            self.assertEqual(first_synced.sync_state, "synced")
            self.assertEqual(first_synced.remote_pull_id, "remote-opaque-1")
            self.assertIsNone(current[1].remote_pull_id if current[1] else None)
            self.assertEqual(current[1].sync_state if current[1] else None, "pending")
            self.assertEqual(storage.load_operations()[0].state, "pending")

            storage.associate_remote_pull_id(metadata[1].client_record_id, "remote-opaque-2")
            completed = storage.load_operations()[0]
            self.assertEqual(completed.operation_id, operation.operation_id)
            self.assertEqual(completed.state, "completed")

    def test_conflict_is_persisted_without_deleting_the_pull(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull()])
            before = history.path.read_bytes()
            pull = history.load()[0]
            storage = ConveneSyncStorage(root / "sync.json")
            metadata = storage.register_records_for_sync(history, [0])[0]
            storage.queue_upload([metadata.client_record_id])

            conflicted = storage.mark_conflict(metadata.client_record_id)

            self.assertEqual(conflicted.sync_state, "conflict")
            self.assertIsNone(conflicted.remote_pull_id)
            self.assertEqual(storage.load_operations()[0].state, "conflict")
            self.assertEqual(history.path.read_bytes(), before)
            self.assertEqual(history.load(), [pull])

    def test_sync_metadata_isolated_from_history_and_portable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge_active_player_with_metadata(
                [self._pull(raw={"private": "local-only"})], "504413756"
            )
            pulls = history.load()
            sync = ConveneSyncStorage(root / "sync.json")

            metadata = sync.register_records_for_sync(history, [0])[0]
            sync.queue_upload([metadata.client_record_id])
            history.save_context({
                "player_id": "504413756",
                "record_id": "record",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
                "card_pool_type": 1,
            })
            history_bytes = history.path.read_bytes()
            export_path = root / "portable.json"
            exported = history.export_tethys_history(export_path)
            sync_after_export = sync.metadata_for_history(history.load())
            portable = json.loads(export_path.read_text(encoding="utf-8"))
            sync_payload = json.loads(sync.path.read_text(encoding="utf-8"))
            reloaded_metadata = sync_after_export[0]
            self.assertIsNotNone(reloaded_metadata)
            self.assertEqual(set(portable), {"date", "playerId", "pulls"})
            self.assertEqual(
                set(portable["pulls"][0]),
                {"cardPoolType", "time", "name", "qualityLevel"},
            )
            self.assertEqual(exported, portable)
            self.assertNotIn("client_record_id", json.dumps(portable))
            self.assertNotIn("remote_pull_id", json.dumps(portable))
            self.assertNotIn("operation_id", json.dumps(portable))
            self.assertNotIn("private", json.dumps(sync_payload))
            if reloaded_metadata is None:
                self.fail("Sync metadata disappeared after portable export.")
            self.assertEqual(reloaded_metadata.client_record_id, metadata.client_record_id)
            self.assertEqual(history.path.read_bytes(), history_bytes)

    def test_atomic_write_failure_preserves_existing_sync_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = ConveneStorageManager(root / "history.json")
            history.merge([self._pull()])
            pulls = history.load()
            path = root / "sync.json"
            storage = ConveneSyncStorage(path)
            storage.register_records_for_sync(history, [0])
            existing_metadata = storage.metadata_for_history(pulls)[0]
            if existing_metadata is None:
                self.fail("Expected registered metadata for the pull.")
            original = path.read_bytes()

            with patch(
                "src.wuwa_calculator.storage.convene_sync_storage.os.replace",
                side_effect=OSError("disk full"),
            ), self.assertRaises(OSError):
                storage.queue_upload([existing_metadata.client_record_id])

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(root.glob(".sync.json.*.tmp")), [])
            current_metadata = storage.metadata_for_history(pulls)[0]
            if current_metadata is None:
                self.fail("Sync metadata disappeared after failed write.")
            self.assertEqual(current_metadata.sync_state, "local_only")

    def test_import_does_not_create_sync_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_manager = ConveneStorageManager(root / "source.json")
            source_manager.save_context({
                "player_id": "504413756",
                "record_id": "record",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
                "card_pool_type": 1,
            })
            source_manager.merge([{**self._pull(), "player_id": "504413756"}])
            portable_path = root / "portable.json"
            source_manager.export_tethys_history(portable_path)
            history = ConveneStorageManager(root / "history.json")
            sync = ConveneSyncStorage(root / "sync.json")

            history.import_json_with_report(portable_path)

            self.assertFalse(sync.path.exists())
            self.assertEqual(sync.metadata_for_history(history.load()), [None])


if __name__ == "__main__":
    unittest.main()
