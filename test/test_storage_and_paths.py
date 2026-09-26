import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.wuwa_calculator.storage.history_storage import (
    export_rotation_history,
    import_rotation_history,
    load_rotation_history,
    save_rotation_test,
)
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager
from src.wuwa_calculator.storage import convene_storage
from src.wuwa_calculator.storage import history_storage, team_storage
from src.wuwa_calculator.app.capture.learning import profile as learning_profile
from src.wuwa_calculator.app.capture.learning.profile import LearningStore
from src.wuwa_calculator.storage.team_storage import load_teams, save_teams
from src.wuwa_calculator.utils.paths import (
    ASSETS_ROOT,
    PACKAGE_ROOT,
    PROJECT_ROOT,
    USER_DATA_ROOT,
    copy_legacy_user_data_file,
    get_asset_path,
)


class PathsAndStorageTests(unittest.TestCase):
    def test_project_paths_are_rooted_at_repository(self) -> None:
        self.assertEqual(PROJECT_ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual(get_asset_path("sample.png"), ASSETS_ROOT / "sample.png")
        self.assertFalse(USER_DATA_ROOT.is_relative_to(PACKAGE_ROOT))

    def test_legacy_user_data_copy_is_byte_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "legacy" / "convene_history.json"
            destination = root / "new" / "convene_history.json"
            original_bytes = b'{ "pulls": [1, 2, 3] }\r\n'
            source.parent.mkdir()
            source.write_bytes(original_bytes)

            self.assertTrue(copy_legacy_user_data_file(source, destination))
            self.assertFalse(copy_legacy_user_data_file(source, destination))
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(destination.read_bytes(), original_bytes)

    def test_legacy_user_data_copy_does_not_overwrite_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "legacy.json"
            destination = root / "user" / "history.json"
            source.write_bytes(b'{"pulls":["legacy"]}')
            destination.parent.mkdir()
            destination.write_bytes(b"not valid json")

            self.assertFalse(copy_legacy_user_data_file(source, destination))
            self.assertEqual(source.read_bytes(), b'{"pulls":["legacy"]}')
            self.assertEqual(destination.read_bytes(), b"not valid json")

    def test_legacy_user_data_copy_without_source_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "new" / "history.json"

            self.assertFalse(copy_legacy_user_data_file(root / "missing.json", destination))
            self.assertFalse(destination.exists())

    def test_convene_manager_migrates_legacy_file_on_first_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "legacy" / "convene_history.json"
            destination = root / "user" / "convene_history.json"
            original_bytes = b'{"pulls": [{"seq_id": "legacy"}]}'
            source.parent.mkdir()
            source.write_bytes(original_bytes)

            with (
                patch.object(convene_storage, "CONVENE_HISTORY_FILE", destination),
                patch.object(convene_storage, "LEGACY_CONVENE_HISTORY_FILE", source),
            ):
                manager = ConveneStorageManager(destination)

            self.assertEqual(manager.load()[0]["seq_id"], "legacy")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(destination.read_bytes(), original_bytes)

    def test_team_storage_migrates_existing_user_data_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "legacy_user_data"
            source = source_root / "teams.json"
            destination = root / "user" / "teams.json"
            original_bytes = b'[{"name":"Saved team","characters":["Jinhsi"]}]'
            source_root.mkdir()
            source.write_bytes(original_bytes)

            with (
                patch.object(team_storage, "TEAMS_FILE", destination),
                patch.object(team_storage, "LEGACY_USER_DATA_ROOT", source_root),
                patch.object(team_storage, "LEGACY_DATA_ROOT", root / "legacy_data"),
            ):
                loaded = team_storage.load_teams(destination)

            self.assertEqual(loaded[0]["name"], "Saved team")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(destination.read_bytes(), original_bytes)

    def test_rotation_history_migrates_existing_user_data_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "legacy_user_data"
            source = source_root / "rotation_history.json"
            destination = root / "user" / "rotation_history.json"
            original_bytes = (
                b'{"schema_version":2,"teams":[],"rotations":'
                b'[{"id":4,"team":"Saved team","damage":55}],"comparisons":[]}'
            )
            source_root.mkdir()
            source.write_bytes(original_bytes)

            with (
                patch.object(history_storage, "ROTATION_HISTORY_FILE", destination),
                patch.object(history_storage, "LEGACY_USER_DATA_ROOT", source_root),
                patch.object(history_storage, "LEGACY_DATA_ROOT", root / "legacy_data"),
            ):
                loaded = history_storage.load_rotation_document(destination)

            rotations = loaded.get("rotations")
            assert isinstance(rotations, list) and rotations
            assert isinstance(rotations[0], dict)
            self.assertEqual(rotations[0].get("id"), 4)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(destination.read_bytes(), original_bytes)

    def test_learning_profile_migrates_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "legacy_user_data"
            source = source_root / "capture_learning" / "damage_profiles.json"
            destination = root / "user" / "capture_learning" / "damage_profiles.json"
            original_bytes = (
                b'{"damage-window":{"confirmed_events":9,"widths":[42],'
                b'"heights":[24],"color_scores":[0.9]}}'
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(original_bytes)

            with (
                patch.object(learning_profile, "LEGACY_USER_DATA_ROOT", source_root),
                patch.object(learning_profile, "LEARNING_PROFILE_FILE", destination),
                patch.object(LearningStore, "PATH", destination),
            ):
                store = LearningStore()
                profile = store.profile("damage-window")

            self.assertEqual(profile.confirmed_events, 9)
            self.assertEqual(profile.widths, [42.0])
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(destination.read_bytes(), original_bytes)

    def test_user_data_migration_io_errors_do_not_block_storage_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            legacy_root = root / "legacy"
            legacy_root.mkdir()
            (legacy_root / "teams.json").write_text("[]", encoding="utf-8")
            team_destination = root / "user" / "teams.json"

            with (
                patch.object(team_storage, "TEAMS_FILE", team_destination),
                patch.object(team_storage, "LEGACY_USER_DATA_ROOT", legacy_root),
                patch.object(team_storage, "LEGACY_DATA_ROOT", root / "old_data"),
                patch.object(
                    team_storage,
                    "copy_legacy_user_data_file",
                    side_effect=OSError("read-only destination"),
                ),
            ):
                self.assertEqual(team_storage.load_teams(team_destination), team_storage.DEFAULT_TEAMS)

            self.assertEqual((legacy_root / "teams.json").read_text(encoding="utf-8"), "[]")
            self.assertFalse(team_destination.exists())

    def test_team_storage_round_trip_uses_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "teams.json"
            teams = [{"name": "Test team", "characters": ["Augusta"]}]

            save_teams(teams, path)

            self.assertEqual(load_teams(path), teams)

    def test_history_storage_round_trip_uses_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rotation_history.json"

            record = save_rotation_test(
                "Test team",
                "Test rotation",
                damage=123.5,
                path=path,
            )

            self.assertEqual(load_rotation_history(path), [record])

    def test_history_import_and_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.json"
            destination = root / "history.json"
            exported = root / "exported.json"
            source.write_text(json.dumps({
                "teams": [{"name": "Imported team"}],
                "rotations": [{"team": "Imported team", "rotation": "Burst", "damage": 250}],
            }), encoding="utf-8")

            imported = import_rotation_history(source, destination)
            export_rotation_history(destination, exported)

            self.assertEqual(len(imported), 1)
            self.assertEqual(load_rotation_history(exported)[0]["damage"], 250.0)

    def test_history_import_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "invalid.json"
            destination = Path(temporary_directory) / "history.json"
            source.write_text("not json", encoding="utf-8")

            with self.assertRaises(ValueError):
                import_rotation_history(source, destination)

    def test_convene_storage_merges_duplicate_pulls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "convene_history.json"
            storage = ConveneStorageManager(path)
            first = storage.merge([
                {"seq_id": "1", "name": "Echo"},
                {"seq_id": "2", "name": "Weapon"},
            ])
            second = storage.merge([
                {"seq_id": "2", "name": "Weapon"},
                {"seq_id": "3", "name": "Character"},
            ])

            self.assertEqual(len(first), 2)
            self.assertEqual(len(second), 3)
            self.assertEqual(len(storage.load()), 3)

    def test_convene_storage_imports_backup_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "backup.json"
            destination = root / "convene_history.json"
            source.write_text(json.dumps({
                "history": [{
                    "time": "2026-01-01",
                    "name": "Jingran",
                    "pool": "resonator",
                    "rarity": 5,
                }],
            }), encoding="utf-8")

            imported = ConveneStorageManager(destination).import_json(source)

            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["name"], "Jingran")

    def test_convene_storage_ignores_empty_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "convene_history.json"
            path.touch()

            self.assertEqual(ConveneStorageManager(path).load(), [])
            with self.assertRaisesRegex(ValueError, "vazio"):
                ConveneStorageManager(path).import_json(path)


if __name__ == "__main__":
    unittest.main()
