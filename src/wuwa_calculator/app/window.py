"""Main application window and its composed tabs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from src.wuwa_calculator.app.dialogs.about_dialog import AboutDialog
from src.wuwa_calculator.app.appearance import AppearanceController
from src.wuwa_calculator.app.dialogs.close_dialog import TethysCloseDialog
from src.wuwa_calculator.app.components import Card, CharacterSidebarButton, TitleLabel
from src.wuwa_calculator.app.characters.character_search import CharacterSearchController
from src.wuwa_calculator.app.home_tab import HomeTab
from src.wuwa_calculator.app.obs_test_tab import ObsTestTab
from src.wuwa_calculator.app.dialogs.settings_dialog import SettingsDialog
from src.wuwa_calculator.app.settings_store import SettingsStore
from src.wuwa_calculator.app.dev_mode import frequencies_should_be_blocked
from src.wuwa_calculator.app.styles import apply_glow
from src.wuwa_calculator.data.characters_elements import CHARACTER_ELEMENTS
from src.wuwa_calculator.data.characters_ids import KNOWN_CHARACTER_IDS
from src.wuwa_calculator.utils.paths import get_asset_path

if TYPE_CHECKING:
    from src.wuwa_calculator.app.import_dialog import CustomImportPopup
    from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget
    from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab
    from src.wuwa_calculator.app.characters.resonator_tab import ResonatorTab

ELEMENT_NAV_COLORS = {
    "Aero": ("#145A4A", "#72E6C0", "#E8FFF8", "#1E8068"),
    "Glacio": ("#285A78", "#82D8FF", "#E4F8FF", "#397A9D"),
    "Electro": ("#49356F", "#B78CFF", "#F0E8FF", "#644B91"),
    "Fusion": ("#713D2C", "#FF8A65", "#FFF0E8", "#975039"),
    "Havoc": ("#642C43", "#E85D75", "#FFE8EE", "#873B58"),
    "Spectro": ("#665522", "#FFD76A", "#FFF8D6", "#87702D"),
}
# Altere para um arquivo .ico ou .png quando quiser personalizar o modal.
TETHYS_CLOSE_ICON_PATH: str | None = None

# Ícone customizado para o popup de fechar (local em Assets ou URL remota)
# Deixe como arquivo local para melhor performance
TETHYS_CLOSE_ICON_URL: str | None = None
TETHYS_CLOSE_ICON_LOCAL: str | None = str(get_asset_path("close_icon.png"))

class PlaceholderTab(QWidget):
    def __init__(self, title: str,
                 description: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.addWidget(TitleLabel(title))
        text = QLabel(description)
        text.setObjectName("muted")
        card_layout.addWidget(text)
        card_layout.addStretch(1)
        layout.addWidget(card)




class WuwaQtWindow(QMainWindow):
    def __init__(
        self,
        startup_marker: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        if startup_marker is not None:
            startup_marker("STARTUP:MAIN_WINDOW_INITIALIZATION")
        self.preferences = QSettings("Tethys", "Tethys")
        self.settings = SettingsStore(settings=self.preferences)
        self._dev_mode_enabled = False
        self._dev_frequencies_override = False
        self._import_dialog: CustomImportPopup | None = None
        self._convene_tracker_backend: LegacyPityTrackerWidget | None = None
        self._close_confirmation_accepted = False
        self._close_after_background_shutdown = False
        self.setWindowTitle("Tethys System")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setFixedSize(1440, 900)
        self.background_label = QLabel(self)
        self.background_label.setObjectName("appBackground")
        self.background_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.background_label.lower()
        self.appearance = AppearanceController(
            root_widget=self,
            background_label=self.background_label,
            settings=self.settings,
        )

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(12, 10, 12, 12)
        shell_layout.setSpacing(10)

        header = Card()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.addWidget(TitleLabel("Tethys System"))
        header_layout.addStretch(1)

        self.character_id_entry = QLineEdit()
        self.character_id_entry.setPlaceholderText("Digite o nome do(a) personagem...")
        self.character_id_entry.setFixedWidth(210)
        self.character_search = CharacterSearchController(
            preferences=self.preferences,
            search_input=self.character_id_entry,
            known_character_ids=KNOWN_CHARACTER_IDS,
            character_elements=CHARACTER_ELEMENTS,
            element_icon=self._element_icon,
            on_character_selected=self._open_character_search_result,
        )

        self.character_load_button = QPushButton("Buscar")
        self.character_load_button.setObjectName("primaryAction")

        self.import_button = QPushButton("Carregar Stats")
        self.import_button.setObjectName("primaryAction")

        header_layout.addWidget(self.character_id_entry)
        header_layout.addWidget(self.character_load_button)
        header_layout.addWidget(self.import_button)
        header_layout.addStretch(1)

        self.character_status = QLabel("")
        self.character_status.setObjectName("onlineStatus")

        header_layout.addWidget(self.character_status)
        shell_layout.addWidget(header)

        tabs = QTabWidget()
        tabs.setObjectName("mainTabs")
        tabs.tabBar().hide()

        def build_home() -> HomeTab:
            home_tab = HomeTab()
            home_tab.set_performance_mode(
                self.settings.get("performance_mode", False, bool)
            )
            set_fast_startup_mode = getattr(home_tab, "set_fast_startup_mode", None)
            if callable(set_fast_startup_mode):
                set_fast_startup_mode(
                    self.settings.get("fast_startup", False, bool)
                )
            home_tab.shutdown_finished.connect(
                self._resume_close_after_background_shutdown
            )
            if startup_marker is not None:
                startup_marker("STARTUP:HOME_CONSTRUCTED")
            return home_tab

        def build_teams() -> QWidget:
            from src.wuwa_calculator.app.teams_tab import TeamsTab
            return TeamsTab()

        def build_convene_tracker() -> QWidget:
            from src.wuwa_calculator.app.convene.convene_tracker_tab import ConveneTrackerTab
            return ConveneTrackerTab(self._ensure_convene_backend())

        def build_history() -> QWidget:
            from src.wuwa_calculator.app.history_tab import HistoryTab
            return HistoryTab()

        def build_multimedia() -> MultimediaTab:
            from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab

            multimedia_tab = MultimediaTab()
            multimedia_tab.set_performance_mode(
                self.settings.get("performance_mode", False, bool)
            )
            multimedia_tab.set_development_frequency_override(
                self._dev_mode_enabled,
                self._dev_frequencies_override,
            )
            multimedia_tab.dps_panel.shutdown_finished.connect(
                self._resume_close_after_background_shutdown
            )
            if multimedia_tab.dps_panel.capture_settings != self._capture_settings:
                multimedia_tab.dps_panel.set_capture_settings(self._capture_settings)
            return multimedia_tab

        def build_obs_test() -> ObsTestTab:
            return ObsTestTab()

        self._tab_factories = (
            build_home,
            build_convene_tracker,
            build_teams,
            build_history,
            build_multimedia,
            build_obs_test,
            lambda: PlaceholderTab(
                "Fontes de dados",
                "Tela preparada para exibir fontes, "
                "cache e estado das integrações."),
        )
        self._tab_titles = (
            "Banners",
            "Convene Tracker",
            "Teams",
            "Histórico",
            "Mapeamento de Frequências",
            "OBS Teste",
            "Fontes de dados",
        )
        self._tab_widgets: dict[int, QWidget] = {}
        self._active_main_index: int | None = None
        self.tabs = tabs
        for title in self._tab_titles:
            tabs.addTab(QWidget(), title)
        obs_test_tab = build_obs_test()
        tabs.removeTab(5)
        tabs.insertTab(5, obs_test_tab, self._tab_titles[5])
        self._tab_widgets[5] = obs_test_tab
        self._capture_settings = obs_test_tab.settings
        obs_test_tab.settingsChanged.connect(self._handle_capture_settings_changed)
        self.character_tabs: dict[str, ResonatorTab] = {}
        self.character_open_order: list[str] = []
        tabs.currentChanged.connect(self._handle_main_tab_changed)
        self._handle_main_tab_changed(0)

        self.sidebar_buttons: dict[str, QPushButton] = {}
        self._sidebar_buttons_by_tab: dict[int, QPushButton] = {}
        self.character_sidebar_rows: dict[str, QWidget] = {}

        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(184)
        apply_glow(sidebar, blur=26, opacity=105)

        self.sidebar_layout = QVBoxLayout(sidebar)
        self.sidebar_layout.setContentsMargins(14, 18, 14, 18)
        self.sidebar_layout.setSpacing(8)
        for index, label in enumerate(("⌂   Banners",
                           "◉   Convene Tracker",
                                       "♣   Teams",
                                       "◷   Histórico",
                                       "⌁   Frequências",
                                       "▣   OBS Teste")):
            self._add_sidebar_button(self.sidebar_layout, label, index)
        self.sidebar_layout.addSpacing(10)
        self.character_sidebar_layout = QVBoxLayout()
        self.character_sidebar_layout.setSpacing(8)
        self.sidebar_layout.addLayout(self.character_sidebar_layout)
        self.sidebar_layout.addSpacing(10)
        self.sidebar_layout.addStretch(1)

        settings_button = self._add_sidebar_button(
            self.sidebar_layout, "⚙   Configurações", None)
        settings_button.clicked.connect(self.open_settings)
        about_button = self._add_sidebar_button(
            self.sidebar_layout, "ⓘ   Sobre", None)

        about_button.clicked.connect(self.open_about)
        workspace.addWidget(sidebar)
        workspace.addWidget(tabs, 1)
        shell_layout.addLayout(workspace, 1)

        self._set_sidebar_active("\u2302   Banners")
        self.setCentralWidget(shell)
        self._update_background(
            self.settings.get("background", True, bool),
            self.settings.get("wallpaper", "", str),
        )
        self.character_load_button.clicked.connect(
            self.open_character_tab)
        self.character_id_entry.returnPressed.connect(
            self.open_character_tab)
        self.import_button.clicked.connect(self.open_import_dialog)
        self.apply_preferences()
        self._restore_last_session()
        if startup_marker is not None:
            startup_marker("STARTUP:MAIN_WINDOW_CONSTRUCTED")

    def _restore_last_session(self) -> None:
        if not self.preferences.value("auto_open_last_character", True, type=bool):
            return
        last_character = self.preferences.value("last_character", "", type=str)
        if not isinstance(last_character, str) or not last_character:
            return
        normalized = self.character_search.normalize_character_id(last_character)
        if not normalized:
            return
        for candidate in KNOWN_CHARACTER_IDS:
            if self.character_search.normalize_character_id(candidate) == normalized:
                self.character_id_entry.setText(candidate)
                self.open_character_tab()
                break

    def apply_preferences(self) -> None:
        self.appearance.apply()
        performance_mode = self.settings.get("performance_mode", False, bool)
        fast_startup = self.settings.get("fast_startup", False, bool)
        self._sync_frequencies_availability()
        for tab in self._tab_widgets.values():
            set_performance_mode = getattr(tab, "set_performance_mode", None)
            if callable(set_performance_mode):
                set_performance_mode(performance_mode)
            set_fast_startup_mode = getattr(tab, "set_fast_startup_mode", None)
            if callable(set_fast_startup_mode):
                set_fast_startup_mode(fast_startup)
            set_development_frequency_override = getattr(
                tab, "set_development_frequency_override", None
            )
            if callable(set_development_frequency_override):
                set_development_frequency_override(
                    self._dev_mode_enabled,
                    self._dev_frequencies_override,
                )

    def _update_background(self, enabled: bool, wallpaper: str) -> None:
        self.appearance.update_background(enabled, wallpaper)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_background(
            self.settings.get("background", True, bool),
            self.settings.get("wallpaper", "", str),
        )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            home = self._tab_widgets.get(0)
            if isinstance(home, HomeTab):
                home.set_window_visible(not self.isMinimized())

    def closeEvent(self, event) -> None:
        if (
            self.preferences.value("confirm_exit", True, type=bool)
            and not self._close_confirmation_accepted
        ):
            if not TethysCloseDialog.confirm_close(
                icon_path=TETHYS_CLOSE_ICON_PATH,
                icon_url=TETHYS_CLOSE_ICON_URL,
                icon_local=TETHYS_CLOSE_ICON_LOCAL,
                parent=self,
            ):
                event.ignore()
                return
            self._close_confirmation_accepted = True
        if self._import_dialog is not None and not self._import_dialog.shutdown_ocr():
            event.ignore()
            return
        home_tab = self._tab_widgets.get(0)
        if isinstance(home_tab, HomeTab):
            if not home_tab.shutdown_workers():
                self._close_after_background_shutdown = True
                event.ignore()
                return
        convene_backend = self._convene_tracker_backend
        if (
            convene_backend is not None
            and not convene_backend.shutdown_workers()
        ):
            event.ignore()
            return
        multimedia_tab = self._tab_widgets.get(4)
        if multimedia_tab is not None:
            if not cast("MultimediaTab", multimedia_tab).shutdown():
                self._close_after_background_shutdown = True
                event.ignore()
                return
        self._close_after_background_shutdown = False
        event.accept()

    def _resume_close_after_background_shutdown(self) -> None:
        if not self._close_after_background_shutdown:
            return
        self._close_after_background_shutdown = False
        self.close()

    @property
    def convene_tracker_backend(self) -> LegacyPityTrackerWidget:
        return self._ensure_convene_backend()

    @convene_tracker_backend.setter
    def convene_tracker_backend(self, backend: LegacyPityTrackerWidget) -> None:
        self._convene_tracker_backend = backend

    def _ensure_convene_backend(self) -> LegacyPityTrackerWidget:
        backend = self._convene_tracker_backend
        if backend is None:
            from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget

            backend = LegacyPityTrackerWidget()
            self._convene_tracker_backend = backend
        return backend

    def _handle_capture_settings_changed(self, settings: object) -> None:
        from src.wuwa_calculator.app.capture.settings import CaptureSettings

        if not isinstance(settings, CaptureSettings):
            return
        self._capture_settings = settings
        multimedia_tab = self._tab_widgets.get(4)
        if multimedia_tab is not None:
            cast("MultimediaTab", multimedia_tab).dps_panel.set_capture_settings(
                settings
            )

    def _add_sidebar_button(
        self,
        layout: QVBoxLayout,
        label: str,
        tab_index: int | None,
        element: str | None = None,
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("nav")
        if element:
            button.setProperty("element", element)
        apply_glow(button, blur=12, opacity=72)
        if tab_index is not None:
            button.clicked.connect(
                lambda: self._select_main_tab(tab_index, label))
            self.sidebar_buttons[label] = button
            self._sidebar_buttons_by_tab[tab_index] = button
        layout.addWidget(button)
        return button

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

    def open_about(self) -> None:
        AboutDialog(self).exec()

    def open_import_dialog(self) -> None:
        dialog = self._import_dialog
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        character_tab = self._character_tab_for_widget(self.tabs.currentWidget())
        if character_tab is None:
            QMessageBox.information(
                self,
                "Personagem não carregado",
                "Carregue uma ID de personagem antes de importar a imagem.",
            )
            return
        from src.wuwa_calculator.app.import_dialog import CustomImportPopup

        dialog = CustomImportPopup(self, character_tab)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        dialog.finished.connect(self._clear_import_dialog)
        self._import_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_import_dialog(self, _result: int) -> None:
        dialog = getattr(self, "_import_dialog", None)
        if dialog is not None:
            dialog.deleteLater()
        self._import_dialog = None
    
    def _select_main_tab(self, index: int, label: str) -> None:
        self.tabs.setCurrentIndex(index)
        self._set_sidebar_active(label)

    def _ensure_main_tab(self, index: int) -> None:
        if index < 0 or index >= len(self._tab_factories):
            return
        if index in self._tab_widgets:
            return
        factory = self._tab_factories[index]
        widget = factory()
        old_widget = self.tabs.widget(index)
        self._tab_widgets[index] = widget
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, widget, self._tab_titles[index])
        self.tabs.blockSignals(False)
        if old_widget is not None:
            old_widget.deleteLater()
        if index == 4:
            self._sync_frequencies_availability()
        self.tabs.setCurrentIndex(index)

    def _sync_frequencies_availability(self) -> None:
        blocked = frequencies_should_be_blocked(
            self._dev_mode_enabled,
            self._dev_frequencies_override,
        )
        self.tabs.setTabEnabled(4, not blocked)
        button = self._sidebar_buttons_by_tab.get(4)
        if button is not None:
            button.setEnabled(not blocked)

    def toggle_development_mode(self) -> bool:
        """Toggle temporary DEV access without changing persisted settings."""
        self._dev_mode_enabled = not self._dev_mode_enabled
        self._dev_frequencies_override = self._dev_mode_enabled
        self._sync_frequencies_availability()
        for tab in self._tab_widgets.values():
            set_override = getattr(
                tab, "set_development_frequency_override", None
            )
            if callable(set_override):
                set_override(
                    self._dev_mode_enabled,
                    self._dev_frequencies_override,
                )
        return self._dev_mode_enabled

    def _character_tab_for_widget(
        self,
        widget: QWidget | None,
    ) -> ResonatorTab | None:
        if widget is None:
            return None
        for character_tab in self.character_tabs.values():
            if widget is character_tab:
                return character_tab
        return None

    def _handle_main_tab_changed(self, index: int) -> None:
        current_widget = self.tabs.widget(index)
        current_character_tab = self._character_tab_for_widget(current_widget)
        if current_character_tab is not None:
            previous_index = self._active_main_index
            if previous_index is not None and previous_index != index:
                previous_widget = self.tabs.widget(previous_index)
                if previous_widget is not None:
                    self._set_active_main_tab(previous_index, previous_widget, False)
                    previous_widget.setUpdatesEnabled(False)
            current_character_tab.setUpdatesEnabled(True)
            current_character_tab.show()
            current_character_tab.update()
            self._active_main_index = index
            return
        previous_index = self._active_main_index
        if previous_index is not None and previous_index != index:
            previous_widget = self._tab_widgets.get(previous_index)
            if previous_widget is not None:
                self._set_active_main_tab(previous_index, previous_widget, False)
                previous_widget.setUpdatesEnabled(False)
        self._ensure_main_tab(index)
        current_widget = self._tab_widgets.get(index)
        if current_widget is not None:
            current_widget.setUpdatesEnabled(True)
            self._set_active_main_tab(index, current_widget, True)
            current_widget.show()
            current_widget.update()
        self._active_main_index = index

    def _set_active_main_tab(
        self,
        index: int,
        widget: QWidget,
        active: bool,
    ) -> None:
        if index == 0 and isinstance(widget, HomeTab):
            widget.set_active(active)
        elif index == 4:
            cast("MultimediaTab", widget).set_active(active)

    def _set_sidebar_active(self, active_label: str) -> None:
        for label, button in self.sidebar_buttons.items():
            button.setObjectName("navActive"
                                 if label == active_label else "nav")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def clear_character_tabs(self) -> None:
        for character_tab in self.character_tabs.values():
            tab_index = self.tabs.indexOf(character_tab)
            if tab_index >= 0:
                self.tabs.removeTab(tab_index)
            character_tab.deleteLater()
        self.character_tabs.clear()

        while self.character_sidebar_layout.count():
            item = self.character_sidebar_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.character_sidebar_rows.clear()
        self.character_open_order.clear()

        for label, button in tuple(self.sidebar_buttons.items()):
            if button.property("sidebarCharacter"):
                self.sidebar_buttons.pop(label, None)

        self.tabs.setCurrentIndex(0)
        self._set_sidebar_active("\u2302   Banners")

    def _add_character_sidebar_button(
        self,
        character_id: str,
        label: str,
        element: str | None,
    ) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        button = CharacterSidebarButton(label)
        button.setObjectName("nav")
        if element:
            button.setProperty("element", element)
        button.setProperty("sidebarCharacter", True)
        apply_glow(button, blur=12, opacity=72)
        row_layout.addWidget(button)
        self.sidebar_buttons[label] = button
        button.clicked.connect(
            lambda: self._select_character_tab(character_id, label))
        button.close_requested.connect(
            lambda: self._close_character_tab(character_id))
        self.character_sidebar_rows[character_id] = row
        self.character_sidebar_layout.addWidget(row)

    def _select_character_tab(self, character_id: str, label: str) -> None:
        character_tab = self.character_tabs.get(character_id)
        if character_tab is None:
            return
        self.tabs.setCurrentWidget(character_tab)
        self._set_sidebar_active(label)

    def _close_character_tab(self, character_id: str) -> None:
        character_tab = self.character_tabs.pop(character_id, None)
        row = self.character_sidebar_rows.pop(character_id, None)
        if character_tab is None:
            return

        label = (
            f"{self._element_icon(CHARACTER_ELEMENTS.get(character_id))}   "
            f"{character_id.title()}"
        )
        self.sidebar_buttons.pop(label, None)
        was_current = self.tabs.currentWidget() is character_tab
        history_index = self.character_open_order.index(character_id)
        if history_index == 0:
            previous_character_id = (
                self.character_open_order[1]
                if len(self.character_open_order) > 1 else None
            )
        else:
            previous_character_id = self.character_open_order[history_index - 1]
        self.character_open_order.remove(character_id)
        tab_index = self.tabs.indexOf(character_tab)
        if tab_index >= 0:
            self.tabs.removeTab(tab_index)
        character_tab.deleteLater()
        if row is not None:
            row.deleteLater()

        if was_current:
            previous_tab = (
                self.character_tabs.get(previous_character_id)
                if previous_character_id is not None
                else None
            )
            if previous_tab is not None and previous_character_id is not None:
                self.tabs.setCurrentWidget(previous_tab)
                previous_label = (
                    f"{self._element_icon(CHARACTER_ELEMENTS.get(previous_character_id))}   "
                    f"{previous_character_id.title()}"
                )
                self._set_sidebar_active(previous_label)
            else:
                self.tabs.setCurrentIndex(0)
                self._set_sidebar_active("\u2302   Banners")
            return

        current_widget = self.tabs.currentWidget()
        current_character_tab = self._character_tab_for_widget(current_widget)
        if current_character_tab is not None:
            current_id = current_character_tab.current_id
            self._set_sidebar_active(
                f"{self._element_icon(CHARACTER_ELEMENTS.get(current_id))}   "
                f"{current_id.title()}"
            )
        else:
            current_index = self.tabs.currentIndex()
            if 0 <= current_index < len(self._tab_titles):
                self._set_sidebar_active(self._tab_titles[current_index])


    @staticmethod
    def _element_icon(element: str | None) -> str:
        return {
            "Aero": "◈",
            "Glacio": "❄",
            "Electro": "✦",
            "Fusion": "♢",
            "Havoc": "◉",
            "Spectro": "✧",
        }.get(str(element), "◆")













    def _open_character_search_result(self, character_id: str) -> None:
        self.character_id_entry.setText(character_id)
        self.open_character_tab()

    def open_character_tab(self) -> None:
        self.character_search.hide_popup()
        typed_text = self.character_id_entry.text().strip()
        if not typed_text:
            self.character_status.setText("Digite um personagem")
            return
        target = self.character_search.normalize_character_id(typed_text)
        character_id = next(
            (
                item for item in KNOWN_CHARACTER_IDS
                if self.character_search.normalize_character_id(item) == target
            ),
            None,
        )
        if character_id is None:
            suggestions = self.character_search.get_character_search_results(
                typed_text,
                limit=1,
            )
            character_id = suggestions[0] if suggestions else None
        if character_id is None:
            self.character_status.setText("Personagem não encontrado")
            return

        character_tab = self.character_tabs.get(character_id)
        if character_tab is None:
            from src.wuwa_calculator.app.characters.resonator_tab import ResonatorTab

            character_tab = ResonatorTab(initial_id=character_id)
            self.character_tabs[character_id] = character_tab
            self.character_open_order.append(character_id)
            sources_index = self.tabs.count() - 1
            self.tabs.insertTab(sources_index,
                                character_tab,
                                character_id.title())
            label = character_id.title()
            element = CHARACTER_ELEMENTS.get(character_id)
            self.tabs.setTabText(
                sources_index,
                f"{self._element_icon(element)} {label}",
            )
            self._add_character_sidebar_button(
                character_id,
                f"{self._element_icon(element)}   {label}",
                element,
            )

        self.tabs.setCurrentWidget(character_tab)
        self.character_search.register(character_id)
        if self.preferences.value("auto_save_session", True, type=bool):
            self.preferences.setValue("last_character", character_id)
            self.preferences.sync()
        self._set_sidebar_active(
            f"{self._element_icon(CHARACTER_ELEMENTS.get(character_id))}   {character_id.title()}")
        self.character_id_entry.blockSignals(True)
        self.character_id_entry.clear()
        self.character_id_entry.blockSignals(False)
        self.character_search.hide_popup()
        self.character_status.clear()
