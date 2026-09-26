"""PySide6 application entry point."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.multimedia.ffmpeg=false;qt.network.ssl.warning=false;"
    "qt.core.qiodevice.warning=false",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.settings_store import SettingsStore
from src.wuwa_calculator.app.styles import application_qss
from src.wuwa_calculator.app.window import PlaceholderTab, WuwaQtWindow

if TYPE_CHECKING:
    from src.wuwa_calculator.app.import_dialog import CustomImportPopup

    ImportDialog = CustomImportPopup


def __getattr__(name: str) -> object:
    if name in {"CustomImportPopup", "ImportDialog"}:
        from src.wuwa_calculator.app.import_dialog import CustomImportPopup

        return CustomImportPopup
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), "CustomImportPopup", "ImportDialog"})


def main() -> int:
    performance_debug = (
        "--performance-debug" in sys.argv
        or os.environ.pop("TETHYS_PERFORMANCE_DEBUG", "") == "1"
    )
    process_started_at = 0.0
    if performance_debug:
        start_time = os.environ.pop("TETHYS_PERFORMANCE_START_TIME", "")
        try:
            process_started_at = float(start_time)
        except ValueError:
            process_started_at = time.perf_counter()
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv)
    qapplication_ready_elapsed = None
    if performance_debug:
        qapplication_ready_elapsed = time.perf_counter() - process_started_at
    performance_monitor = None
    if performance_debug:
        if "--performance-debug" in sys.argv:
            sys.argv.remove("--performance-debug")
        from src.wuwa_calculator.app.performance_debug import PerformanceDebugMonitor

        performance_monitor = PerformanceDebugMonitor(app, process_started_at)
        performance_monitor.mark(
            "STARTUP:QAPPLICATION_READY",
            elapsed_since_process_start=qapplication_ready_elapsed,
            measure_cpu=False,
        )
    app.setStyle("Fusion")
    settings = SettingsStore()
    background = settings.get("background", True, bool)
    wallpaper = settings.get("wallpaper", "", str)
    interface_opacity = settings.get("interface_opacity", 85, int)
    accent_theme = settings.get("accent_theme", "Auto Wallpaper", str)
    app.setStyleSheet(application_qss(
        show_background=background,
        wallpaper=wallpaper,
        interface_opacity=interface_opacity,
        accent_theme=accent_theme,
    ))
    startup_marker = (
        performance_monitor.mark if performance_monitor is not None else None
    )
    window = WuwaQtWindow(startup_marker=startup_marker)
    if performance_monitor is not None:
        performance_monitor.attach_window(window)
    from src.wuwa_calculator.app.dev_ipc import DevCommandServer

    dev_command_server = DevCommandServer(
        window.toggle_development_mode,
        parent=app,
    )
    if not dev_command_server.listen():
        print(
            "[Tethys] Não foi possível abrir o canal local de ativação DEV:",
            dev_command_server.error_string,
            file=sys.stderr,
        )
    window.show()
    try:
        return app.exec()
    finally:
        dev_command_server.close()
        if performance_monitor is not None:
            performance_monitor.stop()


if __name__ == "__main__":
    raise SystemExit(main())
