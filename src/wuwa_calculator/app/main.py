"""PySide6 application entry point."""

from __future__ import annotations

import contextlib
import difflib
import io
import json
import subprocess
import sys
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.multimedia.ffmpeg=false;qt.network.ssl.warning=false;"
    "qt.core.qiodevice.warning=false",
)

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import (
    QAbstractAnimation, QObject, QPropertyAnimation, QPoint, QRect, QSettings, Qt, QThread,
    QEasingCurve, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QDesktopServices, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPen,
    QPixmap, QResizeEvent,
    )
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QFileDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSlider, QTabWidget, QToolButton, QVBoxLayout,
    QWidget,
    QMenu,
)

from src.wuwa_calculator.app.components import Card, TitleLabel
from src.wuwa_calculator.app.resonator_tab import ResonatorTab
from src.wuwa_calculator.app.settings_store import SettingsStore
from src.wuwa_calculator.app.styles import (
    accent_preset,
    application_qss,
    apply_glow,
    refresh_glows,
    ThemeConfig,
    theme_config,
    wallpaper_palette,
)
from src.wuwa_calculator.utils.paths import get_asset_path

ELEMENT_NAV_COLORS = {
    "Aero": ("#145A4A", "#72E6C0", "#E8FFF8", "#1E8068"),
    "Glacio": ("#285A78", "#82D8FF", "#E4F8FF", "#397A9D"),
    "Electro": ("#49356F", "#B78CFF", "#F0E8FF", "#644B91"),
    "Fusion": ("#713D2C", "#FF8A65", "#FFF0E8", "#975039"),
    "Havoc": ("#642C43", "#E85D75", "#FFE8EE", "#873B58"),
    "Spectro": ("#665522", "#FFD76A", "#FFF8D6", "#87702D"),
}
from src.wuwa_calculator.data.characters_elements import CHARACTER_ELEMENTS
from src.wuwa_calculator.data.characters_ids import KNOWN_CHARACTER_IDS

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


class CharacterSidebarButton(QPushButton):
    close_requested = Signal()

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("tabClose")
        self.close_button.setText("×")
        self.close_button.setToolTip("Fechar aba")
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(self.close_requested)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.close_button.move(
            self.width() - self.close_button.width() - 5,
            (self.height() - self.close_button.height()) // 2,
        )


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

        session_layout.addWidget(self.auto_open_last_box)
        session_layout.addWidget(self.auto_save_box)
        session_layout.addWidget(self.performance_mode_box)

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
        self.auto_open_last_box.setChecked(
            self.preferences.value("auto_open_last_character", True, type=bool)
        )
        self.auto_save_box.setChecked(
            self.preferences.value("auto_save_session", True, type=bool)
        )
        self.performance_mode_box.setChecked(
            settings.get("performance_mode", False, bool)
        )
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
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

    def _reset_wallpaper(self) -> None:
        self.settings.remove("wallpaper")
        self.settings.sync()
        self._set_wallpaper_label("")
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

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
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

    def _interface_opacity_changed(self, value: int) -> None:
        self.settings.set("interface_opacity", value)
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

    def _accent_changed(self, accent: str) -> None:
        self.settings.set("accent_theme", accent)
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

    def _language_changed(self, language: str) -> None:
        self.settings.set("ui_language", language)
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

    def _auto_open_last_changed(self, enabled: bool) -> None:
        self.preferences.setValue("auto_open_last_character", enabled)

    def _auto_save_changed(self, enabled: bool) -> None:
        self.preferences.setValue("auto_save_session", enabled)

    def _performance_mode_changed(self, enabled: bool) -> None:
        self.settings.set("performance_mode", enabled)
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()

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
        if not isinstance(window, WuwaQtWindow):
            return

        for character_tab in window.character_tabs.values():
            tab_index = window.tabs.indexOf(character_tab)
            if tab_index >= 0:
                window.tabs.removeTab(tab_index)
            character_tab.deleteLater()
        window.character_tabs.clear()

        while window.character_sidebar_layout.count():
            item = window.character_sidebar_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        window.tabs.setCurrentIndex(0)
        window._set_sidebar_active("⌂   Banners")

    def _restore_defaults(self) -> None:
        self.preferences.clear()
        self.background_box.setChecked(True)
        self.opacity_slider.setValue(85)
        self.accent_box.setCurrentText("Auto Wallpaper")
        self.language_box.setCurrentText("PT-BR")
        self.auto_open_last_box.setChecked(True)
        self.auto_save_box.setChecked(True)
        self.performance_mode_box.setChecked(False)
        self.confirm_exit_box.setChecked(True)
        self._reset_wallpaper()
        window = self.host or self.window()
        if isinstance(window, WuwaQtWindow):
            window.apply_preferences()


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

        settings_tab = SettingsTab(
            self,
            host=host,
            settings=host.settings,
            preferences=host.preferences,
        )
        scroll.setWidget(settings_tab)
        layout.addWidget(scroll, 1)

        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)


from version import APP_VERSION


