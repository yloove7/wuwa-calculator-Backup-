"""Persistent application preference storage."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings


class SettingsStore:
    """Small wrapper around the application's existing QSettings store."""

    def __init__(
        self,
        organization: str = "Tethys",
        application: str = "Tethys",
        settings: QSettings | None = None,
    ) -> None:
        self._settings = settings or QSettings(organization, application)

    def get(self, key: str, default: Any = None, value_type: type | None = None) -> Any:
        if value_type is None:
            return self._settings.value(key, default)
        return self._settings.value(key, default, type=value_type)

    def set(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)

    def remove(self, key: str) -> None:
        self._settings.remove(key)

    def sync(self) -> None:
        self._settings.sync()
