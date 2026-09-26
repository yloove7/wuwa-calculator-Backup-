import json
import tempfile
import unittest
from pathlib import Path

from src.wuwa_calculator.domain.pity import calculate_pity_state
from src.wuwa_calculator.app.pity_tracker import _normalize_pull_record
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager


class TethysHistoryPortabilityTests(unittest.TestCase):
    def _portable_pull(
        self,
        pool: str = "resonator",
        timestamp: str = "2026-09-01T10:00:00-05:00",
        name: str = "Test item",
        rarity: object = 4,
        **extra: object,
    ) -> dict[str, object]:
        return {
            "timestamp": timestamp,
            "pool": pool,
            "name": name,
            "rarity": rarity,
            **extra,
        }

    def _source(self, root: Path, payload: object) -> Path:
        source = root / "portable.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        return source

    def _exported_pulls(self, document: dict[str, object]) -> list[dict[str, object]]:
        value = document.get("pulls")
        if not isinstance(value, list):
            self.fail("Exported pulls are not a list.")
        result: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                self.fail("An exported pull is not an object.")
            result.append({str(key): field for key, field in item.items()})
        return result

    def test_export_uses_wuwa_tracker_fields_and_only_portable_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            internal = root / "local.json"
            exported = root / "nested" / "portable.json"
            context = {
                "player_id": "private-player",
                "record_id": "private-record",
                "server_id": "server",
                "card_pool_id": "pool-id",
                "language_code": "en",
                "card_pool_type": 1,
            }
            manager = ConveneStorageManager(internal)
            manager.save_context(context)
            manager.merge([{
                **self._portable_pull(),
                "player_id": "private-player",
                "source": "convene_api",
                "raw": {"token": "must stay local"},
                "dedup_key": "internal-key",
                "official_id": "internal-id",
                "resourceId": 123,
            }])
            before = json.loads(internal.read_text(encoding="utf-8"))

            document = manager.export_tethys_history(exported)
            parsed = json.loads(exported.read_text(encoding="utf-8"))
            after = json.loads(internal.read_text(encoding="utf-8"))

            self.assertEqual(document, parsed)
            self.assertEqual(parsed["playerId"], "private-player")
            self.assertRegex(parsed["date"], r"^\d{4}-\d\d-\d\dT.*Z$")
            self.assertEqual(set(parsed), {"playerId", "date", "pulls"})
            self.assertEqual(
                set(parsed["pulls"][0]),
                {"cardPoolType", "time", "name", "qualityLevel", "resourceId"},
            )
            self.assertEqual(parsed["pulls"][0]["cardPoolType"], 1)
            self.assertEqual(parsed["pulls"][0]["qualityLevel"], 4)
            serialized = exported.read_text(encoding="utf-8")
            for private_value in ("private-record", "must stay local", "internal-key"):
                self.assertNotIn(private_value, serialized)
            self.assertEqual(before, after)
            self.assertEqual(manager.load_context(), context)

    def test_export_preserves_persisted_duplicate_occurrences_and_order(self) -> None:
        cases = (
            ("three-identical", ["B", "B", "B"]),
            ("interleaved", ["A", "B", "B", "C", "B", "C"]),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for case_name, names in cases:
                with self.subTest(case=case_name):
                    history_path = root / f"{case_name}-history.json"
                    export_path = root / f"{case_name}-export.json"
                    pulls = [
                        {
                            **self._portable_pull(
                                timestamp="2026-09-01T10:00:00-05:00",
                                name=name,
                            ),
                            "local_record_id": f"internal-{index}",
                            "dedup_key": f"fields:{name}",
                            "raw": {"private": True},
                        }
                        for index, name in enumerate(names)
                    ]
                    original = json.dumps(
                        {"schema_version": 1, "pulls": pulls},
                        ensure_ascii=False,
                        indent=2,
                    )
                    history_path.write_text(original, encoding="utf-8")
                    manager = ConveneStorageManager(history_path)

                    self.assertLess(len(manager.load()), len(pulls))
                    manager.export_tethys_history(export_path)
                    exported = json.loads(export_path.read_text(encoding="utf-8"))

                    self.assertEqual(
                        [pull["name"] for pull in exported["pulls"]],
                        names,
                    )
                    self.assertEqual(len(exported["pulls"]), len(names))
                    self.assertNotIn("local_record_id", export_path.read_text(encoding="utf-8"))
                    self.assertNotIn("dedup_key", export_path.read_text(encoding="utf-8"))
                    self.assertNotIn("private", export_path.read_text(encoding="utf-8"))
                    self.assertEqual(history_path.read_text(encoding="utf-8"), original)

    def test_exported_json_round_trips_all_pools(self) -> None:
        pools = ("resonator", "weapon", "standard_character", "standard_weapon")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "local.json")
            manager.save_context({
                "player_id": "real-player-id",
                "record_id": "record",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
                "card_pool_type": 1,
            })
            manager.merge([
                {
                    **self._portable_pull(
                        pool,
                        f"2026-09-0{index}T10:00:00-05:00",
                        f"Item {index}",
                        3 + index % 3,
                    ),
                    "player_id": "real-player-id",
                }
                for index, pool in enumerate(pools, start=1)
            ])
            first = root / "first.json"
            second = root / "second.json"
            first_export = manager.export_tethys_history(first)
            second_export = manager.export_tethys_history(second)
            self.assertEqual(first_export["pulls"], second_export["pulls"])
            self.assertEqual(first_export["playerId"], second_export["playerId"])

            destination = ConveneStorageManager(root / "destination.json")
            report = destination.import_json_with_report(first)

            self.assertEqual(report.format, "wuwa_tracker")
            self.assertEqual(report.imported_count, 4)
            by_name = {record["name"]: record for record in report.records}
            for index, pool in enumerate(pools, start=1):
                record = by_name[f"Item {index}"]
                self.assertEqual(record["pool"], pool)
                self.assertEqual(record["rarity"], 3 + index % 3)
                self.assertEqual(record["timestamp"], f"2026-09-0{index}T10:00:00-05:00")

    def test_export_maps_known_wuwa_pool_label_and_omits_missing_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "local.json"
            history.write_text(json.dumps({
                "pulls": [{
                    "timestamp": "2026-09-01T10:00:00-05:00",
                    "pool": "Resonators Accurate Modulation",
                    "name": "Known source row",
                    "rarity": 4,
                    "raw": {"cardPoolType": "Resonators Accurate Modulation"},
                }],
            }), encoding="utf-8")
            exported_path = root / "export.json"

            document = ConveneStorageManager(history).export_tethys_history(exported_path)

            self.assertEqual(set(document), {"date", "pulls"})
            self.assertEqual(document["pulls"], [{
                "cardPoolType": 1,
                "time": "2026-09-01T10:00:00-05:00",
                "name": "Known source row",
                "qualityLevel": 4,
            }])

    def test_export_order_uses_the_exact_time_field_and_is_stable_for_ties(self) -> None:
        rows = [
            self._portable_pull(timestamp="2026-09-01T09:00:00-05:00", name="A", time="2026-09-01T11:00:00-05:00"),
            self._portable_pull(timestamp="2026-09-01T12:00:00-05:00", name="B", time="2026-09-01T10:00:00-05:00"),
            self._portable_pull(timestamp="2026-09-01T08:00:00-05:00", name="C", time="2026-09-01T10:00:00-05:00"),
            self._portable_pull(timestamp="2026-09-01T13:00:00-05:00", name="D", time="2026-09-01T09:00:00-05:00"),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            history.write_text(json.dumps({"pulls": rows}), encoding="utf-8")

            document = ConveneStorageManager(history).export_tethys_history(root / "export.json")

            pulls = self._exported_pulls(document)
            self.assertEqual([pull["name"] for pull in pulls], ["D", "B", "C", "A"])
            self.assertEqual(
                [pull["time"] for pull in pulls],
                [
                    "2026-09-01T09:00:00-05:00",
                    "2026-09-01T10:00:00-05:00",
                    "2026-09-01T10:00:00-05:00",
                    "2026-09-01T11:00:00-05:00",
                ],
            )

    def test_export_rejects_invalid_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            history.write_text(json.dumps({"pulls": [
                self._portable_pull(timestamp="not a date"),
            ]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid timestamp"):
                ConveneStorageManager(history).export_tethys_history(root / "export.json")

    def test_export_resource_id_requires_valid_explicit_pull_field(self) -> None:
        individual = _normalize_pull_record({
            **self._portable_pull(),
            "resourceId": 451,
        })
        rows = [
            individual,
            {**self._portable_pull(name="No ID"), "raw": {"resourceId": 452}},
            {**self._portable_pull(name="Generic raw"), "source": "generic", "raw": {"resourceId": 453}},
            *[
                {**self._portable_pull(name=f"Invalid {index}"), "resourceId": value}
                for index, value in enumerate((True, 0, -1, "454", 45.4))
            ],
            {**self._portable_pull(name="Same ID first"), "resourceId": 455},
            {**self._portable_pull(timestamp="2026-09-02T10:00:00-05:00", name="Same ID second"), "resourceId": 455},
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            history.write_text(json.dumps({"pulls": rows}), encoding="utf-8")

            document = ConveneStorageManager(history).export_tethys_history(root / "export.json")

            exported_ids = [pull.get("resourceId") for pull in self._exported_pulls(document)]
            self.assertEqual(exported_ids.count(451), 1)
            self.assertEqual(exported_ids.count(455), 2)
            self.assertEqual(exported_ids.count(None), 7)

    def test_export_selects_context_player_from_mixed_history(self) -> None:
        context = {
            "player_id": "player-1",
            "record_id": "record",
            "server_id": "server",
            "card_pool_id": "pool",
        }
        cases = (
            ("homogeneous", [{**self._portable_pull(), "player_id": "player-1"}], True, True),
            ("untagged", [self._portable_pull()], True, False),
            ("mixed", [
                {**self._portable_pull(), "player_id": "player-1"},
                {**self._portable_pull(timestamp="2026-09-02T10:00:00-05:00"), "player_id": "player-2"},
            ], True, True),
            ("without-context", [{**self._portable_pull(), "player_id": "player-1"}], False, False),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for case_name, rows, has_context, expected in cases:
                with self.subTest(case=case_name):
                    history = root / f"{case_name}.json"
                    payload: dict[str, object] = {"pulls": rows}
                    if has_context:
                        payload["convene_context"] = context
                    original = json.dumps(payload)
                    history.write_text(original, encoding="utf-8")

                    document = ConveneStorageManager(history).export_tethys_history(
                        root / f"{case_name}-export.json"
                    )

                    self.assertEqual("playerId" in document, expected)
                    if case_name == "mixed":
                        pulls = document["pulls"]
                        self.assertIsInstance(pulls, list)
                        if not isinstance(pulls, list):
                            self.fail("exported pulls must be a list")
                        self.assertEqual(len(pulls), 1)
                        first_pull = pulls[0]
                        self.assertIsInstance(first_pull, dict)
                        if not isinstance(first_pull, dict):
                            self.fail("exported pull must be an object")
                        self.assertEqual(first_pull["name"], self._portable_pull()["name"])
                    self.assertEqual(history.read_text(encoding="utf-8"), original)

    def test_export_player_id_requires_nonempty_history_and_valid_context(self) -> None:
        valid_context = {"player_id": "player-1"}
        verified_pull = {**self._portable_pull(), "player_id": "player-1"}
        cases: tuple[tuple[str, object, list[dict[str, object]]], ...] = (
            ("empty-history", valid_context, []),
            ("missing-player", {}, [verified_pull]),
            ("empty-player", {"player_id": "  "}, [verified_pull]),
            ("boolean-player", {"player_id": True}, [verified_pull]),
            ("unsupported-player", {"player_id": 1.5}, [verified_pull]),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for case_name, context, pulls in cases:
                with self.subTest(case=case_name):
                    history = root / f"{case_name}.json"
                    history.write_text(
                        json.dumps({"convene_context": context, "pulls": pulls}),
                        encoding="utf-8",
                    )

                    document = ConveneStorageManager(history).export_tethys_history(
                        root / f"{case_name}-export.json"
                    )

                    self.assertNotIn("playerId", document)

    def test_export_quality_level_validation(self) -> None:
        accepted = ((3, 3), ("4", 4), (5.0, 5))
        rejected: tuple[object, ...] = (True, 0, -1, 4.5, "bad", None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, (source_quality, expected) in enumerate(accepted):
                with self.subTest(quality=source_quality):
                    history = root / f"accepted-{index}.json"
                    history.write_text(json.dumps({"pulls": [
                        self._portable_pull(rarity=source_quality),
                    ]}), encoding="utf-8")

                    document = ConveneStorageManager(history).export_tethys_history(
                        root / f"accepted-{index}-export.json"
                    )

                    self.assertEqual(self._exported_pulls(document)[0]["qualityLevel"], expected)

            for index, source_quality in enumerate(rejected):
                with self.subTest(quality=source_quality):
                    history = root / f"rejected-{index}.json"
                    history.write_text(json.dumps({"pulls": [
                        self._portable_pull(rarity=source_quality),
                    ]}), encoding="utf-8")

                    with self.assertRaisesRegex(ValueError, "quality level"):
                        ConveneStorageManager(history).export_tethys_history(
                            root / f"rejected-{index}-export.json"
                        )

    def test_export_pool_uses_structural_fields_and_rejects_ambiguous_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "history.json"
            rows = [
                self._portable_pull(pool="Resonators Accurate Modulation", name="Weapon master"),
                {**self._portable_pull(name="Weapon master"), "pool": "resonator"},
                {
                    **self._portable_pull(pool="Unlabeled", name="Resonator Master"),
                    "banner": "Weapons Accurate Modulation",
                },
                {
                    **self._portable_pull(pool="Unlabeled", name="Numeric pool source"),
                    "cardPoolType": 4,
                },
            ]
            history.write_text(json.dumps({"pulls": rows}), encoding="utf-8")
            exported = ConveneStorageManager(history).export_tethys_history(root / "export.json")
            self.assertEqual(
                [pull["cardPoolType"] for pull in self._exported_pulls(exported)],
                [1, 1, 2, 4],
            )

            history.write_text(json.dumps({
                "pulls": [self._portable_pull(pool="Special Modulation", name="Weapon Master")],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pool"):
                ConveneStorageManager(history).export_tethys_history(root / "ambiguous.json")

            history.write_text(json.dumps({
                "pulls": [{
                    **self._portable_pull(pool="Resonators Accurate Modulation"),
                    "cardPoolType": 2,
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pool"):
                ConveneStorageManager(history).export_tethys_history(root / "conflict.json")

    def test_import_uses_existing_deduplication_and_preserves_context_and_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "local.json"
            context = {
                "player_id": "local-player",
                "record_id": "local-record",
                "server_id": "server",
                "card_pool_id": "pool-id",
                "language_code": "en",
                "card_pool_type": 1,
            }
            manager = ConveneStorageManager(history)
            manager.save_context(context)
            manager.merge([{
                **self._portable_pull(timestamp="2026-09-01T10:00:00-05:00"),
                "raw": {"keep": True},
            }])
            source = self._source(root, {
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [self._portable_pull()],
            })

            report = manager.import_json_with_report(source)
            second = manager.import_json_with_report(source)
            saved = json.loads(history.read_text(encoding="utf-8"))

            self.assertEqual(report.imported_count, 0)
            self.assertEqual(second.imported_count, 0)
            self.assertEqual(len(second.records), 1)
            self.assertEqual(manager.load_context(), context)
            self.assertEqual(saved["pulls"][0]["raw"], {"keep": True})
            self.assertNotIn("convene_context", json.loads(source.read_text(encoding="utf-8")))

    def test_tethys_format_is_prioritized_over_wuwa_detector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self._source(root, {
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [self._portable_pull(cardPoolType=1, resourceId=77, qualityLevel=5)],
            })
            report = ConveneStorageManager(root / "local.json").import_json_with_report(source)
            self.assertEqual(report.format, "tethys_convene_history")
            self.assertEqual(report.records[0]["pool"], "resonator")
            self.assertNotIn("player_id", report.records[0])

    def test_imported_records_keep_pity_calculation_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pools = ("resonator", "weapon", "standard_character", "standard_weapon")
            source = self._source(root, {
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [
                    self._portable_pull(pool, f"2026-09-0{index}T10:00:00-05:00", f"Pool {index}", 5)
                    for index, pool in enumerate(pools, start=1)
                ],
            })
            report = ConveneStorageManager(root / "local.json").import_tethys_history(source)
            state = calculate_pity_state(report.records)
            self.assertEqual(state.five_star_history, [1, 1, 1, 1])
            self.assertEqual(state.total_registered, 4)
            self.assertEqual((state.resonator, state.weapon, state.standard_character, state.standard_weapon), (0, 0, 0, 0))

    def test_import_rejects_invalid_json_and_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "invalid.json"
            source.write_text("not JSON", encoding="utf-8")
            manager = ConveneStorageManager(root / "local.json")
            with self.assertRaisesRegex(ValueError, "could not be read"):
                manager.import_tethys_history(source)
            source.write_text(json.dumps([]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                manager.import_tethys_history(source)

    def test_import_rejects_missing_or_wrong_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "local.json")
            for payload in (
                {"version": 1, "pulls": []},
                {"format": "other", "version": 1, "pulls": []},
            ):
                source = self._source(root, payload)
                with self.assertRaisesRegex(ValueError, "format"):
                    manager.import_tethys_history(source)

    def test_import_rejects_missing_and_unsupported_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "local.json")
            for version in (None, 0, 2, True, "1"):
                payload: dict[str, object] = {
                    "format": "tethys_convene_history",
                    "pulls": [],
                }
                if version is not None:
                    payload["version"] = version
                source = self._source(root, payload)
                with self.assertRaisesRegex(ValueError, "version"):
                    manager.import_tethys_history(source)

    def test_import_rejects_invalid_pull_structure_and_values(self) -> None:
        invalid_pulls = (
            None,
            "not a list",
            ["not an object"],
            [{"pool": "resonator", "name": "Item", "rarity": 4}],
            [self._portable_pull(pool="unknown")],
            [self._portable_pull(rarity=6)],
            [self._portable_pull(rarity=True)],
            [self._portable_pull(timestamp="not a date")],
            [self._portable_pull(name="  ")],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = ConveneStorageManager(root / "local.json")
            for pulls in invalid_pulls:
                source = self._source(root, {
                    "format": "tethys_convene_history",
                    "version": 1,
                    "pulls": pulls,
                })
                with self.subTest(pulls=pulls), self.assertRaises(ValueError):
                    manager.import_json_with_report(source)

    def test_import_without_existing_context_does_not_create_kuro_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "local.json"
            source = self._source(root, {
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [self._portable_pull()],
            })
            ConveneStorageManager(history).import_tethys_history(source)
            self.assertNotIn("convene_context", json.loads(history.read_text(encoding="utf-8")))

    def test_generic_json_import_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self._source(root, {
                "history": [{
                    "time": "2026-09-01T10:00:00-05:00",
                    "name": "Generic item",
                    "pool": "resonator",
                    "rarity": 5,
                }],
            })
            report = ConveneStorageManager(root / "local.json").import_json_with_report(source)
            self.assertEqual(report.format, "generic")
            self.assertEqual(report.records[0]["name"], "Generic item")


if __name__ == "__main__":
    unittest.main()
