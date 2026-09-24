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


if __name__ == "__main__":
    unittest.main()