class AboutDialog(QDialog):
    VERSION = APP_VERSION

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setWindowTitle("Sobre | Tethys System")
        self.setModal(True)
        self.setMinimumSize(560, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel("Tethys System"))

        description = QLabel(
            "O Tethys System é o terminal central de Black Shores: "
            "um sistema dedicado a observar, analisar e compreender o Lamento. "
            "Nesta aplicação, seus cálculos são usados para estudar personagens, "
            "equipes, rotações e dano em Wuthering Waves."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        info = QLabel(
            f"Versão: {self.VERSION}\n"
            "Sistema: Tethys System\n"
            "Licença: MIT"
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        notes = QLabel(
            "Assim como o terminal de Black Shores, o Tethys System organiza "
            "informações para interpretar eventos complexos. Os dados do jogo "
            "são usados localmente para apoiar análises e simulações. "
            "Consulte o README para conhecer o sistema e seus recursos."
        )
        notes.setObjectName("muted")
        notes.setWordWrap(True)
        layout.addWidget(notes)
        layout.addStretch(1)

        actions = QHBoxLayout()
        readme_button = QPushButton("Abrir README")
        readme_button.clicked.connect(self._open_readme)
        actions.addWidget(readme_button)
        copy_button = QPushButton("Copiar diagnóstico")
        copy_button.clicked.connect(self._copy_diagnostic)
        actions.addWidget(copy_button)
        actions.addStretch(1)
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _open_readme(self) -> None:
        readme = Path(__file__).resolve().parent.parent / "README.txt"
        if readme.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
            return
        QMessageBox.information(
            self, "README não encontrado",
            "O arquivo README.txt não foi encontrado.")

    def _copy_diagnostic(self) -> None:
        diagnostic = (
            f"Tethys System {self.VERSION}\n"
            f"Diretório: {Path.cwd()}"
        )
        QApplication.clipboard().setText(diagnostic)
        QMessageBox.information(self, "Diagnóstico copiado",
                                """As informações foram copiadas
                                para a área de transferência.""")


class TethysCloseDialog(QMessageBox):
    def __init__(
        self,
        icon_path: str | None = None,
        icon_url: str | None = None,
        icon_local: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fechar Tethys")
        self.setText("Deseja realmente fechar o Tethys?")
        
        # Tenta usar arquivo local primeiro, depois URL, depois ícone padrão
        icon_loaded = False
        
        if icon_local:
            print(f"[Dialog] Tentando arquivo local: {icon_local}")
            try:
                local_path = Path(icon_local)
                if local_path.exists():
                    icon_pixmap = QPixmap(str(local_path))
                    if not icon_pixmap.isNull():
                        # Redimensiona para ícone pequeno (64x64 mantendo proporção)
                        icon_pixmap = icon_pixmap.scaled(
                            64, 64,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        
                        # Cria máscara circular perfeita
                        circular = QPixmap(64, 64)
                        circular.fill(Qt.transparent)
                        
                        painter = QPainter(circular)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        
                        # Desenha círculo com clipping
                        path = QPainterPath()
                        path.addEllipse(0, 0, 64, 64)
                        painter.setClipPath(path)
                        painter.drawPixmap(0, 0, icon_pixmap)
                        painter.end()
                        
                        self.setIconPixmap(circular)
                        print(f"[Dialog] Ícone local circular 64x64 carregado com sucesso")
                        icon_loaded = True
                else:
                    print(f"[Dialog] Arquivo local não encontrado: {local_path}")
            except Exception as e:
                print(f"[Dialog] Erro ao carregar arquivo local: {e}")
        
        if not icon_loaded:
            self.setIcon(QMessageBox.Icon.Warning)
            print("[Dialog] Ícone local indisponível; usando ícone padrão")
        
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        button_yes = self.button(QMessageBox.StandardButton.Yes)
        button_no = self.button(QMessageBox.StandardButton.No)
        if button_yes is not None:
            button_yes.setText("Sim")
        if button_no is not None:
            button_no.setText("Não")
            self.setDefaultButton(QMessageBox.StandardButton.No)

        self.setStyleSheet("""
            QMessageBox {
                background-color: #0c0b10;
                border: 1px solid #3d3859;
                border-radius: 12px;
            }
            QLabel {
                color: #f3f3f5;
                font-family: 'Segoe UI';
                font-size: 14px;
                background: transparent;
            }
            QPushButton {
                background-color: #1a1829;
                color: #f3f3f5;
                border: 1px solid #3d3859;
                border-radius: 6px;
                padding: 6px 20px;
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #2b2740;
                border: 1px solid #d4af37;
                color: #d4af37;
            }
            QPushButton:pressed {
                background-color: #14121f;
            }
        """)
    
    @staticmethod
    def _fetch_icon_from_url(url: str) -> QPixmap | None:
        """Baixa uma imagem de um URL, redimensiona para ícone CIRCULAR e retorna como QPixmap."""
        try:
            from urllib.request import Request, urlopen
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            with urlopen(request, timeout=5) as response:
                data = response.read()
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    # Redimensiona para ícone (64x64)
                    icon_pixmap = pixmap.scaled(
                        64, 64,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    
                    # Cria máscara circular perfeita
                    circular = QPixmap(64, 64)
                    circular.fill(Qt.transparent)
                    
                    painter = QPainter(circular)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    
                    # Desenha círculo com clipping
                    path = QPainterPath()
                    path.addEllipse(0, 0, 64, 64)
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, icon_pixmap)
                    painter.end()
                    
                    print(f"[Dialog._fetch_icon_from_url] Ícone circular 64x64 criado")
                    return circular
            return None
        except Exception as e:
            print(f"[Dialog._fetch_icon_from_url] Erro: {e}")
            return None

    @staticmethod
    def confirm_close(
        icon_path: str | None = None,
        icon_url: str | None = None,
        icon_local: str | None = None,
        parent: QWidget | None = None,
    ) -> bool:
        dialog = TethysCloseDialog(icon_path, icon_url, icon_local, parent)
        return dialog.exec() == QMessageBox.StandardButton.Yes


class ImageCharacterMismatchError(ValueError):
    def __init__(self, detected_id: str, expected_id: str) -> None:
        super().__init__(
            f"A imagem foi identificada como '{detected_id}', "
            f"mas a aba aberta é '{expected_id}'."
        )
        self.detected_id = detected_id
        self.expected_id = expected_id


class ImageImportWorker(QObject):
    preview_ready = Signal(QImage)
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(dict)
    failed = Signal(object)

    def __init__(self, path: str, target_id: str) -> None:
        super().__init__()
        self.path = path
        self.target_id = target_id

    def run(self) -> None:
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            preview = reader.read()
            if not preview.isNull():
                preview = preview.scaled(
                    1200,
                    900,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_ready.emit(preview)
            self.status.emit("Iniciando leitor isolado da build card...")
            self.progress.emit(15)
            project_root = str(Path(__file__).resolve().parents[3])
            command = [
                sys.executable,
                "-m",
                "src.wuwa_calculator.utils.ocr_process",
                self.path,
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
            result: dict[str, object] | None = None
            if process.stdout is not None:
                for raw_line in process.stdout:
                    line = raw_line.rstrip()
                    prefix, separator, payload = line.partition("\t")
                    if not separator:
                        continue
                    if prefix == "STATUS":
                        self.status.emit(payload)
                    elif prefix == "RESULT":
                        parsed = json.loads(payload)
                        if isinstance(parsed, dict):
                            result = parsed
            return_code = process.wait()
            if return_code != 0 or result is None:
                error_text = "Leitor OCR encerrou sem resultado."
                raise RuntimeError(error_text)
            stats = result.get("stats", {})
            detected_id = result.get("character_id")
            echoes = result.get("echoes", [])
            if detected_id is not None and detected_id != self.target_id:
                raise ImageCharacterMismatchError(
                    detected_id, self.target_id
                )
            self.status.emit("Finalizando atributos base...")
            self.progress.emit(100)
            self.finished.emit({
                "stats": stats,
                "character_id": detected_id,
                "echoes": echoes if isinstance(echoes, list) else [],
            })
        except Exception as error:  # pylint: disable=broad-except
            self.failed.emit(error)


class WuwaQtWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.preferences = QSettings("Tethys", "Tethys")
        self.settings = SettingsStore(settings=self.preferences)
        self.character_recent_searches: list[str] = []
        self.character_view_counts: dict[str, int] = {}
        self._character_search_popup: QFrame | None = None
        self._load_character_search_data()
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
        self._background_cache_key: tuple[str, bool, int, int] | None = None

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

        from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget
        self.convene_tracker_backend = LegacyPityTrackerWidget()
        
        def build_home() -> QWidget:
            from src.wuwa_calculator.app.home_tab import HomeTab
            return HomeTab()

        def build_teams() -> QWidget:
            from src.wuwa_calculator.app.teams_tab import TeamsTab
            return TeamsTab()

        def build_convene_tracker() -> QWidget:
            from src.wuwa_calculator.app.convene_tracker_tab import ConveneTrackerTab
            return ConveneTrackerTab(self.convene_tracker_backend)

        def build_history() -> QWidget:
            from src.wuwa_calculator.app.history_tab import HistoryTab
            return HistoryTab()

        def build_multimedia() -> QWidget:
            from src.wuwa_calculator.app.multimedia_tab import MultimediaTab
            return MultimediaTab()

        def build_obs_test() -> QWidget:
            from src.wuwa_calculator.app.obs_test_tab import ObsTestTab
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
        multimedia_tab = build_multimedia()
        tabs.removeTab(4)
        tabs.insertTab(4, multimedia_tab, self._tab_titles[4])
        self._tab_widgets[4] = multimedia_tab
        obs_test_tab = build_obs_test()
        tabs.removeTab(5)
        tabs.insertTab(5, obs_test_tab, self._tab_titles[5])
        self._tab_widgets[5] = obs_test_tab
        obs_test_tab.settingsChanged.connect(
            multimedia_tab.dps_panel.set_capture_settings
        )
        tabs.currentChanged.connect(self._handle_main_tab_changed)
        self._handle_main_tab_changed(0)

        self.character_tabs: dict[str, ResonatorTab] = {}
        self.character_open_order: list[str] = []
        self.sidebar_buttons: dict[str, QPushButton] = {}
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

        self._set_sidebar_active("Banners")
        self.setCentralWidget(shell)
        self._update_background(
            self.settings.get("background", True, bool),
            self.settings.get("wallpaper", "", str),
        )
        self.character_load_button.clicked.connect(
            self.open_character_tab)
        self.character_id_entry.returnPressed.connect(
            self.open_character_tab)
        self.character_id_entry.textChanged.connect(
            self._on_character_search_text_changed)
        self.import_button.clicked.connect(self.open_import_dialog)
        self.apply_preferences()
        self._restore_last_session()

    def _restore_last_session(self) -> None:
        if not self.preferences.value("auto_open_last_character", True, type=bool):
            return
        last_character = self.preferences.value("last_character", "", type=str)
        if not last_character:
            return
        normalized = self._normalize_character_id(last_character)
        if not normalized:
            return
        for candidate in KNOWN_CHARACTER_IDS:
            if self._normalize_character_id(candidate) == normalized:
                self.character_id_entry.setText(candidate)
                self.open_character_tab()
                break

    def apply_preferences(self) -> None:
        self.settings.sync()
        background = self.settings.get("background", True, bool)
        wallpaper = self.settings.get("wallpaper", "", str)
        interface_opacity = self.settings.get("interface_opacity", 85, int)
        accent_theme = self.settings.get("accent_theme", "Auto Wallpaper", str)
        performance_mode = self.settings.get("performance_mode", False, bool)
        app = QApplication.instance()

        palette = wallpaper_palette(wallpaper if background else "")
        effective_accent = palette[3] if accent_theme == "Auto Wallpaper" else accent_preset(accent_theme)

        if app is not None:
            app.setStyleSheet(application_qss(
                show_background=background,
                wallpaper=wallpaper,
                interface_opacity=interface_opacity,
                accent_theme=accent_theme,
            ))
        for widget in self.findChildren(QWidget):
            apply_palette = getattr(widget, "apply_wallpaper_palette", None)
            if callable(apply_palette):
                apply_palette(
                    *palette,
                    theme_accent=effective_accent,
                )
        refresh_glows(self, performance_mode=performance_mode)
        self._update_background(background, wallpaper)

    def _update_background(self, enabled: bool, wallpaper: str) -> None:
        self.background_label.setVisible(enabled)
        if not enabled:
            self._background_cache_key = None
            return

        cache_key = (wallpaper, enabled, self.width(), self.height())
        if cache_key == self._background_cache_key:
            return

        source = (
            QUrl.fromUserInput(wallpaper).toLocalFile()
            if wallpaper else "")
        default_background = get_asset_path("app_background_reference.png")
        pixmap = QPixmap(source or str(default_background))

        if pixmap.isNull():
            pixmap = QPixmap(str(default_background))
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (scaled.width() - self.width()) // 2)
        top = max(0, (scaled.height() - self.height()) // 2)
        self.background_label.setGeometry(self.rect())
        self.background_label.setPixmap(
            scaled.copy(left, top, self.width(), self.height()))
        self.background_label.lower()
        self._background_cache_key = cache_key

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_background(
            self.settings.get("background", True, bool),
            self.settings.get("wallpaper", "", str),
        )

    def closeEvent(self, event) -> None:
        if self.preferences.value("confirm_exit", True, type=bool):
            if not TethysCloseDialog.confirm_close(
                icon_path=TETHYS_CLOSE_ICON_PATH,
                icon_url=TETHYS_CLOSE_ICON_URL,
                icon_local=TETHYS_CLOSE_ICON_LOCAL,
                parent=self,
            ):
                event.ignore()
                return
        multimedia_tab = self.tabs.widget(3) if hasattr(self, "tabs") else None
        if multimedia_tab is not None and hasattr(multimedia_tab, "dps_panel"):
            multimedia_tab.dps_panel._stop_live_analysis()
        event.accept()

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
        layout.addWidget(button)
        return button

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

    def open_about(self) -> None:
        AboutDialog(self).exec()

    def open_import_dialog(self) -> None:
        if getattr(self, "_import_dialog", None) is not None:
            dialog = self._import_dialog
            if dialog.isVisible():
                dialog.raise_()
                dialog.activateWindow()
                return
        character_tab = self.tabs.currentWidget()
        if not isinstance(character_tab, ResonatorTab):
            QMessageBox.information(
                self,
                "Personagem não carregado",
                "Carregue uma ID de personagem antes de importar a imagem.",
            )
            return
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
        self.tabs.setCurrentIndex(index)

    def _handle_main_tab_changed(self, index: int) -> None:
        current_widget = self.tabs.widget(index)
        if isinstance(current_widget, ResonatorTab):
            previous_index = self._active_main_index
            if previous_index is not None and previous_index != index:
                previous_widget = self.tabs.widget(previous_index)
                if previous_widget is not None:
                    if hasattr(previous_widget, "set_active"):
                        previous_widget.set_active(False)
                    previous_widget.setUpdatesEnabled(False)
            current_widget.setUpdatesEnabled(True)
            current_widget.show()
            current_widget.update()
            self._active_main_index = index
            return
        previous_index = self._active_main_index
        if previous_index is not None and previous_index != index:
            previous_widget = self._tab_widgets.get(previous_index)
            if previous_widget is not None:
                if hasattr(previous_widget, "set_active"):
                    previous_widget.set_active(False)
                previous_widget.setUpdatesEnabled(False)
        self._ensure_main_tab(index)
        current_widget = self._tab_widgets.get(index)
        if current_widget is not None:
            current_widget.setUpdatesEnabled(True)
            if hasattr(current_widget, "set_active"):
                current_widget.set_active(True)
            current_widget.show()
            current_widget.update()
        self._active_main_index = index
        if self.tabs.tabText(index) == "Convene Tracker" and hasattr(self, "convene_tracker_backend"):
            self.convene_tracker_backend.refresh_convene_context_from_log()

    def _set_sidebar_active(self, active_label: str) -> None:
        for label, button in self.sidebar_buttons.items():
            button.setObjectName("navActive"
                                 if label == active_label else "nav")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

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
            previous_tab = self.character_tabs.get(previous_character_id)
            if previous_tab is not None:
                self.tabs.setCurrentWidget(previous_tab)
                previous_label = (
                    f"{self._element_icon(CHARACTER_ELEMENTS.get(previous_character_id))}   "
                    f"{previous_character_id.title()}"
                )
                self._set_sidebar_active(previous_label)
            else:
                self.tabs.setCurrentIndex(0)
                self._set_sidebar_active("Banners")
            return

        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, ResonatorTab):
            current_id = current_widget.current_id
            self._set_sidebar_active(
                f"{self._element_icon(CHARACTER_ELEMENTS.get(current_id))}   "
                f"{current_id.title()}"
            )
        else:
            current_index = self.tabs.currentIndex()
            if 0 <= current_index < len(self._tab_titles):
                self._set_sidebar_active(self._tab_titles[current_index])

    @staticmethod
    def _normalize_character_id(value: str) -> str:
        folded = "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", "", folded)

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

    def _register_character_search(self, character_id: str) -> None:
        normalized = self._normalize_character_id(character_id)
        if not normalized:
            return
        self.character_recent_searches = [
            item for item in self.character_recent_searches
            if self._normalize_character_id(item) != normalized
        ]
        self.character_recent_searches.insert(0, character_id)
        self.character_recent_searches = self.character_recent_searches[:10]
        self.character_view_counts[character_id] = (
            self.character_view_counts.get(character_id, 0) + 1
        )
        self._save_character_search_data()

    def _get_character_search_results(
        self,
        text: str,
        limit: int = 8,
    ) -> list[str]:
        query = self._normalize_character_id(text)
        if not query:
            return []
        scored: list[tuple[float, str]] = []
        for character_id in KNOWN_CHARACTER_IDS:
            candidate = self._normalize_character_id(character_id)
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
    def _get_character_display_name(character_id: str) -> str:
        return character_id.replace("_", " ").title()

    def _get_most_viewed_characters(self, limit: int = 5) -> list[str]:
        valid_ids = {
            self._normalize_character_id(item): item
            for item in KNOWN_CHARACTER_IDS
        }
        result: list[str] = []
        for character_id, _count in sorted(
            self.character_view_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            valid_id = valid_ids.get(self._normalize_character_id(character_id))
            if valid_id and valid_id not in result:
                result.append(valid_id)
            if len(result) >= limit:
                break
        return result

    def _get_recent_characters(self, limit: int = 5) -> list[str]:
        valid_ids = {
            self._normalize_character_id(item): item
            for item in KNOWN_CHARACTER_IDS
        }
        result: list[str] = []
        for character_id in self.character_recent_searches:
            valid_id = valid_ids.get(self._normalize_character_id(character_id))
            if valid_id and valid_id not in result:
                result.append(valid_id)
            if len(result) >= limit:
                break
        return result

    def _show_character_search_popup(self) -> None:
        text = self.character_id_entry.text().strip()
        if not text:
            sections = [
                ("Recentes", self._get_recent_characters()),
                ("Frequentes", self._get_most_viewed_characters()),
            ]
            self._rebuild_character_search_popup(sections)
            return
        query = self._normalize_character_id(text)
        recent = [
            character_id
            for character_id in self._get_recent_characters()
            if query in self._normalize_character_id(character_id)
        ]
        frequent = [
            character_id
            for character_id in self._get_most_viewed_characters()
            if query in self._normalize_character_id(character_id)
        ]
        self._rebuild_character_search_popup([
            ("Sugestões", self._get_character_search_results(text)),
            ("Recentes", recent),
            ("Frequentes", frequent),
        ])

    def _rebuild_character_search_popup(
        self,
        sections: list[tuple[str, list[str]]],
    ) -> None:
        self._hide_character_search_popup()
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
            self,
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
                    f"{self._element_icon(CHARACTER_ELEMENTS.get(character_id))}  "
                    f"{self._get_character_display_name(character_id)}"
                )
                button.setObjectName("characterSearchItem")
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(f"ID: {character_id}")
                button.clicked.connect(
                    lambda checked=False, cid=character_id:
                    self._select_character_search_result(cid)
                )
                layout.addWidget(button)
        popup.adjustSize()
        entry = self.character_id_entry
        popup.move(entry.mapToGlobal(entry.rect().bottomLeft()))
        popup.setFixedWidth(max(entry.width(), 260))
        popup.show()
        self._character_search_popup = popup

    def _select_character_search_result(self, character_id: str) -> None:
        self._hide_character_search_popup()
        self.character_id_entry.setText(character_id)
        self.open_character_tab()

    def _hide_character_search_popup(self) -> None:
        popup = self._character_search_popup
        if popup is not None:
            popup.close()
            popup.deleteLater()
        self._character_search_popup = None

    def _on_character_search_text_changed(self, text: str) -> None:
        self._show_character_search_popup()

    def open_character_tab(self) -> None:
        self._hide_character_search_popup()
        typed_text = self.character_id_entry.text().strip()
        if not typed_text:
            self.character_status.setText("Digite um personagem")
            return
        target = self._normalize_character_id(typed_text)
        character_id = next(
            (
                item for item in KNOWN_CHARACTER_IDS
                if self._normalize_character_id(item) == target
            ),
            None,
        )
        if character_id is None:
            suggestions = self._get_character_search_results(typed_text, limit=1)
            character_id = suggestions[0] if suggestions else None
        if character_id is None:
            self.character_status.setText("Personagem não encontrado")
            return

        character_tab = self.character_tabs.get(character_id)
        if character_tab is None:
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
        self._register_character_search(character_id)
        if self.preferences.value("auto_save_session", True, type=bool):
            self.preferences.setValue("last_character", character_id)
            self.preferences.sync()
        self._set_sidebar_active(
            f"{self._element_icon(CHARACTER_ELEMENTS.get(character_id))}   {character_id.title()}")
        self.character_id_entry.blockSignals(True)
        self.character_id_entry.clear()
        self.character_id_entry.blockSignals(False)
        self._hide_character_search_popup()
        self.character_status.clear()


class AdaptiveStatusSpinner(QWidget):
    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.angle = 0
        self._active = False
        self._state = "idle"
        self.setMinimumSize(72, 72)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._state = "loading" if active else self._state
        if active:
            self._timer.start(40)
        else:
            self._timer.stop()
        self.update()

    def set_state(self, state: str) -> None:
        self._state = state
        self.set_active(state == "loading")

    def _advance(self) -> None:
        self.angle = (self.angle + 8) % 360
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        radius = min(self.width(), self.height()) // 2 - 10
        pen = QPen(QColor(self.color), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self._state == "success":
            check = QPainterPath()
            check.moveTo(center.x() - radius * 0.58, center.y())
            check.lineTo(center.x() - radius * 0.12, center.y() + radius * 0.42)
            check.lineTo(center.x() + radius * 0.68, center.y() - radius * 0.48)
            painter.drawPath(check)
        elif self._state == "error":
            painter.drawLine(
                center.x() - radius * 0.42,
                center.y() - radius * 0.42,
                center.x() + radius * 0.42,
                center.y() + radius * 0.42,
            )
            painter.drawLine(
                center.x() + radius * 0.42,
                center.y() - radius * 0.42,
                center.x() - radius * 0.42,
                center.y() + radius * 0.42,
            )
        elif self._state == "loading":
            painter.drawArc(
                center.x() - radius,
                center.y() - radius,
                radius * 2,
                radius * 2,
                (90 - self.angle) * 16,
                -275 * 16,
            )
        painter.setPen(QPen(QColor(self.color), 1))
        painter.drawEllipse(center, 3, 3)


class AdaptiveDataGrid(QFrame):
    def __init__(self, theme: ThemeConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("ocrGrid")

    def set_theme(self, theme: ThemeConfig) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        horizon = int(height * 0.47)
        neon = QColor(self._theme.primary_neon_color)
        painter.fillRect(self.rect(), QColor(self._theme.panel_bg_color))
        glow = QColor(neon)
        glow.setAlpha(24)
        painter.fillRect(0, horizon - 34, width, 68, glow)
        grid_color = QColor(neon)
        grid_color.setAlpha(48)
        painter.setPen(QPen(grid_color, 1))
        vanishing_x = width // 2
        for index in range(-12, 13):
            bottom_x = vanishing_x + index * max(26, width // 10)
            painter.drawLine(vanishing_x, horizon, bottom_x, height)
        for distance in range(1, 10):
            progress = distance / 10.0
            y = horizon + int((height - horizon) * (progress ** 1.65))
            painter.drawLine(0, y, width, y)
        for distance in range(1, 6):
            progress = distance / 6.0
            y = horizon - int(horizon * (progress ** 0.85))
            painter.drawLine(0, y, width, y)
        horizon_color = QColor(neon)
        horizon_color.setAlpha(155)
        painter.setPen(QPen(horizon_color, 2))
        painter.drawLine(0, horizon, width, horizon)
        painter.end()


class CustomImportPopup(QDialog):
    def __init__(
        self,
        parent: QWidget,
        character_tab: ResonatorTab,
        theme: ThemeConfig | None = None,
        wallpaper_path: str | None = None,
    ):
        super().__init__(parent)
        self.character_tab = character_tab
        self.pending_stats: dict[str, float] = {}
        self.pending_echoes: list[str] = []
        self._theme = theme or self._theme_from_parent(parent)
        self.wallpaper_path = wallpaper_path

        self.setObjectName("ocrImportDialog")
        self.setWindowTitle("Importar Dados")
        self.resize(820, 680)
        self._wallpaper_label = QLabel(self)
        self._wallpaper_label.setObjectName("ocrWallpaper")
        self._wallpaper_label.lower()
        self._wallpaper_opacity = QGraphicsOpacityEffect(self._wallpaper_label)
        self._wallpaper_opacity.setOpacity(0.30)
        self._wallpaper_label.setGraphicsEffect(self._wallpaper_opacity)
        self.apply_theme(self._theme)
        if wallpaper_path:
            self.set_custom_wallpaper(wallpaper_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        self.title_icon = QLabel("◇")
        self.title_icon.setObjectName("ocrTitleIcon")
        heading.addWidget(self.title_icon)
        character_name = self.character_tab.character_name.text().strip() or "Resonador"
        title = QLabel(f"Importar Dados  ·  {character_name}")
        title.setObjectName("ocrDialogTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.protocol_label = QLabel("PRÉVIA PRONTA")
        self.protocol_label.setObjectName("ocrDialogProtocol")
        heading.addWidget(self.protocol_label)
        layout.addLayout(heading)

        content = QHBoxLayout()
        content.setSpacing(14)

        scan_panel = QFrame()
        scan_panel.setObjectName("ocrScanPanel")
        scan_layout = QVBoxLayout(scan_panel)
        scan_layout.setContentsMargins(12, 12, 12, 12)
        scan_layout.setSpacing(8)
        scan_label = QLabel("GRADE DE LEITURA")
        scan_label.setObjectName("ocrSectionLabel")
        scan_layout.addWidget(scan_label)

        self.scan_grid = AdaptiveDataGrid(self._theme)
        grid_layout = QVBoxLayout(self.scan_grid)
        grid_layout.setContentsMargins(18, 18, 18, 18)
        grid_layout.addStretch(1)
        self.grid_hint = QLabel("Aguardando imagem\n\nArraste ou selecione uma screenshot de atributos")
        self.grid_hint.setObjectName("ocrGridHint")
        self.grid_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid_hint.setWordWrap(True)
        grid_layout.addWidget(self.grid_hint)
        self.image_preview = QLabel()
        self.image_preview.setObjectName("ocrImagePreview")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedHeight(320)
        self.image_preview.setVisible(True)
        grid_layout.addWidget(self.image_preview, 1)
        grid_layout.addStretch(1)
        self.select_button = QPushButton("↑  Selecionar imagem")
        self.select_button.setObjectName("ocrSelectButton")
        self.select_button.setFixedHeight(38)
        self.select_button.clicked.connect(self.select_image)
        self.scan_line = QFrame(self.scan_grid)
        self.scan_line.setObjectName("ocrScanLine")
        self.scan_line.setFixedHeight(2)
        self.scan_line.setGeometry(0, 4, 1, 2)
        self.scan_animation = QPropertyAnimation(self.scan_line, b"pos", self)
        self.scan_animation.setDuration(4800)
        self.scan_animation.setLoopCount(-1)
        self.scan_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.scan_animation.setStartValue(QPoint(8, 8))
        self.scan_animation.setEndValue(QPoint(8, 8))
        scan_layout.addWidget(self.scan_grid, 1)
        scan_layout.addWidget(self.select_button)
        content.addWidget(scan_panel, 3)
        QTimer.singleShot(0, self._configure_scan_line)

        status_panel = QFrame()
        status_panel.setObjectName("ocrStatusPanel")
        status_panel.setProperty("interactive", True)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(10)
        status_title = QLabel("ALVO DA IMPORTAÇÃO")
        status_title.setObjectName("ocrSectionLabel")
        status_layout.addWidget(status_title)
        character_card = QFrame()
        character_card.setObjectName("ocrCharacterCard")
        character_layout = QHBoxLayout(character_card)
        character_layout.setContentsMargins(8, 8, 8, 8)
        self.character_preview = QLabel()
        self.character_preview.setObjectName("ocrCharacterPreview")
        self.character_preview.setFixedSize(78, 96)
        self.character_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = self.character_tab.character_image.pixmap()
        if pixmap is not None and not pixmap.isNull():
            preview_pixmap = pixmap.scaled(
                78, 96, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.character_preview.setPixmap(preview_pixmap)
            self.title_icon.setPixmap(preview_pixmap.scaled(
                28, 34, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self.character_preview.setText("◇")
        character_layout.addWidget(self.character_preview)
        identity = QVBoxLayout()
        name_label = QLabel(character_name)
        name_label.setObjectName("ocrCharacterName")
        level_label = QLabel("NÍVEL 80  //  BUILD ATIVA")
        level_label.setObjectName("ocrCharacterMeta")
        identity.addWidget(name_label)
        identity.addWidget(level_label)
        identity.addStretch(1)
        character_layout.addLayout(identity, 1)
        status_layout.addWidget(character_card)
        self.status_ring = AdaptiveStatusSpinner(self._theme.primary_neon_color)
        self.status_ring.setObjectName("ocrStatusRing")
        status_glow = QGraphicsDropShadowEffect(self.status_ring)
        status_glow.setBlurRadius(22)
        status_glow.setOffset(0, 0)
        status_glow.setColor(QColor(self._theme.primary_neon_color))
        self.status_ring.setGraphicsEffect(status_glow)
        status_layout.addWidget(self.status_ring)
        self.status_label = QLabel("Aguardando imagem")
        self.status_label.setObjectName("ocrStatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.live_telemetry = QLabel("Pronto para receber uma build card")
        self.live_telemetry.setObjectName("ocrLiveTelemetry")
        self.live_telemetry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_telemetry.setWordWrap(True)
        status_layout.addWidget(self.live_telemetry)
        self.status_items: dict[str, QLabel] = {}
        self.status_texts: dict[str, QLabel] = {}
        for key, label in (
            ("waiting", "Aguardando imagem"),
            ("scanning", "Analisando dados"),
            ("detected", "Dados detectados"),
            ("error", "Erro de leitura"),
        ):
            status_row = QHBoxLayout()
            dot = QLabel("●")
            dot.setObjectName("ocrStatusDot")
            dot.setProperty("state", key)
            status_text = QLabel(label)
            status_text.setObjectName("ocrStatusItem")
            status_row.addWidget(dot)
            status_row.addWidget(status_text, 1)
            status_layout.addLayout(status_row)
            self.status_items[key] = dot
            self.status_texts[key] = status_text
        status_layout.addStretch(1)
        content.addWidget(status_panel, 2)
        layout.addLayout(content, 1)

        preview_panel = QFrame()
        preview_panel.setObjectName("ocrPreviewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(12, 8, 12, 8)
        preview_title = QLabel("Pré-visualização dos dados detectados")
        preview_title.setObjectName("ocrSectionLabel")
        preview_layout.addWidget(preview_title)
        self.preview_label = QLabel("Aguardando leitura do OCR...")
        self.preview_label.setObjectName("ocrPreviewText")
        preview_layout.addWidget(self.preview_label)
        self.stats_grid = QGridLayout()
        self.stats_grid.setContentsMargins(0, 2, 0, 2)
        self.stats_grid.setHorizontalSpacing(8)
        self.stats_grid.setVerticalSpacing(8)
        preview_layout.addLayout(self.stats_grid)
        self.echo_preview_title = QLabel("Echoes detectados na build card")
        self.echo_preview_title.setObjectName("ocrSectionLabel")
        self.echo_preview_title.setVisible(False)
        preview_layout.addWidget(self.echo_preview_title)
        self.echo_preview_grid = QGridLayout()
        self.echo_preview_grid.setContentsMargins(0, 2, 0, 2)
        self.echo_preview_grid.setHorizontalSpacing(8)
        self.echo_preview_grid.setVerticalSpacing(8)
        preview_layout.addLayout(self.echo_preview_grid)
        layout.addWidget(preview_panel)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancelar")
        cancel_button.setObjectName("ocrCancelButton")
        cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("Confirmar Importação")
        self.confirm_button.setObjectName("ocrConfirmButton")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.confirm_import)
        actions.addWidget(cancel_button)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)

        self.ocr_thread: QThread | None = None
        self.ocr_worker: ImageImportWorker | None = None
        self._source_pixmap = QPixmap()
        self.apply_theme(self._theme)
        self._set_status_phase("waiting")

    @staticmethod
    def _theme_from_parent(parent: QWidget | None) -> ThemeConfig:
        settings = SettingsStore()
        return theme_config(
            settings.get("wallpaper", "", str),
            settings.get("interface_opacity", 85, int),
            settings.get("accent_theme", "Auto Wallpaper", str),
        )

    @property
    def theme(self) -> ThemeConfig:
        return self._theme

    def apply_theme(self, theme: ThemeConfig) -> None:
        self._theme = theme
        self.setStyleSheet(f"""
            QDialog#ocrImportDialog {{ background: {theme.panel_bg_color_with_alpha}; color: {theme.text_color}; border: 1px solid {theme.secondary_neon_color}; }}
            QLabel#ocrWallpaper {{ background: transparent; }}
            QLabel#ocrDialogTitle {{ color: {theme.primary_neon_color}; }}
            QLabel#ocrTitleIcon {{ color: {theme.secondary_neon_color}; font-size: 24px; }}
            QLabel#ocrDialogProtocol, QLabel#ocrSectionLabel {{ color: {theme.primary_neon_color}; }}
            QFrame#ocrScanPanel, QFrame#ocrStatusPanel {{ background: {theme.panel_bg_color_with_alpha}; border-color: {theme.secondary_neon_color}; }}
            QFrame#ocrGrid {{ border-color: {theme.primary_neon_color}; background: {theme.panel_bg_color_with_alpha}; }}
            QLabel#ocrImagePreview {{ background: {theme.panel_bg_color_with_alpha}; border: 1px solid {theme.secondary_neon_color}; border-radius: 4px; }}
            QFrame#ocrScanLine {{ background: {theme.primary_neon_color}; }}
            QPushButton#ocrSelectButton, QPushButton#ocrConfirmButton {{ background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 {theme.button_gradient_start}, stop: 1 {theme.button_gradient_end}); color: {theme.text_color}; border-color: {theme.secondary_neon_color}; }}
            QPushButton#ocrSelectButton:hover, QPushButton#ocrConfirmButton:hover {{ border-color: {theme.primary_neon_color}; }}
            QPushButton#ocrCancelButton {{ background: {theme.panel_bg_color_with_alpha}; color: {theme.muted_text_color}; border-color: {theme.secondary_neon_color}; }}
            QFrame#ocrCharacterCard, QFrame#ocrPreviewPanel {{ background: {theme.panel_bg_color_with_alpha}; border-color: {theme.secondary_neon_color}; }}
            QLabel#ocrCharacterName, QLabel#ocrStatusLabel {{ color: {theme.text_color}; }}
            QLabel#ocrCharacterMeta, QLabel#ocrPreviewText {{ color: {theme.secondary_neon_color}; }}
            QFrame#ocrStatCard {{ background: {theme.panel_bg_color_with_alpha}; border: 1px solid {theme.secondary_neon_color}; border-radius: 5px; }}
            QLabel#ocrStatName {{ color: {theme.secondary_neon_color}; font-size: 9px; font-weight: 800; }}
            QLabel#ocrStatValue {{ color: {theme.text_color}; font-size: 15px; font-weight: 900; }}
            QFrame#ocrEchoCard {{ background: {theme.panel_bg_color_with_alpha}; border: 1px solid {theme.secondary_neon_color}; border-radius: 5px; }}
            QLabel#ocrEchoName {{ color: {theme.secondary_neon_color}; font-size: 10px; font-weight: 900; }}
            QLabel#ocrEchoDetails {{ color: {theme.text_color}; font-size: 8px; }}
                    QLabel#ocrStatusItem {{ color: {theme.muted_text_color}; padding: 2px 4px; border-radius: 3px; }}
                    QLabel#ocrStatusItem[active="true"] {{ color: {theme.text_color}; background: {theme.panel_bg_color_with_alpha}; font-weight: 800; }}
                    QLabel#ocrStatusItem[complete="true"] {{ color: {theme.primary_neon_color}; }}
            QLabel#ocrLiveTelemetry {{ color: {theme.secondary_neon_color}; font-size: 10px; font-weight: 800; padding: 6px; border: 1px solid {theme.secondary_neon_color}; border-radius: 5px; }}
            QLabel#ocrStatusDot {{ color: {theme.muted_text_color}; font-size: 11px; }}
            QLabel#ocrStatusDot[state="scanning"], QLabel#ocrStatusDot[state="detected"] {{ color: {theme.primary_neon_color}; }}
            QLabel#ocrStatusDot[state="error"] {{ color: {theme.secondary_neon_color}; }}
            QLabel#ocrStatusDot[active="false"] {{ color: {theme.muted_text_color}; }}
        """)
        if not hasattr(self, "status_ring"):
            return
        self.status_ring.set_color(theme.primary_neon_color)
        self.scan_grid.set_theme(theme)
        status_effect = self.status_ring.graphicsEffect()
        if isinstance(status_effect, QGraphicsDropShadowEffect):
            status_effect.setColor(QColor(theme.primary_neon_color))
        for widget, color, blur in (
            (self.select_button, theme.secondary_neon_color, 18),
            (self.confirm_button, theme.secondary_neon_color, 18),
        ):
            effect = QGraphicsDropShadowEffect(widget)
            effect.setBlurRadius(blur)
            effect.setOffset(0, 0)
            effect.setColor(QColor(color))
            widget.setGraphicsEffect(effect)
        scan_effect = QGraphicsDropShadowEffect(self.scan_line)
        scan_effect.setBlurRadius(14)
        scan_effect.setOffset(0, 0)
        scan_effect.setColor(QColor(theme.primary_neon_color))
        self.scan_line.setGraphicsEffect(scan_effect)

    def set_custom_wallpaper(self, path: str | None) -> None:
        self.wallpaper_path = path or None
        if not path:
            self._wallpaper_label.clear()
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._wallpaper_label.clear()
            return
        self._wallpaper_label.setPixmap(pixmap)
        self._wallpaper_label.setScaledContents(True)
        self._wallpaper_label.setGeometry(self.rect())
        self._wallpaper_label.lower()

    def _set_source_preview(self, image: QImage) -> None:
        self._source_pixmap = QPixmap.fromImage(image)
        if self._source_pixmap.isNull():
            return
        self.grid_hint.hide()
        self._refresh_source_preview()

    def _refresh_source_preview(self) -> None:
        if self._source_pixmap.isNull() or self.image_preview.size().isEmpty():
            return
        self.image_preview.setPixmap(self._source_pixmap.scaled(
            self.image_preview.contentsRect().size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._wallpaper_label.setGeometry(self.rect())
        self._refresh_source_preview()
        self._configure_scan_line()

    def _configure_scan_line(self) -> None:
        if not hasattr(self, "scan_grid") or not hasattr(self, "scan_line"):
            return
        width = max(1, self.scan_grid.width() - 16)
        y = max(8, self.scan_grid.height() // 2)
        self.scan_line.setFixedWidth(width)
        self.scan_line.move(8, y)
        bottom_y = max(8, self.scan_grid.height() - 8)
        self.scan_animation.setStartValue(QPoint(8, 8))
        self.scan_animation.setKeyValueAt(0.5, QPoint(8, bottom_y))
        self.scan_animation.setEndValue(QPoint(8, 8))
        scanning = self.ocr_thread is not None and self.ocr_thread.isRunning()
        if scanning and self.scan_animation.state() != QAbstractAnimation.State.Running:
            self.scan_animation.start()
        elif not scanning:
            self.scan_animation.stop()

    def _render_stats_preview(self, stats: dict[str, float]) -> None:
        percentage_stats = {
            "crit_rate",
            "crit_dmg",
            "energy_regen",
            "elemental_dmg",
            "heavy_atk_dmg",
            "liberation_dmg",
            "skill_dmg",
        }
        while self.stats_grid.count():
            item = self.stats_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, (key, value) in enumerate(stats.items()):
            card = QFrame()
            card.setObjectName("ocrStatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(1)
            label = QLabel(key.replace("_", " ").title())
            label.setObjectName("ocrStatName")
            suffix = "%" if key in percentage_stats else ""
            value_label = QLabel(f"{value:g}{suffix}")
            value_label.setObjectName("ocrStatValue")
            card_layout.addWidget(label)
            card_layout.addWidget(value_label)
            self.stats_grid.addWidget(card, index // 4, index % 4)

    def _render_echoes_preview(self, echoes: list[dict[str, object]]) -> None:
        while self.echo_preview_grid.count():
            item = self.echo_preview_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.echo_preview_title.setVisible(bool(echoes))
        for index, echo in enumerate(echoes):
            card = QFrame()
            card.setObjectName("ocrEchoCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(3)
            name = QLabel(str(echo.get("name", "Echo")))
            name.setObjectName("ocrEchoName")
            name.setWordWrap(True)
            attributes = echo.get("attributes", [])
            attribute_lines = [str(value) for value in attributes] if isinstance(attributes, list) else []
            main_stat = str(echo.get("main_stat", attribute_lines[0] if attribute_lines else "--"))
            sub_stats = echo.get("sub_stats", attribute_lines[1:])
            sub_stat_lines = [str(value) for value in sub_stats] if isinstance(sub_stats, list) else []
            cost = echo.get("cost", "--")
            set_bonus = str(echo.get("set_bonus", "--"))
            details = QLabel(
                f"Cost: {cost or '--'}\n"
                f"Set: {set_bonus}\n"
                f"Main: {main_stat}\n"
                "Sub-stats: " + ("; ".join(sub_stat_lines) or "--")
            )
            details.setObjectName("ocrEchoDetails")
            details.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(details)
            self.echo_preview_grid.addWidget(card, index // 2, index % 2)

    def _set_status_phase(self, phase: str) -> None:
        phase_order = ("waiting", "scanning", "detected", "error")
        current_index = phase_order.index(phase) if phase in phase_order else 0
        if hasattr(self, "status_ring"):
            state = {
                "waiting": "idle",
                "scanning": "loading",
                "detected": "success",
                "error": "error",
            }.get(phase, "idle")
            self.status_ring.set_state(state)
        for key, dot in self.status_items.items():
            dot.setProperty("active", "true" if key == phase else "false")
            dot.setProperty("complete", "true" if key in phase_order[:current_index] else "false")
            dot.style().unpolish(dot)
            dot.style().polish(dot)
            status_text = self.status_texts[key]
            status_text.setProperty("active", "true" if key == phase else "false")
            status_text.setProperty("complete", "true" if key in phase_order[:current_index] else "false")
            status_text.style().unpolish(status_text)
            status_text.style().polish(status_text)

    def _set_scan_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.protocol_label.setText("PROCESSANDO")
        self._set_status_phase("scanning")
        self.live_telemetry.setText(message)

    def select_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar imagem",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp)"
        )

        if not path:
            return

        self.select_button.setEnabled(False)
        self.confirm_button.setEnabled(False)
        self.pending_stats = {}
        self.pending_echoes = []
        self.status_texts["detected"].setText("Dados detectados")
        self.status_texts["error"].setText("Erro de leitura")
        self.preview_label.setText("Processando leitura da imagem...")
        self.preview_label.show()
        self.protocol_label.setText("PROCESSANDO")
        self._set_scan_status("Escaneando...")
        self._configure_scan_line()

        self.ocr_thread = QThread(self)
        self.ocr_worker = ImageImportWorker(path, self.character_tab.current_id)
        self.ocr_worker.moveToThread(self.ocr_thread)
        self.ocr_thread.started.connect(self.ocr_worker.run)
        self.ocr_worker.preview_ready.connect(self._set_source_preview)
        self.ocr_worker.status.connect(self._set_scan_status)
        self.ocr_worker.finished.connect(self._import_finished)
        self.ocr_worker.failed.connect(self._import_failed)
        self.ocr_worker.finished.connect(self.ocr_thread.quit)
        self.ocr_worker.failed.connect(self.ocr_thread.quit)
        self.ocr_thread.finished.connect(self._clear_import_worker)
        self.ocr_thread.start(QThread.Priority.LowPriority)
        self._configure_scan_line()

    def _import_finished(self, result: dict) -> None:
        self.select_button.setEnabled(True)
        stats = result.get("stats", {})
        if stats or self.pending_echoes:
            self.pending_stats = stats
            echoes = result.get("echoes", [])
            self.pending_echoes = echoes if isinstance(echoes, list) else []
            self.status_texts["detected"].setText("Leitura concluída")
            self._set_status_phase("detected")
            self.status_label.setText("Confira os dados e confirme a importação.")
            self.protocol_label.setText("PRÉVIA PRONTA")
            echo_count = len(echoes) if isinstance(echoes, list) else 0
            self.live_telemetry.setText(
                f"Leitura concluída: {len(stats)} atributos e {echo_count} Echo(s) encontrados"
            )
            self._render_stats_preview(stats)
            self._render_echoes_preview(
                [echo for echo in self.pending_echoes if isinstance(echo, dict)]
            )
            self.confirm_button.setEnabled(True)
            return

        message = (
            "Não foi possível encontrar informações na imagem.\n\n"
            "Verifique se a screenshot contém os atributos do personagem."
        )
        self.status_label.setText(message)
        self.status_texts["error"].setText("Erro de leitura")
        self._set_status_phase("error")
        self.live_telemetry.setText("Nenhum atributo confiável foi localizado")
        QMessageBox.critical(self, "Nenhum dado encontrado", message)

    def confirm_import(self) -> None:
        if not self.pending_stats and not self.pending_echoes:
            return
        self.character_tab.apply_imported_stats(self.pending_stats, self.pending_echoes)
        self._set_status_phase("detected")
        self.status_label.setText("Importado com sucesso (5 estrelas)")
        self.accept()

    def _import_failed(self, error: object) -> None:
        self.select_button.setEnabled(True)
        if isinstance(error, FileNotFoundError):
            message = "Arquivo não encontrado."
            title = "Erro ao importar"
        elif isinstance(error, ImageCharacterMismatchError):
            message = (
                f"Esta imagem pertence a '{error.detected_id}', mas a aba "
                f"aberta é '{error.expected_id}'. Carregue a ID correta "
                "antes de importar esta build card."
            )
            title = "Personagem incompatível"
        elif isinstance(error, (OSError, ValueError)):
            message = (
                "Não foi possível ler a imagem. Verifique se o arquivo é "
                "uma imagem válida e tente novamente."
            )
            title = "Erro ao importar"
        elif isinstance(error, ImportError):
            message = (
                "O recurso de ler imagens não está disponível. "
                "Uma dependência necessária não está instalada."
            )
            title = "Recurso indisponível"
        elif isinstance(error, RuntimeError):
            message = (
                "Não foi possível processar a imagem. Tente novamente "
                "ou utilize outra imagem."
            )
            title = "Erro ao processar"
        else:
            message = (
                "Ocorreu um erro inesperado ao processar a imagem. "
                "Se o problema persistir, reporte o erro."
            )
            title = "Erro inesperado"

        print(f"[Importação] {type(error).__name__}: {error}")
        self.scan_animation.stop()
        self._set_status_phase("error")
        self.live_telemetry.setText("Falha na leitura da build card")
        self.status_texts["error"].setText("Erro de leitura")
        self.protocol_label.setText("ERRO DE LEITURA")
        self.status_label.setText(message)
        QMessageBox.critical(self, title, message)

    def _clear_import_worker(self) -> None:
        if self.ocr_worker is not None:
            self.ocr_worker.deleteLater()
        if self.ocr_thread is not None:
            self.ocr_thread.deleteLater()
        self.ocr_worker = None
        self.ocr_thread = None

    def reject(self) -> None:
        if self.ocr_thread is not None and self.ocr_thread.isRunning():
            self.status_label.setText("Aguarde: a importação ainda está em andamento.")
            self.live_telemetry.setText("O processamento continua em segundo plano")
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.ocr_thread is not None and self.ocr_thread.isRunning():
            self.status_label.setText("Aguarde: a importação ainda está em andamento.")
            self.live_telemetry.setText("O processamento continua em segundo plano")
            event.ignore()
            return
        super().closeEvent(event)


# Compatibility name for integrations that imported the previous dialog.
ImportDialog = CustomImportPopup


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
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
