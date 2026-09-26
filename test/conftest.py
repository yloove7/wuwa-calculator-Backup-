"""Keep test-created Convene storage away from the real user history."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.wuwa_calculator.app.capture.learning import profile as learning_profile
from src.wuwa_calculator.app.capture.learning.profile import LearningStore
from src.wuwa_calculator.app import backend_adapter, history_tab
from src.wuwa_calculator.storage import banner_cache, history_storage, team_storage
from src.wuwa_calculator.storage.convene_storage import (
    CONVENE_HISTORY_FILE,
    ConveneStorageManager,
)


@pytest.fixture(autouse=True)
def redirect_real_convene_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect every manager targeting the application history into tmp_path."""
    real_history_path = CONVENE_HISTORY_FILE.resolve()
    original_init = ConveneStorageManager.__init__

    def isolated_init(
        manager: ConveneStorageManager,
        path: Path = CONVENE_HISTORY_FILE,
    ) -> None:
        selected_path = Path(path)
        if selected_path.resolve() == real_history_path:
            selected_path = tmp_path / "convene_history.json"
        original_init(manager, selected_path)

    monkeypatch.setattr(ConveneStorageManager, "__init__", isolated_init)


@pytest.fixture(autouse=True)
def redirect_other_user_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tests away from repository and platform user-data directories."""
    legacy_user_data = tmp_path / "legacy_user_data"
    legacy_data = tmp_path / "legacy_data"

    teams_path = tmp_path / "teams.json"
    monkeypatch.setattr(team_storage, "TEAMS_FILE", teams_path)
    monkeypatch.setattr(team_storage, "LEGACY_USER_DATA_ROOT", legacy_user_data)
    monkeypatch.setattr(team_storage, "LEGACY_DATA_ROOT", legacy_data)
    monkeypatch.setattr(team_storage.load_teams, "__defaults__", (teams_path,))
    monkeypatch.setattr(team_storage.save_teams, "__defaults__", (teams_path,))

    rotations_path = tmp_path / "rotation_history.json"
    monkeypatch.setattr(history_storage, "ROTATION_HISTORY_FILE", rotations_path)
    monkeypatch.setattr(history_storage, "LEGACY_USER_DATA_ROOT", legacy_user_data)
    monkeypatch.setattr(history_storage, "LEGACY_DATA_ROOT", legacy_data)
    monkeypatch.setattr(
        history_storage.load_rotation_document,
        "__defaults__",
        (rotations_path,),
    )
    monkeypatch.setattr(
        history_storage.save_rotation_document,
        "__defaults__",
        (rotations_path,),
    )
    monkeypatch.setattr(
        history_storage.load_rotation_history,
        "__defaults__",
        (rotations_path,),
    )
    monkeypatch.setattr(
        history_storage.load_rotation_teams,
        "__defaults__",
        (rotations_path,),
    )
    save_rotation_defaults = history_storage.save_rotation_test.__defaults__
    if save_rotation_defaults is not None:
        monkeypatch.setattr(
            history_storage.save_rotation_test,
            "__defaults__",
            (
                save_rotation_defaults[0],
                rotations_path,
                *save_rotation_defaults[2:],
            ),
        )
    monkeypatch.setattr(
        history_storage.import_rotation_history,
        "__defaults__",
        (rotations_path,),
    )
    monkeypatch.setattr(
        history_storage.export_rotation_history,
        "__defaults__",
        (rotations_path, None),
    )
    monkeypatch.setattr(backend_adapter, "ROTATION_HISTORY_FILE", rotations_path)
    monkeypatch.setattr(history_tab, "HISTORY_FILE", rotations_path)
    monkeypatch.setattr(backend_adapter.history_records, "__defaults__", (rotations_path,))
    monkeypatch.setattr(backend_adapter.history_teams, "__defaults__", (rotations_path,))
    save_history_defaults = backend_adapter.save_history_record.__defaults__
    if save_history_defaults is not None:
        monkeypatch.setattr(
            backend_adapter.save_history_record,
            "__defaults__",
            (
                save_history_defaults[0],
                rotations_path,
                *save_history_defaults[2:],
            ),
        )
    monkeypatch.setattr(
        backend_adapter.import_history_file,
        "__defaults__",
        (rotations_path,),
    )
    monkeypatch.setattr(
        backend_adapter.export_history_file,
        "__defaults__",
        (rotations_path, None),
    )

    monkeypatch.setattr(banner_cache, "CACHE_FILE", tmp_path / "current_banner.json")
    monkeypatch.setattr(
        learning_profile,
        "LEGACY_USER_DATA_ROOT",
        legacy_user_data,
    )
    learning_profile_path = (
        tmp_path / "capture_learning" / "damage_profiles.json"
    )
    monkeypatch.setattr(
        learning_profile,
        "LEARNING_PROFILE_FILE",
        learning_profile_path,
    )
    monkeypatch.setattr(
        LearningStore,
        "PATH",
        learning_profile_path,
    )
    monkeypatch.setattr(
        learning_profile,
        "LEARNING_PROFILE_FILE",
        tmp_path / "capture_learning" / "damage_profiles.json",
    )
