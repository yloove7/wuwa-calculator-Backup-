"""Appearance orchestration for the main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.wuwa_calculator.app.settings_store import SettingsStore
from src.wuwa_calculator.app.styles import (
    accent_preset,
    application_qss,
    refresh_glows,
    wallpaper_palette,
)
from src.wuwa_calculator.utils.paths import get_asset_path


class AppearanceController:
    """Apply saved appearance preferences to a window and its widgets."""

    def __init__(
        self,
        root_widget: QWidget,
        background_label: QLabel,
        settings: SettingsStore,
    ) -> None:
        self.root_widget = root_widget
        self.background_label = background_label
        self.settings = settings
        self._background_cache_key: tuple[str, bool, int, int] | None = None

    def apply(self) -> None:
        self.settings.sync()
        background = self.settings.get("background", True, bool)
        wallpaper = self.settings.get("wallpaper", "", str)
        interface_opacity = self.settings.get("interface_opacity", 85, int)
        accent_theme = self.settings.get("accent_theme", "Auto Wallpaper", str)
        performance_mode = self.settings.get("performance_mode", False, bool)
        app = QApplication.instance()

        palette = wallpaper_palette(wallpaper if background else "")
        effective_accent = (
            palette[3]
            if accent_theme == "Auto Wallpaper"
            else accent_preset(accent_theme)
        )

        if isinstance(app, QApplication):
            app.setStyleSheet(application_qss(
                show_background=background,
                wallpaper=wallpaper,
                interface_opacity=interface_opacity,
                accent_theme=accent_theme,
            ))
        for widget in self.root_widget.findChildren(QWidget):
            apply_palette = getattr(widget, "apply_wallpaper_palette", None)
            if callable(apply_palette):
                apply_palette(*palette, theme_accent=effective_accent)
        refresh_glows(self.root_widget, performance_mode=performance_mode)
        self.update_background(background, wallpaper)

    def update_background(self, enabled: bool, wallpaper: str) -> None:
        self.background_label.setVisible(enabled)
        if not enabled:
            self._background_cache_key = None
            return

        cache_key = (
            wallpaper,
            enabled,
            self.root_widget.width(),
            self.root_widget.height(),
        )
        if cache_key == self._background_cache_key:
            return

        source = QUrl.fromUserInput(wallpaper).toLocalFile() if wallpaper else ""
        default_background = get_asset_path("app_background_reference.png")
        pixmap = QPixmap(source or str(default_background))

        if pixmap.isNull():
            pixmap = QPixmap(str(default_background))
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.root_widget.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (scaled.width() - self.root_widget.width()) // 2)
        top = max(0, (scaled.height() - self.root_widget.height()) // 2)
        self.background_label.setGeometry(self.root_widget.rect())
        self.background_label.setPixmap(
            scaled.copy(
                left,
                top,
                self.root_widget.width(),
                self.root_widget.height(),
            )
        )
        self.background_label.lower()
        self._background_cache_key = cache_key
