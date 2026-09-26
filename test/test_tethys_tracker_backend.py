import json
import io
import os
import requests
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.domain.pity import calculate_pity_state
from src.wuwa_calculator.app.pity_tracker import (
    CONVENE_DNS_ERROR_MESSAGE,
    ConveneStorageManager,
    LegacyPityTrackerWidget,
    PityHistoryImportWorker,
    TrackerStatus,
    fetch_convene_records,
    _normalize_pull_record,
    _failed_tracker_status,
)
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager as StorageManager

KURO_RECORD_URL = (
    "https://aki-gm-resources.example/record?playerId=player&recordId=record&"
    "serverId=server&cardPoolId=pool&languageCode=en"
)


class TethysTrackerBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _player_url(player_id: str) -> str:
        return KURO_RECORD_URL.replace("playerId=player", f"playerId={player_id}")

    @staticmethod
    def _save_player_context(storage: StorageManager, player_id: str) -> None:
        storage.save_context({
            "player_id": player_id,
            "record_id": f"record-{player_id}",
            "server_id": "server",
            "card_pool_id": "pool",
            "language_code": "en",
            "card_pool_type": 1,
        })

    def _run_active_sync(
        self,
        storage: StorageManager,
        player_id: str,
        records: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            self._save_player_context(storage, player_id)
            pool_statuses.update({
                str(pool): {"status": "success", "completed": True, "record_count": 1}
                for pool in range(1, 5)
            })
            return records

        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker(self._player_url(player_id))
        worker.imported.connect(imported.append)
        with patch(
            "src.wuwa_calculator.app.pity_tracker.fetch_convene_records",
            side_effect=fake_fetch,
        ), patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
            return_value=storage,
        ):
            worker.run()
        self.assertEqual(len(imported), 1)
        return imported[0]

    def test_unicode_api_diagnostics_do_not_break_windows_console_sync(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "code": 0,
            "message": "成功",
            "data": [{"name": "漂泊者", "quality": 3, "time": "2026-09-24 12:00:00"}],
        }
        statuses: dict[str, dict[str, object]] = {}
        console_buffer = io.BytesIO()
        windows_console = io.TextIOWrapper(
            console_buffer,
            encoding="cp1252",
            errors="strict",
            write_through=True,
        )

        with (
            patch("sys.stdout", windows_console),
            patch(
                "src.wuwa_calculator.app.pity_tracker.requests.post",
                return_value=response,
            ) as post,
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.save_context"
            ),
        ):
            records = fetch_convene_records(KURO_RECORD_URL, pool_statuses=statuses)

        self.assertEqual(len(records), 4)
        self.assertEqual(len(statuses), 4)
        self.assertEqual(post.call_count, 4)
        self.assertIn(r"newest_name='\u6f02\u6cca\u8005'", console_buffer.getvalue().decode("cp1252"))

    @staticmethod
    def _active_pull(name: str, *, day: int = 1, rarity: int = 3, **extra: object) -> dict[str, object]:
        return {
            "timestamp": f"2026-09-{day:02d}T10:00:00Z",
            "pool": "resonator",
            "name": name,
            "rarity": rarity,
            **extra,
        }

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

    def test_active_history_isolated_across_player_switches_and_pity(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            account_a = [self._active_pull(f"A{index}", day=index) for index in range(1, 4)]
            account_b = [self._active_pull(f"B{index}", day=index + 3) for index in range(1, 4)]
            self._save_player_context(storage, "A")
            storage.merge_active_player_with_metadata(account_a, "A")

            tracker_a = self._run_active_sync(
                storage, "A", [self._active_pull("A4", day=4)]
            )
            self.assertEqual({row["name"] for row in tracker_a}, {"A1", "A2", "A3", "A4"})
            self.assertEqual(calculate_pity_state(tracker_a).total_registered, 4)

            tracker_b = self._run_active_sync(storage, "B", account_b)
            self.assertEqual({row["name"] for row in tracker_b}, {"B1", "B2", "B3"})
            self.assertEqual(calculate_pity_state(tracker_b).total_registered, 3)
            self.assertEqual({row["name"] for row in storage.load_for_player("A")}, {"A1", "A2", "A3", "A4"})

            repeated_b = self._run_active_sync(storage, "B", account_b)
            self.assertEqual(len(repeated_b), 3)
            self.assertEqual(calculate_pity_state(repeated_b).total_registered, 3)

            tracker_c = self._run_active_sync(
                storage, "C", [self._active_pull("C1", day=8)]
            )
            self.assertEqual([row["name"] for row in tracker_c], ["C1"])
            self.assertEqual({row["name"] for row in storage.load_for_player("B")}, {"B1", "B2", "B3"})

            tracker_a_again = self._run_active_sync(
                storage, "A", [self._active_pull("A5", day=5)]
            )
            self.assertEqual(
                {row["name"] for row in tracker_a_again},
                {"A1", "A2", "A3", "A4", "A5"},
            )
            self.assertEqual({row["name"] for row in storage.load_for_player("B")}, {"B1", "B2", "B3"})
            self.assertEqual({row["name"] for row in storage.load_for_player("C")}, {"C1"})
            self.assertEqual(len(storage.load()), 9)

    def test_active_merge_keeps_same_resource_and_same_fields_for_different_players(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            account_a = self._active_pull(
                "Same event", day=1, player_id="A", resourceId=123
            )
            account_b = self._active_pull(
                "Same event", day=1, player_id="B", resourceId=123
            )

            storage.merge_active_player_with_metadata([account_a], "A")
            storage.merge_active_player_with_metadata([account_b], "B")

            self.assertEqual(len(storage.load()), 2)
            self.assertEqual(
                {row["player_id"] for row in storage.load()},
                {"A", "B"},
            )

    def test_unowned_legacy_pulls_are_preserved_but_not_assigned_to_new_player(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            legacy = self._active_pull("Unknown legacy", day=1)
            storage.merge([legacy])

            active = storage.load_for_player("B")
            merged, _count = storage.merge_active_player_with_metadata(
                [self._active_pull("B pull", day=2)], "B"
            )

            self.assertEqual([row["name"] for row in active], [])
            self.assertEqual([row["name"] for row in merged], ["B pull"])
            self.assertEqual({row["name"] for row in storage.load()}, {"Unknown legacy", "B pull"})

    def test_active_sync_promotes_strong_legacy_match_with_continuous_context(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            self._save_player_context(storage, "A")
            api_pull = {
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Known legacy pull",
                "rarity": 3,
                "resourceId": 123,
            }
            storage.merge([
                {**api_pull, "raw": dict(api_pull), "source": "convene_api"},
                {
                    "timestamp": "2026-09-02T10:00:00Z",
                    "pool": "resonator",
                    "name": "Unrelated legacy pull",
                    "rarity": 3,
                },
            ])
            legacy_id = next(
                row["local_record_id"]
                for row in storage.load()
                if row["name"] == "Known legacy pull"
            )

            self._run_active_sync(storage, "A", [api_pull])

            pulls = storage.load()
            self.assertEqual(len(pulls), 2)
            promoted = storage.load_for_player("A")
            self.assertEqual([row["name"] for row in promoted], ["Known legacy pull"])
            self.assertEqual(promoted[0]["local_record_id"], legacy_id)
            self.assertEqual(
                [row["name"] for row in pulls if StorageManager._record_player_id(row) is None],
                ["Unrelated legacy pull"],
            )

    def test_active_sync_does_not_promote_legacy_after_player_context_switch(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            self._save_player_context(storage, "A")
            api_pull = {
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Coincident pull",
                "rarity": 3,
                "resourceId": 123,
            }
            storage.merge([{**api_pull, "raw": dict(api_pull)}])

            self._run_active_sync(storage, "B", [api_pull])

            pulls = storage.load()
            self.assertEqual(len(pulls), 2)
            self.assertEqual(
                [row["name"] for row in pulls if StorageManager._record_player_id(row) is None],
                ["Coincident pull"],
            )
            self.assertEqual(
                [row["name"] for row in storage.load_for_player("B")],
                ["Coincident pull"],
            )

    def test_active_sync_does_not_promote_legacy_when_occurrence_is_owned_by_other_player(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            self._save_player_context(storage, "A")
            api_pull = {
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Pull owned by another player",
                "rarity": 3,
                "resourceId": 123,
            }
            storage.merge([
                {**api_pull, "raw": dict(api_pull)},
                {**api_pull, "raw": dict(api_pull), "player_id": "B"},
            ])

            self._run_active_sync(storage, "A", [api_pull])

            pulls = storage.load()
            self.assertEqual(len(pulls), 3)
            self.assertEqual(
                sum(StorageManager._record_player_id(row) is None for row in pulls),
                1,
            )
            self.assertEqual(len(storage.load_for_player("A")), 1)
            self.assertEqual(len(storage.load_for_player("B")), 1)

    def test_active_sync_requires_strong_evidence_beyond_matching_pull_fields(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            self._save_player_context(storage, "A")
            api_pull = {
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Matching visible fields",
                "rarity": 3,
                "resourceId": 123,
            }
            legacy = {
                **api_pull,
                "raw": {**api_pull, "capture_marker": "legacy"},
            }
            storage.merge([legacy])

            self._run_active_sync(storage, "A", [api_pull])

            pulls = storage.load()
            self.assertEqual(len(pulls), 2)
            self.assertEqual(
                [row["name"] for row in pulls if StorageManager._record_player_id(row) is None],
                ["Matching visible fields"],
            )
            self.assertEqual(len(storage.load_for_player("A")), 1)

    def test_active_sync_requires_player_id_before_fetch_or_persistence(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            self._save_player_context(storage, "A")
            storage.merge_active_player_with_metadata([self._active_pull("A pull")], "A")
            before = storage.path.read_bytes()
            failures: list[str] = []
            worker = PityHistoryImportWorker("https://aki-gm-resources.example/record")
            worker.failed.connect(failures.append)

            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.fetch_convene_records"
            ) as fetch:
                worker.run()

            fetch.assert_not_called()
            self.assertTrue(failures)
            self.assertEqual(storage.path.read_bytes(), before)
            self.assertEqual({row["name"] for row in storage.load_for_player("A")}, {"A pull"})

    def test_export_selects_only_requested_player_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            storage = StorageManager(root / "history.json")
            self._save_player_context(storage, "A")
            storage.merge_active_player_with_metadata([self._active_pull("A pull")], "A")
            self._save_player_context(storage, "B")
            storage.merge_active_player_with_metadata([self._active_pull("B pull", day=2)], "B")

            export_a = storage.export_tethys_history(root / "a.json", player_id="A")
            export_b = storage.export_tethys_history(root / "b.json", player_id="B")

            self.assertEqual(export_a["playerId"], "A")
            pulls_a = export_a["pulls"]
            self.assertIsInstance(pulls_a, list)
            if not isinstance(pulls_a, list):
                self.fail("player A export pulls must be a list")
            self.assertEqual([pull["name"] for pull in pulls_a], ["A pull"])
            self.assertEqual(export_b["playerId"], "B")
            pulls_b = export_b["pulls"]
            self.assertIsInstance(pulls_b, list)
            if not isinstance(pulls_b, list):
                self.fail("player B export pulls must be a list")
            self.assertEqual([pull["name"] for pull in pulls_b], ["B pull"])

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
                {"timestamp": "2026-09-01", "name": "R", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-09-02", "name": "C", "rarity": 3, "pool": "standard_character"},
                {"timestamp": "2026-09-03", "name": "S", "rarity": 3, "pool": "standard_weapon"},
            ]

        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker("https://aki-gm-resources.example/record?playerId=player&recordId=record&serverId=server&cardPoolId=pool&languageCode=en")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        def merge_records(records: list[dict[str, object]]):
            return list(records), len(records)

        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=merge_records), \
                patch.object(ConveneStorageManager, "load", return_value=[]):
            worker.run()

        self.assertEqual(len(imported[0]), 3)
        self.assertEqual(statuses[-1].sync_status, "success")
        self.assertEqual(statuses[-1].pool_status["2"]["status"], "success_empty")

    def test_all_api_pools_failing_is_error_and_preserves_existing_history(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            storage.merge([{
                "timestamp": "2026-09-01T10:00:00Z",
                "name": "Existing pull",
                "rarity": 5,
                "pool": "resonator",
            }])
            before_bytes = storage.path.read_bytes()
            before_history = storage.load()
            statuses: list[TrackerStatus] = []
            imported: list[list[dict[str, object]]] = []
            failures: list[str] = []
            worker = PityHistoryImportWorker(KURO_RECORD_URL)
            worker.status.connect(statuses.append)
            worker.imported.connect(imported.append)
            worker.failed.connect(failures.append)
            unavailable = Mock(status_code=503, text="Service unavailable")

            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.requests.post",
                return_value=unavailable,
            ) as post:
                worker.run()

            self.assertEqual(post.call_count, 4)
            self.assertEqual(set(statuses[-1].pool_status), {"1", "2", "3", "4"})
            self.assertTrue(all(
                status["status"] == "error" and status["completed"] is True
                for status in statuses[-1].pool_status.values()
            ))
            self.assertEqual(statuses[-1].sync_status, "error")
            self.assertIsNone(statuses[-1].last_success_at)
            self.assertIn("todos os pools", statuses[-1].message)
            self.assertEqual(failures, ["Falha ao consultar todos os pools de Convene."])
            self.assertEqual(imported, [])
            self.assertEqual(storage.path.read_bytes(), before_bytes)
            self.assertEqual(storage.load(), before_history)

    def test_all_successful_empty_pools_are_success_no_new(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            existing, _count = storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "name": "Existing pull",
                "rarity": 5,
                "pool": "resonator",
            }], "player")
            statuses: list[TrackerStatus] = []
            imported: list[list[dict[str, object]]] = []
            worker = PityHistoryImportWorker(KURO_RECORD_URL)
            worker.status.connect(statuses.append)
            worker.imported.connect(imported.append)
            empty_success = Mock(status_code=200, text="")
            empty_success.json.return_value = {
                "code": 0,
                "message": "success",
                "data": [],
            }

            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.requests.post",
                return_value=empty_success,
            ) as post:
                worker.run()

            self.assertEqual(post.call_count, 4)
            self.assertEqual(
                [statuses[-1].pool_status[str(pool)]["status"] for pool in range(1, 5)],
                ["success_empty"] * 4,
            )
            self.assertEqual(statuses[-1].sync_status, "success_no_new")
            self.assertIsNotNone(statuses[-1].last_success_at)
            self.assertEqual(storage.load(), existing)
            self.assertEqual(imported, [existing])

    def test_one_successful_empty_pool_and_three_errors_is_partial(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            statuses: list[TrackerStatus] = []
            imported: list[list[dict[str, object]]] = []
            worker = PityHistoryImportWorker(KURO_RECORD_URL)
            worker.status.connect(statuses.append)
            worker.imported.connect(imported.append)
            empty_success = Mock(status_code=200, text="")
            empty_success.json.return_value = {
                "code": 0,
                "message": "success",
                "data": [],
            }
            unavailable = Mock(status_code=503, text="Service unavailable")

            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.requests.post",
                side_effect=[empty_success, unavailable, unavailable, unavailable],
            ) as post:
                worker.run()

            self.assertEqual(post.call_count, 4)
            self.assertEqual(statuses[-1].sync_status, "partial")
            self.assertTrue(statuses[-1].is_partial)
            self.assertIsNone(statuses[-1].last_success_at)
            self.assertEqual(statuses[-1].pool_status["1"]["status"], "success_empty")
            self.assertTrue(all(
                statuses[-1].pool_status[str(pool)]["status"] == "error"
                for pool in (2, 3, 4)
            ))
            self.assertEqual(imported, [[]])
            self.assertEqual(storage.load(), [])

    def test_general_network_failure_remains_an_error(self) -> None:
        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        failures: list[str] = []
        worker = PityHistoryImportWorker(KURO_RECORD_URL)
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        worker.failed.connect(failures.append)

        with patch(
            "src.wuwa_calculator.app.pity_tracker.requests.post",
            side_effect=requests.exceptions.ConnectionError("network down"),
        ) as post:
            worker.run()

        self.assertEqual(post.call_count, 4)
        self.assertEqual(statuses[-1].sync_status, "offline")
        self.assertEqual(failures, [CONVENE_DNS_ERROR_MESSAGE])
        self.assertEqual(imported, [])

    def test_worker_aggregates_successful_pools_around_one_error(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses.update({
                "1": {"status": "success", "completed": True, "record_count": 2},
                "2": {"status": "success", "completed": True, "record_count": 1},
                "3": {"status": "error", "completed": True, "record_count": 0},
                "4": {"status": "success", "completed": True, "record_count": 1},
            })
            return [
                {"timestamp": "2026-09-01", "name": "R1", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-09-02", "name": "R2", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-09-03", "name": "W", "rarity": 3, "pool": "weapon"},
                {"timestamp": "2026-09-04", "name": "S", "rarity": 3, "pool": "standard_weapon"},
            ]

        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker("https://aki-gm-resources.example/record?playerId=player&recordId=record&serverId=server&cardPoolId=pool&languageCode=en")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        def merge_records(records: list[dict[str, object]]):
            return list(records), len(records)

        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=merge_records), \
                patch.object(ConveneStorageManager, "load", return_value=[]):
            worker.run()

        self.assertEqual(len(imported[0]), 4)
        self.assertEqual(statuses[-1].sync_status, "partial")
        self.assertEqual(statuses[-1].pool_status["3"]["status"], "error")
        self.assertEqual(statuses[-1].pool_status["1"]["status"], "success")
        self.assertEqual(statuses[-1].pool_status["2"]["status"], "success")
        self.assertEqual(statuses[-1].pool_status["4"]["status"], "success")

    def test_worker_keeps_history_and_reports_partial_when_no_current_records(self) -> None:
        local_history = [{
            "timestamp": "2026-08-31 23:59:59",
            "name": "Existing Five",
            "rarity": 5,
            "pool": "resonator",
        }]

        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses.update({
                "1": {"status": "success_empty", "completed": True, "record_count": 0},
                "2": {"status": "error", "completed": True, "record_count": 0},
                "3": {"status": "success_empty", "completed": True, "record_count": 0},
                "4": {"status": "success_empty", "completed": True, "record_count": 0},
            })
            return []

        statuses: list[TrackerStatus] = []
        imported: list[list[dict[str, object]]] = []
        worker = PityHistoryImportWorker("https://aki-gm-resources.example/record?playerId=player&recordId=record&serverId=server&cardPoolId=pool&languageCode=en")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch) as fetch, \
                patch.object(ConveneStorageManager, "load_for_player", return_value=local_history), \
                patch.object(ConveneStorageManager, "merge_with_metadata") as merge:
            worker.run()

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(set(statuses[-1].pool_status), {"1", "2", "3", "4"})
        self.assertEqual(imported[0], local_history)
        self.assertEqual(statuses[-1].sync_status, "partial")
        self.assertTrue(statuses[-1].is_partial)
        merge.assert_not_called()

    def test_non_pull_api_rows_do_not_increase_pity(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses.update({
                str(pool): {
                    "status": "success" if pool == 1 else "success_empty",
                    "completed": True,
                    "record_count": 1 if pool == 1 else 0,
                }
                for pool in range(1, 5)
            })
            return [
                {
                    "timestamp": "2026-09-10T10:00:00-05:00",
                    "name": "Valid pull",
                    "rarity": 3,
                    "pool": "resonator",
                },
                {"timestamp": "2026-09-10T11:00:00-05:00", "record_url": "not-a-pull"},
            ]

        imported: list[list[dict[str, object]]] = []
        persisted: list[dict[str, object]] = []
        worker = PityHistoryImportWorker("https://aki-gm-resources.example/record?playerId=player&recordId=record&serverId=server&cardPoolId=pool&languageCode=en")
        worker.imported.connect(imported.append)

        def merge_valid_pulls(records: list[dict[str, object]]):
            persisted.extend(records)
            return list(records), len(records)

        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(
                    ConveneStorageManager,
                    "merge_with_metadata",
                    side_effect=merge_valid_pulls,
                ):
            worker.run()

        self.assertEqual(len(persisted), 1)
        self.assertNotEqual(persisted[0].get("is_pull"), False)
        self.assertEqual(len(imported[0]), 2)
        self.assertIs(imported[0][1]["is_pull"], False)
        tracker = LegacyPityTrackerWidget()
        tracker._apply_imported_records(imported[0])
        self.assertEqual(tracker.state.total_registered, 1)
        self.assertEqual(tracker.state.resonator, 1)
        tracker.close()

    def test_pity_calculation_does_not_change_persisted_non_pull_record(self) -> None:
        with TemporaryDirectory() as directory:
            storage = StorageManager(Path(directory) / "history.json")
            document = {
                "pulls": [
                    {
                        "timestamp": "2026-09-10T10:00:00Z",
                        "name": "Valid pull",
                        "rarity": 3,
                        "pool": "resonator",
                    },
                    {
                        "timestamp": "2026-09-10T11:00:00Z",
                        "record_url": "metadata-only",
                        "is_pull": False,
                    },
                ]
            }
            storage.path.write_text(json.dumps(document), encoding="utf-8")
            bytes_before = storage.path.read_bytes()
            records_before = storage.load()

            state = calculate_pity_state(records_before)

            self.assertEqual(state.total_registered, 1)
            self.assertEqual(len(storage.load()), 2)
            self.assertIn({
                "timestamp": "2026-09-10T11:00:00Z",
                "record_url": "metadata-only",
                "is_pull": False,
            }, storage.load())
            self.assertEqual(storage.path.read_bytes(), bytes_before)

    def test_persistence_failure_still_emits_normalized_records(self) -> None:
        def fake_fetch(_url: str, *, pool_statuses: dict[str, dict[str, object]]):
            pool_statuses["1"] = {"status": "success", "completed": True, "record_count": 1}
            return [{
                "seq_id": "1",
                "timestamp": "2026-09-01",
                "name": "Qingxiao",
                "rarity": 5,
                "pool": "resonator",
            }]

        statuses: list[TrackerStatus] = []
        imported: list[object] = []
        worker = PityHistoryImportWorker("https://aki-gm-resources.example/record?playerId=player&recordId=record&serverId=server&cardPoolId=pool&languageCode=en")
        worker.status.connect(statuses.append)
        worker.imported.connect(imported.append)
        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", side_effect=fake_fetch), \
                patch.object(ConveneStorageManager, "merge_with_metadata", side_effect=OSError("disk full")), \
                patch.object(ConveneStorageManager, "load", return_value=[]):
            worker.run()

        self.assertEqual(statuses[-1].history_status, "error")
        self.assertEqual(statuses[-1].sync_status, "error")
        first_import = imported[0]
        self.assertIsInstance(first_import, list)
        if not isinstance(first_import, list) or not first_import:
            self.fail("import worker emitted no records")
        first_record = first_import[0]
        self.assertIsInstance(first_record, dict)
        if not isinstance(first_record, dict):
            self.fail("imported record is not a dictionary")
        self.assertEqual(first_record["official_id"], "1")
        self.assertEqual(first_record["dedup_key"], "id:1")

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
