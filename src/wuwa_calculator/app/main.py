"""PySide6 application entry point."""

from __future__ import annotations

import os
import sys
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
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv)
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
    window = WuwaQtWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
