import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.pity_tracker import (
    ConveneStorageManager,
    LegacyPityTrackerWidget,
    PityHistoryImportWorker,
    TrackerStatus,
    _normalize_pull_record,
    _failed_tracker_status,
)
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager as StorageManager


class TethysTrackerBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_normalize_pull_record_supports_documented_aliases(self) -> None:
        aliases = (
            ("timestamp", "name", "rarity", "pool", "seq_id"),
            ("time", "item", "quality", "type", "seqId"),
            ("date", "title", "rank", "gacha_type", "pull_id"),
        )
        for timestamp_key, name_key, rarity_key, pool_key, id_key in aliases:
            with self.subTest(keys=aliases):
                raw = {
                    timestamp_key: "2026-09-10T10:00:00Z",
                    name_key: "Qingxiao",
                    rarity_key: 5,
                    pool_key: "resonator",
                    id_key: "official-1",
                    "extra": "preserved",
                }
                normalized = _normalize_pull_record(raw, source="client_log")

                self.assertEqual(normalized["timestamp"], raw[timestamp_key])
                self.assertEqual(normalized["name"], "Qingxiao")
                self.assertEqual(normalized["rarity"], 5)
                self.assertEqual(normalized["pool"], "resonator")
                self.assertEqual(normalized["official_id"], "official-1")
                self.assertEqual(normalized["source"], "client_log")
                self.assertEqual(normalized["raw"], raw)
                self.assertEqual(normalized["dedup_key"], "id:official-1")

    def test_normalize_pull_record_preserves_all_canonical_pool_tags(self) -> None:
        pools = (
            "resonator",
            "weapon",
            "standard_character",
            "standard_weapon",
        )

        normalized = [
            _normalize_pull_record({
                "timestamp": f"2026-01-0{index + 1}",
                "name": f"Pull {index}",
                "rarity": 3,
                "pool": pool,
            })
            for index, pool in enumerate(pools)
        ]

        self.assertEqual([record["pool"] for record in normalized], list(pools))

    def test_official_id_dedup_keeps_distinct_records(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            storage = StorageManager(Path(temporary_directory) / "history.json")
            merged = storage.merge([
                {"seq_id": "same", "timestamp": "2026-01-01", "name": "First"},
                {"seq_id": "same", "timestamp": "2026-01-01", "name": "Duplicate"},
                {"seq_id": "different", "timestamp": "2026-01-02", "name": "Legitimate"},
            ])

            self.assertEqual(len(merged), 2)
            self.assertEqual({record["seq_id"] for record in merged}, {"same", "different"})

    def test_fallback_signature_dedup_uses_pull_fields(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            storage = StorageManager(Path(temporary_directory) / "history.json")
            record = {
                "timestamp": "2026-01-01T00:00:00Z",
                "pool": "resonator",
                "name": "Qingxiao",
                "rarity": 5,
            }
            merged = storage.merge([record, dict(record)])

            self.assertEqual(len(merged), 1)
            self.assertEqual(StorageManager._record_key(record), StorageManager._record_key(dict(record)))

    def test_merge_sorts_records_and_preserves_equal_timestamp_order(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            storage = StorageManager(Path(temporary_directory) / "history.json")
            merged = storage.merge([
                {"seq_id": "late", "timestamp": "2026-01-03", "name": "Late"},
                {"seq_id": "same-a", "timestamp": "2026-01-02", "name": "Same A"},
                {"seq_id": "same-b", "timestamp": "2026-01-02", "name": "Same B"},
                {"seq_id": "early", "timestamp": "2026-01-01", "name": "Early"},
            ])

            self.assertEqual([record["name"] for record in merged], [
                "Early", "Same A", "Same B", "Late",
            ])
            self.assertEqual(storage.load(), merged)

    def test_merge_history_and_api_counts_only_new_records(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            storage = StorageManager(Path(temporary_directory) / "history.json")
            old = {"seq_id": "old", "timestamp": "2026-01-01", "name": "Old"}
            new = {"seq_id": "new", "timestamp": "2026-01-02", "name": "New"}
            storage.merge([old])

            merged, new_count = storage.merge_with_metadata([old, new])

            self.assertEqual(new_count, 1)
            self.assertEqual({record["seq_id"] for record in merged}, {"old", "new"})

    def test_second_sync_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            storage = StorageManager(Path(temporary_directory) / "history.json")
            records = [
                {"seq_id": "1", "timestamp": "2026-01-01", "name": "One"},
                {"seq_id": "2", "timestamp": "2026-01-02", "name": "Two"},
            ]

            _, first_count = storage.merge_with_metadata(records)
            first_total = len(storage.load())
            _, second_count = storage.merge_with_metadata(records)
            second_total = len(storage.load())

            self.assertEqual(first_count, 2)
            self.assertEqual(second_count, 0)
            self.assertEqual(second_total, first_total)

    def test_pity_state_derives_totals_reset_and_recent_pity(self) -> None:
        widget = LegacyPityTrackerWidget()
        self.addCleanup(widget.deleteLater)
        widget._update_state_from_records([
            {"timestamp": "2026-01-04", "pool": "resonator", "rarity": 3, "name": "R1"},
            {"timestamp": "2026-01-01", "pool": "resonator", "rarity": 3, "name": "R0"},
            {"timestamp": "2026-01-02", "pool": "resonator", "rarity": 4, "name": "R4"},
            {"timestamp": "2026-01-03", "pool": "resonator", "rarity": 5, "name": "R5"},
            {"timestamp": "2026-01-05", "pool": "resonator", "rarity": 3, "name": "R2"},
        ])

        self.assertEqual(widget.state.total_registered, 5)
        self.assertEqual(widget.state.four_star_total, 1)
        self.assertEqual(widget.state.five_star_history, [3])
        self.assertEqual(widget.state.resonator, 2)
        self.assertEqual(widget.state.recent_convene_details[-1], "R2 (3★)")

    def test_pity_pools_are_independent(self) -> None:
        widget = LegacyPityTrackerWidget()
        self.addCleanup(widget.deleteLater)
        widget._update_state_from_records([
            {"timestamp": "2026-01-01", "pool": "resonator", "rarity": 3, "name": "R"},
            {"timestamp": "2026-01-02", "pool": "weapon", "rarity": 3, "name": "W"},
            {"timestamp": "2026-01-03", "pool": "weapon", "rarity": 5, "name": "W5"},
            {"timestamp": "2026-01-04", "pool": "resonator", "rarity": 3, "name": "R2"},
            {"timestamp": "2026-01-05", "pool": "standard_character", "rarity": 3, "name": "C"},
            {"timestamp": "2026-01-06", "pool": "standard_weapon", "rarity": 3, "name": "S"},
        ])

        self.assertEqual(widget.state.resonator, 2)
        self.assertEqual(widget.state.weapon, 0)
        self.assertEqual(widget.state.standard_character, 1)
        self.assertEqual(widget.state.standard_weapon, 1)
        self.assertEqual(widget.state.five_star_history, [2])

    def test_partial_api_status_is_structured(self) -> None:
        statuses = {
            "1": {"status": "success", "completed": True, "record_count": 1},
            "2": {"status": "success_empty", "completed": True, "record_count": 0},
            "3": {"status": "error", "completed": True, "record_count": 0},
            "4": {"status": "success", "completed": True, "record_count": 1},
        }
        status = _failed_tracker_status(
            statuses,
            "partial",
            "partial sync",
            "started",
        )

        self.assertTrue(status.is_partial)
        self.assertEqual(status.sync_status, "partial")
        self.assertEqual(status.pool_status["1"]["status"], "success")
        self.assertEqual(status.pool_status["2"]["status"], "success_empty")
        self.assertEqual(status.pool_status["3"]["status"], "error")
        self.assertEqual(status.pool_status["4"]["status"], "success")

    def test_worker_keeps_records_when_one_pool_is_success_empty(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses.update({
                "1": {"status": "success", "completed": True, "record_count": 1},
                "2": {"status": "success_empty", "completed": True, "record_count": 0},
                "3": {"status": "success", "completed": True, "record_count": 1},
                "4": {"status": "success", "completed": True, "record_count": 1},
            })
            return [
                {"timestamp": "2026-01-01", "name": "R", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-01-02", "name": "C", "rarity": 3, "pool": "standard_character"},
                {"timestamp": "2026-01-03", "name": "S", "rarity": 3, "pool": "standard_weapon"},
            ]

        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker("https://example.invalid/record")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        def merge_records(records: list[dict[str, object]]):
            return list(records), len(records)

        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=merge_records):
            worker.run()

        self.assertEqual(len(imported[0]), 3)
        self.assertEqual(statuses[-1].sync_status, "success")
        self.assertEqual(statuses[-1].pool_status["2"]["status"], "success_empty")

    def test_worker_aggregates_successful_pools_around_one_error(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses.update({
                "1": {"status": "success", "completed": True, "record_count": 2},
                "2": {"status": "success", "completed": True, "record_count": 1},
                "3": {"status": "error", "completed": True, "record_count": 0},
                "4": {"status": "success", "completed": True, "record_count": 1},
            })
            return [
                {"timestamp": "2026-01-01", "name": "R1", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-01-02", "name": "R2", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-01-03", "name": "W", "rarity": 3, "pool": "weapon"},
                {"timestamp": "2026-01-04", "name": "S", "rarity": 3, "pool": "standard_weapon"},
            ]

        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker("https://example.invalid/record")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        def merge_records(records: list[dict[str, object]]):
            return list(records), len(records)

        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=merge_records):
            worker.run()

        self.assertEqual(len(imported[0]), 4)
        self.assertEqual(statuses[-1].sync_status, "partial")
        self.assertEqual(statuses[-1].pool_status["3"]["status"], "error")
        self.assertEqual(statuses[-1].pool_status["1"]["status"], "success")
        self.assertEqual(statuses[-1].pool_status["2"]["status"], "success")
        self.assertEqual(statuses[-1].pool_status["4"]["status"], "success")

    def test_persistence_failure_still_emits_normalized_records(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses["1"] = {"status": "success", "completed": True, "record_count": 1}
            return [{
                "seq_id": "1",
                "timestamp": "2026-01-01",
                "name": "Qingxiao",
                "rarity": 5,
                "pool": "resonator",
            }]

        statuses: list[TrackerStatus] = []
        imported: list[object] = []
        worker = PityHistoryImportWorker("https://example.invalid/record")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=OSError("disk full")):
            worker.run()

        self.assertEqual(statuses[-1].history_status, "error")
        self.assertEqual(statuses[-1].sync_status, "error")
        self.assertEqual(imported[0][0]["official_id"], "1")
        self.assertEqual(imported[0][0]["dedup_key"], "id:1")

    def test_corrupted_json_loads_as_empty_history(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.json"
            path.write_text("{not valid json", encoding="utf-8")

            self.assertEqual(StorageManager(path).load(), [])

    def test_atomic_save_preserves_previous_file_when_replace_fails(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.json"
            original = '{"schema_version": 1, "pulls": []}'
            path.write_text(original, encoding="utf-8")
            storage = StorageManager(path)

            with patch("src.wuwa_calculator.storage.convene_storage.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    storage.merge([{
                        "seq_id": "1",
                        "timestamp": "2026-01-01",
                        "name": "One",
                    }])

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(temporary_directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
