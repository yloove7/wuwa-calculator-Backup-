from pathlib import Path

from src.wuwa_calculator.storage.convene_storage import (
    CONVENE_HISTORY_FILE,
    ConveneStorageManager,
)


def test_manager_cannot_target_the_real_convene_history_during_pytest(
    tmp_path: Path,
) -> None:
    manager = ConveneStorageManager(CONVENE_HISTORY_FILE)

    assert manager.path == tmp_path / "convene_history.json"
    assert manager.path.resolve() != CONVENE_HISTORY_FILE.resolve()
