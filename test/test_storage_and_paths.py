import tempfile
import json
import unittest
from pathlib import Path

from src.wuwa_calculator.storage.history_storage import (
    export_rotation_history,
    import_rotation_history,
    load_rotation_history,
    save_rotation_test,
)
from src.wuwa_calculator.storage.team_storage import load_teams, save_teams
from src.wuwa_calculator.utils.paths import ASSETS_ROOT, PROJECT_ROOT, USER_DATA_ROOT, get_asset_path


class PathsAndStorageTests(unittest.TestCase):
    def test_project_paths_are_rooted_at_repository(self) -> None:
        self.assertEqual(PROJECT_ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual(get_asset_path("sample.png"), ASSETS_ROOT / "sample.png")
        self.assertEqual(USER_DATA_ROOT.parent.name, "storage")

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


if __name__ == "__main__":
    unittest.main()
