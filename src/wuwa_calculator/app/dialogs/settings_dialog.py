"""Settings dialog and preference controls."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.wuwa_calculator.app.components import Card, TitleLabel
from src.wuwa_calculator.app.settings_store import SettingsStore


class _SettingsHost(Protocol):
    settings: SettingsStore
    preferences: QSettings

    def apply_preferences(self) -> None: ...

    def clear_character_tabs(self) -> None: ...


class SettingsTab(QWidget):
    def __init__(self, parent: QWidget | None = None,
                 host: QWidget | None = None,
                 settings: SettingsStore | None = None,
                 preferences: QSettings | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.preferences = preferences or QSettings("Tethys", "Tethys")
        self.settings = settings or SettingsStore(settings=self.preferences)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        appearance_card = Card()
        appearance_layout = QVBoxLayout(appearance_card)
        appearance_layout.setContentsMargins(20, 20, 20, 20)
        appearance_layout.addWidget(TitleLabel("Aparência e janela"))
        appearance_form = QFormLayout()
        appearance_form.setVerticalSpacing(12)

        self.background_box = QCheckBox("Usar imagem de fundo")
        self.background_box.setChecked(True)
        appearance_form.addRow("Fundo", self.background_box)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setSingleStep(1)
        self.opacity_slider.setPageStep(1)
        self.opacity_slider.setTracking(False)
        self.opacity_slider.setValue(85)
        self.opacity_slider.setToolTip("Opacidade dos painéis e cards")
        appearance_form.addRow("Opacidade da interface", self.opacity_slider)

        self.accent_box = QComboBox()
        self.accent_box.addItems([
            "Auto Wallpaper",
            "Ciano Tethys", "Dourado Sol", "Roxo Nécro", "Vermelho Alerta",
            "Verde Aurora", "Azul Abissal", "Rosa Prisma", "Laranja Solar",
            "Turquesa Maré", "Lima Resonância", "Gelo Lunar", "Âmbar Nebulosa",
            "Coral Resonante", "Índigo Profundo", "Prata Sônica", "Verde Vórtice",
        ])
        appearance_form.addRow("Cor do tema", self.accent_box)

        self.language_box = QComboBox()
        self.language_box.addItems(["PT-BR", "EN"])
        appearance_form.addRow("Idioma do app", self.language_box)

        self.confirm_exit_box = QCheckBox(
            "Confirmar antes de fechar o programa")
        appearance_layout.addLayout(appearance_form)
        layout.addWidget(appearance_card)

        wallpaper_card = Card()
        wallpaper_layout = QVBoxLayout(wallpaper_card)
        wallpaper_layout.setContentsMargins(20, 20, 20, 20)
        wallpaper_layout.addWidget(TitleLabel("Wallpaper personalizado"))
        wallpaper_info = QLabel(
            "Use uma imagem entre 1024 x 640 e 1440 x 900 px, "
            "na proporção 16:10. "
            "O tamanho ideal é 1440 x 900 px para preencher o "
            "programa sem deformar."
        )
        wallpaper_info.setObjectName("muted")
        wallpaper_info.setWordWrap(True)
        wallpaper_layout.addWidget(wallpaper_info)

        self.wallpaper_label = QLabel("Fundo padrão do programa")
        self.wallpaper_label.setObjectName("muted")
        self.wallpaper_label.setWordWrap(True)

        wallpaper_layout.addWidget(self.wallpaper_label)
        wallpaper_actions = QHBoxLayout()
        choose_wallpaper_button = QPushButton("Escolher wallpaper")
        choose_wallpaper_button.clicked.connect(self._choose_wallpaper)
        wallpaper_actions.addWidget(choose_wallpaper_button)
        reset_wallpaper_button = QPushButton("Usar fundo padrão")
        reset_wallpaper_button.clicked.connect(self._reset_wallpaper)
        wallpaper_actions.addWidget(reset_wallpaper_button)
        wallpaper_actions.addStretch(1)
        wallpaper_layout.addLayout(wallpaper_actions)
        layout.addWidget(wallpaper_card)

        session_card = Card()
        session_layout = QVBoxLayout(session_card)
        session_layout.setContentsMargins(20, 20, 20, 20)
        session_layout.addWidget(TitleLabel("Sessão e desempenho"))

        self.auto_open_last_box = QCheckBox("Abrir o último personagem ao iniciar")
        self.auto_save_box = QCheckBox("Salvar sessão automaticamente")
        self.performance_mode_box = QCheckBox("Modo leve / reduzir efeitos visuais")
        self.fast_startup_box = QCheckBox("Inicialização Rápida")
        self.fast_startup_box.setToolTip(
            "Adia carregamentos secundários da Home após a primeira tela; "
            "a opção afeta a próxima inicialização."
        )

        session_layout.addWidget(self.auto_open_last_box)
        session_layout.addWidget(self.auto_save_box)
        session_layout.addWidget(self.performance_mode_box)
        session_layout.addWidget(self.fast_startup_box)

        session_actions = QHBoxLayout()
        clear_cache_button = QPushButton("Limpar cache")
        clear_cache_button.clicked.connect(self._clear_cache)
        clear_history_button = QPushButton("Limpar histórico")
        clear_history_button.clicked.connect(self._clear_history)
        session_actions.addWidget(clear_cache_button)
        session_actions.addWidget(clear_history_button)
        session_actions.addStretch(1)
        session_layout.addLayout(session_actions)
        layout.addWidget(session_card)

        data_card = Card()
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(20, 20, 20, 20)
        data_layout.addWidget(TitleLabel("Dados da sessão"))
        data_text = QLabel("Remova as abas de personagens "
                           "carregadas sem apagar arquivos salvos.")
        data_text.setObjectName("muted")
        data_layout.addWidget(data_text)
        clear_button = QPushButton("Limpar personagens carregados")
        clear_button.clicked.connect(self._clear_characters)
        data_layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(data_card)

        actions = QHBoxLayout()
        defaults_button = QPushButton("Restaurar padrões")
        defaults_button.clicked.connect(self._restore_defaults)
        actions.addWidget(defaults_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.background_box.toggled.connect(self._background_changed)
        self.opacity_slider.valueChanged.connect(self._interface_opacity_changed)
        self.accent_box.currentTextChanged.connect(self._accent_changed)
        self.language_box.currentTextChanged.connect(self._language_changed)
        self.auto_open_last_box.toggled.connect(self._auto_open_last_changed)
        self.auto_save_box.toggled.connect(self._auto_save_changed)
        self.performance_mode_box.toggled.connect(self._performance_mode_changed)
        self.fast_startup_box.toggled.connect(self._fast_startup_changed)
        self.confirm_exit_box.toggled.connect(self._confirm_exit_changed)
        self._load_preferences()

    def _load_preferences(self) -> None:
        settings = self.settings
        self.background_box.setChecked(
            settings.get("background", True, bool))

        self.opacity_slider.setValue(settings.get("interface_opacity", 85, int))
        accent = settings.get("accent_theme", "Auto Wallpaper", str)
        if accent in {"Modo claro", "Modo escuro"}:
            accent = "Auto Wallpaper"
        index = self.accent_box.findText(accent)
        self.accent_box.setCurrentIndex(max(0, index))
        self.language_box.setCurrentText(
            settings.get("ui_language", "PT-BR", str)
        )
        auto_open_last = self.preferences.value("auto_open_last_character", True, type=bool)
        self.auto_open_last_box.setChecked(
            auto_open_last if isinstance(auto_open_last, bool) else True
        )
        auto_save = self.preferences.value("auto_save_session", True, type=bool)
        self.auto_save_box.setChecked(auto_save if isinstance(auto_save, bool) else True)
        self.performance_mode_box.setChecked(
            settings.get("performance_mode", False, bool)
        )
        self.fast_startup_box.blockSignals(True)
        self.fast_startup_box.setChecked(settings.get("fast_startup", False, bool))
        self.fast_startup_box.blockSignals(False)
        self.confirm_exit_box.setChecked(
            settings.get("confirm_exit", True, bool))

        wallpaper = settings.get("wallpaper", "", str)
        self._set_wallpaper_label(wallpaper)

    def _choose_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher wallpaper do programa",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp);;Todos os arquivos (*)",
        )
        if not path:
            return
        size = QPixmap(path).size()
        minimum_width, minimum_height = 1024, 640
        maximum_width, maximum_height = 1440, 900
        ratio = size.width() / size.height() if size.height() else 0
        if (
            size.width() < minimum_width
            or size.height() < minimum_height
            or size.width() > maximum_width
            or size.height() > maximum_height
            or abs(ratio - 1.6) > 0.01
        ):
            QMessageBox.warning(
                self,
                "Tamanho de wallpaper inválido",
                "Escolha uma imagem entre 1024 x 640 e 1440 x 900 px, "
                "com proporção 16:10. O tamanho recomendado é 1440 x 900 px.",
            )
            return

        wallpaper = str(QUrl.fromLocalFile(path).toString())
        self.settings.set("wallpaper", wallpaper)
        self.settings.sync()
        self._set_wallpaper_label(path)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _reset_wallpaper(self) -> None:
        self.settings.remove("wallpaper")
        self.settings.sync()
        self._set_wallpaper_label("")
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _set_wallpaper_label(self, wallpaper: str) -> None:
        label_text = "app_background_reference.png"
        if wallpaper:
            cleaned = wallpaper.strip()
            if cleaned.startswith("file://"):
                parsed = QUrl(cleaned)
                local_path = parsed.toLocalFile()
                label_text = Path(local_path).name or cleaned
            else:
                label_text = Path(cleaned).name or cleaned
        self.wallpaper_label.setText(f"Wallpaper atual: {label_text}")

    def _background_changed(self, enabled: bool) -> None:
        self.settings.set("background", enabled)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _interface_opacity_changed(self, value: int) -> None:
        self.settings.set("interface_opacity", value)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _accent_changed(self, accent: str) -> None:
        self.settings.set("accent_theme", accent)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _language_changed(self, language: str) -> None:
        self.settings.set("ui_language", language)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _auto_open_last_changed(self, enabled: bool) -> None:
        self.preferences.setValue("auto_open_last_character", enabled)

    def _auto_save_changed(self, enabled: bool) -> None:
        self.preferences.setValue("auto_save_session", enabled)

    def _performance_mode_changed(self, enabled: bool) -> None:
        self.settings.set("performance_mode", enabled)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _fast_startup_changed(self, enabled: bool) -> None:
        self.settings.set("fast_startup", enabled)
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()

    def _confirm_exit_changed(self, enabled: bool) -> None:
        self.settings.set("confirm_exit", enabled)

    def _clear_cache(self) -> None:
        from src.wuwa_calculator.storage.banner_cache import CACHE_FILE as BANNER_CACHE_FILE
        for path in (BANNER_CACHE_FILE, Path(self.preferences.fileName()).parent / "current_banner.json"):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        QMessageBox.information(self, "Cache limpo", "O cache de banner foi removido.")

    def _clear_history(self) -> None:
        from src.wuwa_calculator.storage.history_storage import ROTATION_HISTORY_FILE, save_rotation_document, empty_rotation_document
        save_rotation_document(empty_rotation_document(), ROTATION_HISTORY_FILE)
        QMessageBox.information(self, "Histórico limpo", "O histórico de rotações foi resetado.")

    def _clear_characters(self) -> None:
        window = self.host or self.window()
        clear_character_tabs = getattr(window, "clear_character_tabs", None)
        if callable(clear_character_tabs):
            clear_character_tabs()

    def _restore_defaults(self) -> None:
        self.preferences.clear()
        self.background_box.setChecked(True)
        self.opacity_slider.setValue(85)
        self.accent_box.setCurrentText("Auto Wallpaper")
        self.language_box.setCurrentText("PT-BR")
        self.auto_open_last_box.setChecked(True)
        self.auto_save_box.setChecked(True)
        self.performance_mode_box.setChecked(False)
        self.fast_startup_box.setChecked(False)
        self.confirm_exit_box.setChecked(True)
        self._reset_wallpaper()
        window = self.host or self.window()
        apply_preferences = getattr(window, "apply_preferences", None)
        if callable(apply_preferences):
            apply_preferences()


class SettingsDialog(QDialog):
    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setWindowTitle("Configurações | Tethys")
        self.setModal(True)
        self.resize(820, 540)
        self.setMinimumSize(720, 420)
        self.setMaximumHeight(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        settings_host = cast(_SettingsHost, host)
        settings_tab = SettingsTab(
            self,
            host=host,
            settings=settings_host.settings,
            preferences=settings_host.preferences,
        )
        scroll.setWidget(settings_tab)
        layout.addWidget(scroll, 1)

        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
