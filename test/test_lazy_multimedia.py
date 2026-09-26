from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path
from collections.abc import Generator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QSettings, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

from src.wuwa_calculator.app import pity_tracker
from src.wuwa_calculator.app import window as window_module
from src.wuwa_calculator.app.capture.settings import CaptureSettings
from src.wuwa_calculator.domain.pity import PityState
from src.wuwa_calculator.storage.convene_storage import (
    CONVENE_HISTORY_FILE,
    ConveneStorageManager,
)
from src.wuwa_calculator.app.obs_test_tab import ObsTestTab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_APPLICATION = QApplication.instance() or QApplication([])


class _HomeTab(QWidget):
    shutdown_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.active_states: list[bool] = []
        self.window_states: list[bool] = []
        self.performance_states: list[bool] = []

    def shutdown_workers(self) -> bool:
        return True

    def set_active(self, active: bool) -> None:
        self.active_states.append(active)

    def set_window_visible(self, visible: bool) -> None:
        self.window_states.append(visible)

    def set_performance_mode(self, enabled: bool) -> None:
        self.performance_states.append(enabled)


class _ConveneBackend:
    def shutdown_workers(self) -> bool:
        return True


@pytest.fixture
def window(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[window_module.WuwaQtWindow, None, None]:
    monkeypatch.setattr(window_module, "HomeTab", _HomeTab)
    monkeypatch.setattr(
        pity_tracker,
        "LegacyPityTrackerWidget",
        _ConveneBackend,
    )
    preferences = QSettings("Tethys", "Tethys")
    preferences.setValue("auto_open_last_character", False)
    preferences.setValue("confirm_exit", False)
    instance = window_module.WuwaQtWindow()
    yield instance
    instance._close_confirmation_accepted = True
    instance.close()
    instance.deleteLater()
    _APPLICATION.processEvents()


@pytest.fixture
def real_convene_window(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[
    tuple[
        window_module.WuwaQtWindow,
        list[pity_tracker.LegacyPityTrackerWidget],
        list[bool],
        list[str],
    ],
    None,
    None,
]:
    monkeypatch.setattr(window_module, "HomeTab", _HomeTab)
    backend_type = pity_tracker.LegacyPityTrackerWidget
    backends: list[pity_tracker.LegacyPityTrackerWidget] = []
    shutdown_results: list[bool] = []
    storage_reads: list[str] = []
    original_load = ConveneStorageManager.load
    original_load_context = ConveneStorageManager.load_context
    original_load_for_player = ConveneStorageManager.load_for_player

    def track_load(manager: ConveneStorageManager) -> list[dict[str, object]]:
        storage_reads.append("history")
        return original_load(manager)

    def track_load_context(
        manager: ConveneStorageManager,
    ) -> dict[str, object] | None:
        storage_reads.append("context")
        return original_load_context(manager)

    def track_load_for_player(
        manager: ConveneStorageManager,
        player_id: str,
    ) -> list[dict[str, object]]:
        storage_reads.append("player_history")
        return original_load_for_player(manager, player_id)

    monkeypatch.setattr(ConveneStorageManager, "load", track_load)
    monkeypatch.setattr(ConveneStorageManager, "load_context", track_load_context)
    monkeypatch.setattr(
        ConveneStorageManager,
        "load_for_player",
        track_load_for_player,
    )

    class CountingBackend(backend_type):
        def __init__(self) -> None:
            super().__init__()
            backends.append(self)

        def shutdown_workers(self, timeout_ms: int = 5000) -> bool:
            result = super().shutdown_workers(timeout_ms)
            shutdown_results.append(result)
            return result

    monkeypatch.setattr(pity_tracker, "LegacyPityTrackerWidget", CountingBackend)
    preferences = QSettings("Tethys", "Tethys")
    preferences.setValue("auto_open_last_character", False)
    preferences.setValue("confirm_exit", False)
    instance = window_module.WuwaQtWindow()
    yield instance, backends, shutdown_results, storage_reads
    instance._close_confirmation_accepted = True
    instance.close()
    instance.deleteLater()
    _APPLICATION.processEvents()


def test_window_import_does_not_load_multimedia_or_pyqtgraph() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    script = (
        "import sys; "
        "import src.wuwa_calculator.app.main as app_main; "
        "assert 'src.wuwa_calculator.app.multimedia.multimedia_tab' not in sys.modules; "
        "assert 'src.wuwa_calculator.app.multimedia.dps_simulation_panel' not in sys.modules; "
        "assert 'src.wuwa_calculator.app.import_dialog' not in sys.modules; "
        "assert 'src.wuwa_calculator.app.characters.resonator_tab' not in sys.modules; "
        "assert 'pyqtgraph' not in sys.modules; "
        "from src.wuwa_calculator.app.main import ImportDialog, CustomImportPopup; "
        "assert ImportDialog is CustomImportPopup; "
        "assert app_main.ImportDialog is CustomImportPopup; "
        "assert 'src.wuwa_calculator.app.import_dialog' in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_multimedia_is_created_once_with_the_normal_player_and_dps_initialization(
    window: window_module.WuwaQtWindow,
) -> None:
    from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab

    assert 4 not in window._tab_widgets

    window.tabs.setCurrentIndex(4)
    multimedia = window._tab_widgets[4]
    assert isinstance(multimedia, MultimediaTab)
    assert isinstance(multimedia.video_player, QWidget)
    assert multimedia.video_player.progress_slider.minimum() == 0
    assert multimedia.video_player.progress_slider.maximum() == 0
    assert multimedia.dps_panel.modo_analise == "VIDEO"
    assert multimedia.dps_panel.analysis_source.currentIndex() == 0
    assert multimedia.dps_panel.capture_settings == CaptureSettings()

    window.tabs.setCurrentIndex(0)
    window.tabs.setCurrentIndex(4)

    assert window._tab_widgets[4] is multimedia
    assert multimedia.updatesEnabled()


def test_ipc_dev_activation_unlocks_only_frequencies_without_recreating_media(
    window: window_module.WuwaQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab

    monkeypatch.setattr(window.appearance, "apply", lambda: None)
    performance_mode = [True]
    get_setting = window.settings.get
    monkeypatch.setattr(
        window.settings,
        "get",
        lambda key, default=None, value_type=None: (
            performance_mode[0]
            if key == "performance_mode"
            else get_setting(key, default, value_type)
        ),
    )
    window.apply_preferences()
    assert not window._dev_mode_enabled
    assert not window._dev_frequencies_override
    assert not window.tabs.isTabEnabled(4)
    assert not window._sidebar_buttons_by_tab[4].isEnabled()

    # Programmatic construction proves that old saved DEV keys cannot unlock it.
    window._ensure_main_tab(4)
    multimedia = window._tab_widgets[4]
    assert isinstance(multimedia, MultimediaTab)
    player = multimedia.video_player
    assert not multimedia._maintenance_overlay.isHidden()

    assert window.toggle_development_mode() is True

    assert window._dev_mode_enabled
    assert window._dev_frequencies_override
    assert window.settings.get("performance_mode", False, bool)
    assert multimedia._maintenance_overlay.isHidden()
    assert window.tabs.isTabEnabled(4)
    assert window._sidebar_buttons_by_tab[4].isEnabled()
    assert multimedia.dps_panel._performance_mode is True
    assert window._tab_widgets[4] is multimedia
    assert multimedia.video_player is player

    assert window.toggle_development_mode() is False
    assert not window._dev_mode_enabled
    assert not window._dev_frequencies_override
    assert not multimedia._maintenance_overlay.isHidden()
    assert not window.tabs.isTabEnabled(4)
    assert not window._sidebar_buttons_by_tab[4].isEnabled()
    assert window._tab_widgets[4] is multimedia
    assert multimedia.video_player is player

    performance_mode[0] = False
    window.apply_preferences()
    assert multimedia.dps_panel._performance_mode is False
    assert not multimedia._maintenance_overlay.isHidden()
    assert not window.tabs.isTabEnabled(4)
    assert not window._sidebar_buttons_by_tab[4].isEnabled()

    assert window.toggle_development_mode() is True
    assert multimedia._maintenance_overlay.isHidden()
    assert window.tabs.isTabEnabled(4)
    assert window._sidebar_buttons_by_tab[4].isEnabled()
    assert multimedia.dps_panel._performance_mode is False

    assert window.toggle_development_mode() is False
    assert not multimedia._maintenance_overlay.isHidden()
    assert not window.tabs.isTabEnabled(4)
    assert not window._sidebar_buttons_by_tab[4].isEnabled()


def test_resonator_tab_is_created_once_and_reused_after_returning_home(
    window: window_module.WuwaQtWindow,
) -> None:
    assert window.character_tabs == {}

    window.character_id_entry.setText("jiyan")
    window.open_character_tab()
    resonator = window.character_tabs["jiyan"]
    assert window.tabs.currentWidget() is resonator

    window.tabs.setCurrentIndex(0)
    window.character_id_entry.setText("jiyan")
    window.open_character_tab()

    assert window.character_tabs["jiyan"] is resonator
    assert window.tabs.currentWidget() is resonator


def test_import_dialog_module_loads_when_dialog_is_first_opened(
    window: window_module.WuwaQtWindow,
) -> None:
    from PySide6.QtWidgets import QDialog

    window.character_id_entry.setText("jiyan")
    window.open_character_tab()
    window.open_import_dialog()

    dialog = window._import_dialog
    assert isinstance(dialog, QDialog)
    assert "src.wuwa_calculator.app.import_dialog" in sys.modules
    assert dialog is not None
    dialog.close()


def test_window_minimize_state_is_forwarded_to_home(
    window: window_module.WuwaQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = window._tab_widgets[0]
    assert isinstance(home, _HomeTab)
    monkeypatch.setattr(window, "isMinimized", lambda: True)

    window.changeEvent(QEvent(QEvent.Type.WindowStateChange))

    assert home.window_states == [False]
    monkeypatch.setattr(window, "isMinimized", lambda: False)
    window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    assert home.window_states == [False, True]


def test_obs_settings_applied_before_multimedia_creation_are_replayed(
    window: window_module.WuwaQtWindow,
) -> None:
    obs_tab = window._tab_widgets[5]
    assert isinstance(obs_tab, ObsTestTab)
    obs_tab.capture_cursor.setChecked(True)
    obs_tab._emit_settings()
    expected_settings = window._capture_settings

    window.tabs.setCurrentIndex(4)

    multimedia = window._tab_widgets[4]
    from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab

    assert isinstance(multimedia, MultimediaTab)
    assert multimedia.dps_panel.capture_settings is expected_settings
    assert multimedia.dps_panel.capture_settings.capture_cursor


def test_close_without_visiting_multimedia_does_not_shutdown_missing_widget(
    window: window_module.WuwaQtWindow,
) -> None:
    assert 4 not in window._tab_widgets

    window._close_confirmation_accepted = True
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert 4 not in window._tab_widgets


def test_close_after_multimedia_creation_runs_its_existing_shutdown(
    window: window_module.WuwaQtWindow,
) -> None:
    window.tabs.setCurrentIndex(4)
    multimedia = window._tab_widgets[4]
    from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab

    assert isinstance(multimedia, MultimediaTab)
    window._close_confirmation_accepted = True
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    assert multimedia.video_player.media_player.playbackState().name == "StoppedState"


def test_convene_backend_is_lazy_singleton_and_shared_with_its_tab(
    real_convene_window: tuple[
        window_module.WuwaQtWindow,
        list[pity_tracker.LegacyPityTrackerWidget],
        list[bool],
        list[str],
    ],
) -> None:
    from src.wuwa_calculator.app.convene.convene_tracker_tab import ConveneTrackerTab

    window, backends, _shutdown_results, storage_reads = real_convene_window
    assert backends == []
    assert storage_reads == []
    assert window._convene_tracker_backend is None
    assert 1 not in window._tab_widgets

    window.tabs.setCurrentIndex(1)

    assert len(backends) == 1
    backend = backends[0]
    tab = window._tab_widgets[1]
    assert isinstance(tab, ConveneTrackerTab)
    assert tab.tracker is backend
    assert window.convene_tracker_backend is backend

    window.tabs.setCurrentIndex(0)
    window.tabs.setCurrentIndex(1)

    assert len(backends) == 1
    assert window._tab_widgets[1] is tab
    assert tab.tracker is backend


def test_lazy_convene_loads_player_history_state_and_keeps_tab_signals_connected(
    real_convene_window: tuple[
        window_module.WuwaQtWindow,
        list[pity_tracker.LegacyPityTrackerWidget],
        list[bool],
        list[str],
    ],
) -> None:
    from src.wuwa_calculator.app.convene.convene_tracker_tab import ConveneTrackerTab

    window, backends, _shutdown_results, storage_reads = real_convene_window
    storage = ConveneStorageManager()
    assert storage.path.resolve() != CONVENE_HISTORY_FILE.resolve()
    storage.path.write_text(
        json.dumps(
            {
                "convene_context": {
                    "player_id": "500448647",
                    "record_id": "record-1",
                    "server_id": "server-1",
                    "card_pool_id": "pool-1",
                    "language_code": "en",
                },
                "pulls": [
                    {
                        "player_id": "500448647",
                        "timestamp": "2026-09-20T12:00:00Z",
                        "pool": "resonator",
                        "name": "Test Resonator",
                        "rarity": 5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    window.tabs.setCurrentIndex(1)

    assert len(backends) == 1
    assert "context" in storage_reads
    assert "player_history" in storage_reads
    backend = backends[0]
    tab = window._tab_widgets[1]
    assert isinstance(tab, ConveneTrackerTab)
    assert backend.active_player_id == "500448647"
    assert len(backend.history_records) == 1
    assert backend.state.total_registered == 1
    assert tab.tracker is backend
    assert tab.summary_values["total"].text() == "1"
    assert tab.history_table.rowCount() == 1

    backend.state.total_registered = 9
    backend.state_changed.emit(backend.state)
    assert tab.summary_values["total"].text() == "9"

    backend.tracker_status = pity_tracker.TrackerStatus(
        sync_status="success",
        new_records_count=2,
    )
    backend.status_changed.emit(backend.tracker_status)
    assert "2 novos registros" in tab.status_message_label.text()

    backend.history_records.append(
        {
            "player_id": "500448647",
            "timestamp": "2026-09-20T12:01:00Z",
            "pool": "resonator",
            "name": "Second Resonator",
            "rarity": 4,
        }
    )
    backend.history_changed.emit(backend.history_records)
    assert tab.history_table.rowCount() == 2


def test_convene_shutdown_is_skipped_before_creation_and_runs_after_creation(
    real_convene_window: tuple[
        window_module.WuwaQtWindow,
        list[pity_tracker.LegacyPityTrackerWidget],
        list[bool],
        list[str],
    ],
) -> None:
    window, backends, shutdown_results, storage_reads = real_convene_window
    window._close_confirmation_accepted = True
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    assert backends == []
    assert shutdown_results == []
    assert storage_reads == []

    window.tabs.setCurrentIndex(1)
    event_after_open = QCloseEvent()
    window.closeEvent(event_after_open)

    assert event_after_open.isAccepted()
    assert len(backends) == 1
    assert shutdown_results == [True]
