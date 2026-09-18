import tempfile
import unittest
from pathlib import Path

from src.wuwa_calculator.storage.history_storage import (
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


if __name__ == "__main__":
    unittest.main()
