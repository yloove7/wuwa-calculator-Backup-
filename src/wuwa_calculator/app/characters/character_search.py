"""Character search history, matching, and popup behavior."""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
import weakref
from collections.abc import Callable, Collection, Mapping

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class CharacterSearchController:
    """Own character search state and its popup without owning the Window."""

    def __init__(
        self,
        preferences: QSettings,
        search_input: QLineEdit,
        known_character_ids: Collection[str],
        character_elements: Mapping[str, str],
        element_icon: Callable[[str | None], str],
        on_character_selected: Callable[[str], None],
    ) -> None:
        self.preferences = preferences
        self.search_input = search_input
        self.known_character_ids = known_character_ids
        self.character_elements = character_elements
        self.element_icon = element_icon
        if getattr(on_character_selected, "__self__", None) is not None:
            self._on_character_selected = weakref.WeakMethod(
                on_character_selected
            )
        else:
            self._on_character_selected = on_character_selected
        self.character_recent_searches: list[str] = []
        self.character_view_counts: dict[str, int] = {}
        self._character_search_popup: QFrame | None = None
        self._load_character_search_data()
        self.search_input.textChanged.connect(self._on_text_changed)

    @staticmethod
    def normalize_character_id(value: str) -> str:
        folded = "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", "", folded)

    def _load_character_search_data(self) -> None:
        recent = self.preferences.value("character_search_recent", [])
        if isinstance(recent, str):
            try:
                recent = json.loads(recent)
            except (TypeError, ValueError):
                recent = []
        if not isinstance(recent, list):
            recent = []
        self.character_recent_searches = [
            str(item) for item in recent if str(item).strip()
        ][:10]

        viewed_raw = self.preferences.value(
            "character_search_viewed", "{}", type=str
        )
        if not isinstance(viewed_raw, str):
            viewed_raw = "{}"
        try:
            viewed = json.loads(viewed_raw)
        except (TypeError, ValueError):
            viewed = {}
        if not isinstance(viewed, dict):
            viewed = {}
        self.character_view_counts = {}
        for key, value in viewed.items():
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if str(key).strip() and count > 0:
                self.character_view_counts[str(key)] = count

    def _save_character_search_data(self) -> None:
        self.preferences.setValue(
            "character_search_recent",
            json.dumps(self.character_recent_searches[:10], ensure_ascii=False),
        )
        self.preferences.setValue(
            "character_search_viewed",
            json.dumps(self.character_view_counts, ensure_ascii=False),
        )
        self.preferences.sync()

    def register(self, character_id: str) -> None:
        normalized = self.normalize_character_id(character_id)
        if not normalized:
            return
        self.character_recent_searches = [
            item for item in self.character_recent_searches
            if self.normalize_character_id(item) != normalized
        ]
        self.character_recent_searches.insert(0, character_id)
        self.character_recent_searches = self.character_recent_searches[:10]
        self.character_view_counts[character_id] = (
            self.character_view_counts.get(character_id, 0) + 1
        )
        self._save_character_search_data()

    def get_character_search_results(
        self,
        text: str,
        limit: int = 8,
    ) -> list[str]:
        query = self.normalize_character_id(text)
        if not query:
            return []
        scored: list[tuple[float, str]] = []
        for character_id in self.known_character_ids:
            candidate = self.normalize_character_id(character_id)
            if not candidate:
                continue
            if candidate == query:
                score = 1000.0
            elif candidate.startswith(query):
                score = 800.0 - (len(candidate) - len(query))
            elif query in candidate:
                score = 600.0 - candidate.find(query)
            else:
                similarity = difflib.SequenceMatcher(None, query, candidate).ratio()
                score = similarity * 100.0 if similarity >= 0.55 else 0.0
            if score > 0:
                scored.append((score, character_id))
        scored.sort(key=lambda item: (-item[0], item[1].lower()))
        return [character_id for _, character_id in scored[:limit]]

    @staticmethod
    def get_character_display_name(character_id: str) -> str:
        return character_id.replace("_", " ").title()

    def get_most_viewed_characters(self, limit: int = 5) -> list[str]:
        valid_ids = {
            self.normalize_character_id(item): item
            for item in self.known_character_ids
        }
        result: list[str] = []
        for character_id, _count in sorted(
            self.character_view_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            valid_id = valid_ids.get(self.normalize_character_id(character_id))
            if valid_id and valid_id not in result:
                result.append(valid_id)
            if len(result) >= limit:
                break
        return result

    def get_recent_characters(self, limit: int = 5) -> list[str]:
        valid_ids = {
            self.normalize_character_id(item): item
            for item in self.known_character_ids
        }
        result: list[str] = []
        for character_id in self.character_recent_searches:
            valid_id = valid_ids.get(self.normalize_character_id(character_id))
            if valid_id and valid_id not in result:
                result.append(valid_id)
            if len(result) >= limit:
                break
        return result

    def show_popup(self) -> None:
        text = self.search_input.text().strip()
        if not text:
            sections = [
                ("Recentes", self.get_recent_characters()),
                ("Frequentes", self.get_most_viewed_characters()),
            ]
            self._rebuild_popup(sections)
            return
        query = self.normalize_character_id(text)
        recent = [
            character_id
            for character_id in self.get_recent_characters()
            if query in self.normalize_character_id(character_id)
        ]
        frequent = [
            character_id
            for character_id in self.get_most_viewed_characters()
            if query in self.normalize_character_id(character_id)
        ]
        self._rebuild_popup([
            ("Sugestões", self.get_character_search_results(text)),
            ("Recentes", recent),
            ("Frequentes", frequent),
        ])

    def _rebuild_popup(
        self,
        sections: list[tuple[str, list[str]]],
    ) -> None:
        self.hide_popup()
        visible_sections: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        for title, results in sections:
            unique_results: list[str] = []
            for character_id in results:
                if character_id in seen:
                    continue
                seen.add(character_id)
                unique_results.append(character_id)
            if unique_results:
                visible_sections.append((title, unique_results))
        if not visible_sections:
            return
        popup = QFrame(
            self.search_input.window(),
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        popup.setObjectName("characterSearchPopup")
        popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        popup.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )
        popup.setStyleSheet(
            """
            QFrame#characterSearchPopup {
                background-color: #14131f;
                border: 1px solid #3d3859;
                border-radius: 10px;
            }
            QLabel#characterSearchTitle {
                color: #9f9bad;
                font-size: 10px;
                font-weight: bold;
                padding: 8px 10px 4px 10px;
            }
            QPushButton#characterSearchItem {
                background-color: transparent;
                color: #f3f3f5;
                border: none;
                border-radius: 6px;
                text-align: left;
                padding: 8px 10px;
                font-size: 13px;
            }
            QPushButton#characterSearchItem:hover {
                background-color: #242133;
                color: #d4af37;
            }
            """
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        for title, results in visible_sections:
            title_label = QLabel(title)
            title_label.setObjectName("characterSearchTitle")
            layout.addWidget(title_label)
            for character_id in results:
                button = QPushButton(
                    f"{self.element_icon(self.character_elements.get(character_id))}  "
                    f"{self.get_character_display_name(character_id)}"
                )
                button.setObjectName("characterSearchItem")
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(f"ID: {character_id}")
                button.clicked.connect(
                    lambda checked=False, cid=character_id:
                    self._select_result(cid)
                )
                layout.addWidget(button)
        popup.adjustSize()
        entry = self.search_input
        popup.move(entry.mapToGlobal(entry.rect().bottomLeft()))
        popup.setFixedWidth(max(entry.width(), 260))
        popup.show()
        self._character_search_popup = popup

    def _select_result(self, character_id: str) -> None:
        self.hide_popup()
        self.search_input.setText(character_id)
        callback = self._on_character_selected
        if isinstance(callback, weakref.WeakMethod):
            callback = callback()
        if callback is not None:
            callback(character_id)

    def hide_popup(self) -> None:
        popup = self._character_search_popup
        if popup is not None:
            popup.close()
            popup.deleteLater()
        self._character_search_popup = None

    def _on_text_changed(self, _text: str) -> None:
        self.show_popup()
