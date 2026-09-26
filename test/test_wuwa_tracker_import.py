import json
import tempfile
import unittest
from pathlib import Path

from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager


class WuWaTrackerImportTests(unittest.TestCase):
    def _source(self, root: Path, payload: object) -> Path:
        source = root / "wuwa_tracker.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        return source

    def _pull(self, pool_type: int, name: str, timestamp: str, **extra: object) -> dict[str, object]:
        return {
            "cardPoolType": pool_type,
            "resourceId": 21030044,
            "qualityLevel": 4,
            "name": name,
            "time": timestamp,
            "isSorted": True,
            "group": 1,
            **extra,
        }

    def test_maps_pools_and_preserves_source_data(self) -> None:
        pool_names = {
            1: "resonator",
            2: "weapon",
            3: "standard_character",
            4: "standard_weapon",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pulls = [
                self._pull(pool_type, f"Item {pool_type}", f"2026-09-0{pool_type}T10:00:00+00:00")
                for pool_type in pool_names
            ]
            payload = {
                "siteVersion": "v4.8.24",
                "version": "0.0.2",
                "date": "2026-09-23T14:11:45.332Z",
                "playerId": "504413756",
                "pulls": pulls,
            }
            manager = ConveneStorageManager(root / "history.json")
            report = manager.import_json_with_report(self._source(root, payload))

            self.assertEqual(report.format, "wuwa_tracker")
            self.assertEqual(report.player_id, "504413756")
            self.assertEqual(report.imported_count, 4)
            self.assertEqual(report.source_metadata["date"], payload["date"])
            records = {record["cardPoolType"]: record for record in report.records}
            self.assertEqual({key: records[key]["pool"] for key in pool_names}, pool_names)
            for pool_type, original in enumerate(pulls, start=1):
                record = records[pool_type]
                self.assertEqual(record["timestamp"], original["time"])
                self.assertEqual(record["rarity"], 4)
                self.assertEqual(record["resourceId"], 21030044)
                self.assertNotIn("official_id", record)
                self.assertEqual(record["group"], 1)
                self.assertIs(record["isSorted"], True)
                self.assertEqual(record["player_id"], "504413756")
                self.assertEqual(record["raw"], original)
                self.assertEqual(record["source_metadata"], report.source_metadata)

    def test_merge_preserves_context_and_existing_pull_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history = Path(temporary_directory) / "history.json"
            context = {
                "player_id": "player-1",
                "record_id": "record-1",
                "server_id": "server-1",
                "card_pool_id": "pool-1",
                "language_code": "en",
                "card_pool_type": 1,
            }
            existing = {"seq_id": "pull-1", "name": "Existing"}
            history.write_text(json.dumps({
                "schema_version": 1,
                "convene_context": context,
                "pulls": [existing],
            }), encoding="utf-8")
            manager = ConveneStorageManager(history)

            records, new_count = manager.merge_with_metadata([
                existing,
                {"seq_id": "pull-2", "name": "New"},
            ])

            self.assertEqual(new_count, 1)
            self.assertEqual(len(records), 2)
            self.assertEqual(
                {record["seq_id"] for record in records},
                {"pull-1", "pull-2"},
            )
            self.assertEqual(ConveneStorageManager(history).load_context(), context)

    def test_new_context_survives_generic_imports_and_reopening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            context = {
                "player_id": "player-2",
                "record_id": "record-2",
                "server_id": "server-2",
                "card_pool_id": "pool-2",
                "language_code": "en",
                "card_pool_type": 1,
            }
            manager = ConveneStorageManager(history)
            manager.save_context(context)

            first_source = self._source(root, {
                "pulls": [{"seq_id": "pull-1", "name": "First"}],
            })
            manager.import_json(first_source)
            self.assertEqual(manager.load_context(), context)

            second_source = self._source(root, {
                "history": [{"seq_id": "pull-2", "name": "Second"}],
            })
            report = manager.import_json_with_report(second_source)
            reopened = ConveneStorageManager(history)

            self.assertEqual(report.imported_count, 1)
            self.assertEqual(len(reopened.load()), 2)
            self.assertEqual(reopened.load_context(), context)

    def test_unknown_pool_is_reported_and_valid_records_still_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            payload = {
                "playerId": "player-1",
                "pulls": [
                    self._pull(1, "Known", "2026-09-01T00:00:00Z"),
                    self._pull(8, "Unknown", "2026-09-02T00:00:00Z"),
                ],
            }
            manager = ConveneStorageManager(root / "history.json")
            manager.import_json(self._source(root, payload))
            report = manager.last_import_report
            self.assertIsNotNone(report)
            if report is None:
                self.fail("import report was not produced")

            self.assertEqual(report.imported_count, 1)
            self.assertEqual(len(report.records), 1)
            self.assertEqual(report.records[0]["pool"], "resonator")
            self.assertEqual(report.unsupported_pools[0]["cardPoolType"], 8)
            self.assertEqual(report.unsupported_pools[0]["raw"], payload["pulls"][1])

    def test_generic_import_keeps_previous_last_import_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "history.json")
            tracker_source = self._source(root, {
                "playerId": "player-1",
                "pulls": [self._pull(1, "Tracker item", "2026-09-01T00:00:00Z")],
            })
            manager.import_json_with_report(tracker_source)
            previous_report = manager.last_import_report
            generic_source = self._source(root, {
                "history": [{
                    "time": "2026-09-02T00:00:00Z",
                    "name": "Generic item",
                    "pool": "weapon",
                    "rarity": 3,
                }],
            })

            manager.import_json(generic_source)

            self.assertIs(manager.last_import_report, previous_report)
            self.assertEqual(len(manager.load()), 2)

    def test_failed_report_import_keeps_previous_last_import_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "history.json")
            good_source = self._source(root, {
                "playerId": "player-1",
                "pulls": [self._pull(1, "Tracker item", "2026-09-01T00:00:00Z")],
            })
            manager.import_json_with_report(good_source)
            previous_report = manager.last_import_report
            invalid_source = root / "invalid.json"
            invalid_source.write_text("not JSON", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "could not be read"):
                manager.import_json_with_report(invalid_source)

            self.assertIs(manager.last_import_report, previous_report)

    def test_invalid_records_are_reported_without_using_envelope_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            payload = {
                "date": "2026-09-23T14:11:45Z",
                "playerId": "player-1",
                "pulls": [
                    self._pull(1, "May pull", "2026-05-03T00:00:00Z"),
                    self._pull(2, "September pull", "2026-09-03T00:00:00Z"),
                    {"cardPoolType": 1, "name": "Bad time", "qualityLevel": 4, "time": "bad"},
                    "not a pull",
                ],
            }
            manager = ConveneStorageManager(root / "history.json")
            report = manager.import_json_with_report(self._source(root, payload))

            self.assertEqual(report.imported_count, 2)
            self.assertEqual({record["name"] for record in report.records}, {"May pull", "September pull"})
            self.assertEqual(len(report.invalid_records), 2)

    def test_reimport_deduplicates_without_deleting_existing_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            history.write_text(json.dumps({
                "schema_version": 1,
                "convene_context": {"player_id": "player-1"},
                "custom_metadata": "preserve me",
                "pulls": [{"timestamp": "2026-01-01", "name": "Existing", "pool": "weapon", "rarity": 3}],
            }), encoding="utf-8")
            source = self._source(root, {
                "playerId": "player-1",
                "pulls": [self._pull(1, "Imported", "2026-05-03T00:00:00Z")],
            })
            manager = ConveneStorageManager(history)

            first = manager.import_json_with_report(source)
            second = manager.import_json_with_report(source)
            persisted = json.loads(history.read_text(encoding="utf-8"))

            self.assertEqual(first.imported_count, 1)
            self.assertEqual(second.imported_count, 0)
            self.assertEqual(len(second.records), 2)
            self.assertEqual(persisted["custom_metadata"], "preserve me")
            self.assertEqual(persisted["convene_context"], {"player_id": "player-1"})
            self.assertEqual({record["name"] for record in persisted["pulls"]}, {"Existing", "Imported"})

    def test_refuses_to_mix_different_or_unidentified_existing_player(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self._source(root, {
                "playerId": "new-player",
                "pulls": [self._pull(1, "Incoming", "2026-09-03T00:00:00Z")],
            })
            for history_payload in (
                {"pulls": [{"player_id": "other-player", "timestamp": "2026-01-01", "name": "Old"}]},
                {"pulls": [{"timestamp": "2026-01-01", "name": "Unknown owner"}]},
            ):
                history = root / "history.json"
                original = json.dumps(history_payload)
                history.write_text(original, encoding="utf-8")
                with self.assertRaises(ValueError):
                    ConveneStorageManager(history).import_json_with_report(source)
                self.assertEqual(history.read_text(encoding="utf-8"), original)

    def test_import_for_active_player_preserves_other_player_histories_but_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = ConveneStorageManager(root / "history.json")
            context = {
                "player_id": "B",
                "record_id": "record-B",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            }
            history.save_context({**context, "player_id": "A", "record_id": "record-A"})
            history.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "A pull",
                "rarity": 3,
            }], "A")
            history.save_context(context)
            history.merge_active_player_with_metadata([{
                "timestamp": "2026-09-02T10:00:00Z",
                "pool": "resonator",
                "name": "B pull",
                "rarity": 3,
            }], "B")

            same_player_source = self._source(root, {
                "playerId": "B",
                "pulls": [self._pull(1, "Imported B", "2026-09-03T10:00:00Z")],
            })
            report = history.import_json_with_report(same_player_source)
            self.assertEqual(report.player_id, "B")
            self.assertEqual({row["name"] for row in history.load_for_player("A")}, {"A pull"})
            self.assertEqual(
                {row["name"] for row in history.load_for_player("B")},
                {"B pull", "Imported B"},
            )

            different_player_source = self._source(root, {
                "playerId": "A",
                "pulls": [self._pull(1, "Imported A", "2026-09-04T10:00:00Z")],
            })
            before = history.path.read_bytes()
            with self.assertRaises(ValueError):
                history.import_json_with_report(different_player_source)
            self.assertEqual(history.path.read_bytes(), before)

    def test_context_loader_rejects_invalid_player_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.json"
            base_context = {
                "record_id": "record",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            }
            for player_id in ("", True, 1.5, "bad id", "bad/id"):
                with self.subTest(player_id=player_id):
                    path.write_text(json.dumps({
                        "convene_context": {**base_context, "player_id": player_id}
                    }), encoding="utf-8")
                    self.assertIsNone(ConveneStorageManager(path).load_context())

            path.write_text(json.dumps({
                "convene_context": {**base_context, "player_id": "player-2"}
            }), encoding="utf-8")
            loaded_context = ConveneStorageManager(path).load_context()
            self.assertIsNotNone(loaded_context)
            if loaded_context is None:
                self.fail("valid context should be loaded")
            self.assertEqual(
                loaded_context["player_id"],
                "player-2",
            )

    def test_wuwa_import_without_context_does_not_mix_into_other_players(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history_path = root / "history.json"
            history_path.write_text(json.dumps({"pulls": [
                {"player_id": "A", "timestamp": "2026-09-01T10:00:00Z", "pool": "resonator", "name": "A pull", "rarity": 5},
                {"player_id": "B", "timestamp": "2026-09-02T10:00:00Z", "pool": "resonator", "name": "B pull", "rarity": 5},
                {"timestamp": "2026-09-03T10:00:00Z", "pool": "resonator", "name": "legacy", "rarity": 5},
            ]}), encoding="utf-8")
            source = self._source(root, {
                "playerId": "B",
                "pulls": [self._pull(1, "Imported B", "2026-09-04T10:00:00Z")],
            })
            before = history_path.read_bytes()
            with self.assertRaises(ValueError):
                ConveneStorageManager(history_path).import_json_with_report(source)
            self.assertEqual(history_path.read_bytes(), before)
            self.assertEqual(
                {record["name"] for record in ConveneStorageManager(history_path).load()},
                {"A pull", "B pull", "legacy"},
            )

    def test_wuwa_import_rejects_malformed_player_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history_path = root / "history.json"
            history_path.write_text(json.dumps({"pulls": []}), encoding="utf-8")
            source = self._source(root, {
                "playerId": "bad id",
                "pulls": [self._pull(1, "Invalid", "2026-09-01T10:00:00Z")],
            })
            with self.assertRaisesRegex(ValueError, "valid playerId"):
                ConveneStorageManager(history_path).import_json_with_report(source)
            self.assertEqual(json.loads(history_path.read_text(encoding="utf-8")), {"pulls": []})

    def test_generic_json_import_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self._source(root, {
                "history": [{
                    "time": "2026-01-01",
                    "name": "Jingran",
                    "pool": "resonator",
                    "rarity": 5,
                }],
            })
            imported = ConveneStorageManager(root / "history.json").import_json(source)
            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["name"], "Jingran")

    def test_json_import_apis_return_equivalent_records_for_each_format(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = [
            (
                "tethys",
                {
                    "format": "tethys_convene_history",
                    "version": 1,
                    "pulls": [{
                        "timestamp": "2026-09-01T10:00:00Z",
                        "pool": "resonator",
                        "name": "Tethys pull",
                        "rarity": 5,
                    }],
                },
            ),
            (
                "wuwa_tracker",
                {
                    "playerId": "player-3",
                    "version": "0.0.2",
                    "pulls": [
                        self._pull(1, "WuWa pull", "2026-09-02T10:00:00Z"),
                        self._pull(8, "Unsupported pull", "2026-09-03T10:00:00Z"),
                    ],
                },
            ),
            (
                "generic",
                {
                    "history": [{
                        "time": "2026-09-04T10:00:00Z",
                        "pool": "weapon",
                        "name": "Generic pull",
                        "rarity": 4,
                        "source": "manual-import",
                        "raw": {"keep": True},
                    }],
                },
            ),
        ]

        def without_local_ids(
            records: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            return [
                {key: value for key, value in record.items() if key != "local_record_id"}
                for record in records
            ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for format_name, payload in cases:
                with self.subTest(format=format_name):
                    simple_root = root / f"{format_name}-simple"
                    report_root = root / f"{format_name}-report"
                    simple_root.mkdir()
                    report_root.mkdir()
                    source = self._source(simple_root, payload)
                    report_source = self._source(report_root, payload)
                    simple_manager = ConveneStorageManager(simple_root / "history.json")
                    report_manager = ConveneStorageManager(report_root / "history.json")

                    simple_records = simple_manager.import_json(source)
                    report = report_manager.import_json_with_report(report_source)

                    self.assertEqual(
                        without_local_ids(simple_records),
                        without_local_ids(report.records),
                    )
                    self.assertTrue(all(record.get("local_record_id") for record in simple_records))
                    self.assertEqual(simple_manager.last_import_report is not None, format_name != "generic")
                    expected_format = (
                        "tethys_convene_history"
                        if format_name == "tethys"
                        else format_name
                    )
                    self.assertEqual(report.format, expected_format)
                    if format_name == "wuwa_tracker":
                        self.assertEqual(report.player_id, "player-3")
                        self.assertEqual(len(report.unsupported_pools), 1)
                    if format_name == "generic":
                        self.assertEqual(report.imported_count, 1)


if __name__ == "__main__":
    unittest.main()
