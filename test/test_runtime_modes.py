from __future__ import annotations

import csv
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

from src.wuwa_calculator.app.dev_mode import frequencies_should_be_blocked
from src.wuwa_calculator.app.dialogs.settings_dialog import SettingsTab
from src.wuwa_calculator.app.performance_debug import PerformanceDebugMonitor
from src.wuwa_calculator.app.settings_store import SettingsStore

_existing_application = QApplication.instance()
_APPLICATION = (
    _existing_application
    if isinstance(_existing_application, QApplication)
    else QApplication([])
)


class _SettingsHost(QWidget):
    def __init__(self, settings: SettingsStore, preferences: QSettings) -> None:
        super().__init__()
        self.settings = settings
        self.preferences = preferences
        self.apply_count = 0

    def apply_preferences(self) -> None:
        self.apply_count += 1

    def clear_character_tabs(self) -> None:
        pass


def test_frequency_access_policy_matrix() -> None:
    cases = (
        (False, False, True),
        (False, True, True),
        (True, False, True),
        (True, True, False),
    )
    for dev_mode, unlock, expected_blocked in cases:
        assert frequencies_should_be_blocked(
            dev_mode, unlock
        ) is expected_blocked


def test_settings_keep_fast_startup_light_mode_and_dev_independent(
    tmp_path: Path,
) -> None:
    preferences = QSettings(
        str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat
    )
    store = SettingsStore(settings=preferences)
    store.set("dev_mode", True)
    store.set("dev_unlock_frequencies", True)
    host = _SettingsHost(store, preferences)
    tab = SettingsTab(host=host, settings=store, preferences=preferences)

    assert not tab.fast_startup_box.isChecked()
    assert not tab.performance_mode_box.isChecked()
    visible_checkbox_labels = {
        checkbox.text() for checkbox in tab.findChildren(QCheckBox)
    }
    assert "Modo DEV" not in visible_checkbox_labels
    assert "Desbloquear Frequências" not in visible_checkbox_labels
    assert not hasattr(tab, "dev_mode_box")
    assert not hasattr(tab, "unlock_frequencies_box")

    tab.fast_startup_box.setChecked(True)
    assert store.get("fast_startup", False, bool)
    assert not store.get("performance_mode", False, bool)

    tab.performance_mode_box.setChecked(True)
    assert store.get("performance_mode", False, bool)
    assert store.get("fast_startup", False, bool)

    assert store.get("dev_mode", False, bool)
    assert store.get("dev_unlock_frequencies", False, bool)
    assert store.get("performance_mode", False, bool)
    assert store.get("fast_startup", False, bool)
    assert host.apply_count > 0
    tab.deleteLater()
    host.deleteLater()


def test_performance_debug_writes_process_samples_to_requested_temp_directory(
    tmp_path: Path,
) -> None:
    monitor = PerformanceDebugMonitor(
        _APPLICATION,
        process_started_at=0.0,
        output_dir=tmp_path,
    )
    monitor.mark("STARTUP:TEST_MILESTONE")
    monitor.stop()

    with monitor.csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["state"] == "STARTUP:INSTRUMENTATION_READY"
    assert rows[1]["state"] == "STARTUP:TEST_MILESTONE"
    assert rows[1]["widget_count"]
    assert {
        "cpu_percent", "rss_mb", "private_mb", "virtual_mb", "threads",
        "elapsed_since_process_start_s", "performance_mode", "fast_startup",
    } <= set(rows[0])
