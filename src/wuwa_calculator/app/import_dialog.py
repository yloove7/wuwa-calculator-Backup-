"""Image import dialog for character build screenshots."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from src.wuwa_calculator.app.image_import.adaptive_widgets import AdaptiveStatusSpinner
from src.wuwa_calculator.app.image_import.echo_preview_data import format_echo_preview_data
from src.wuwa_calculator.app.image_import.image_import_worker import (
    ImageCharacterMismatchError, ImageImportResult, ImageImportWorker,
)
from src.wuwa_calculator.app.image_import.image_preview_widget import ImagePreviewWidget
from src.wuwa_calculator.app.characters.resonator_tab import ResonatorTab
from src.wuwa_calculator.app.settings_store import SettingsStore
from src.wuwa_calculator.app.styles import ThemeConfig, theme_config


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
        self.pending_echoes: list[dict[str, object]] = []
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

        self.image_preview_widget = ImagePreviewWidget(self._theme, scan_panel)
        self.select_button = QPushButton("↑  Selecionar imagem")
        self.select_button.setObjectName("ocrSelectButton")
        self.select_button.setFixedHeight(38)
        self.select_button.clicked.connect(self.select_image)
        scan_layout.addWidget(self.image_preview_widget, 1)
        scan_layout.addWidget(self.select_button)
        content.addWidget(scan_panel, 3)

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
        self.image_preview_widget.set_theme(theme)
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._wallpaper_label.setGeometry(self.rect())

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
            if item is None:
                continue
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
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.echo_preview_title.setVisible(bool(echoes))
        for index, echo in enumerate(echoes):
            name_text, details_text = format_echo_preview_data(echo)
            card = QFrame()
            card.setObjectName("ocrEchoCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(3)
            name = QLabel(name_text)
            name.setObjectName("ocrEchoName")
            name.setWordWrap(True)
            details = QLabel(details_text)
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
        self.image_preview_widget.set_scanning(
            self.ocr_thread is not None and self.ocr_thread.isRunning()
        )

        self.ocr_thread = QThread(self)
        self.ocr_worker = ImageImportWorker(path, self.character_tab.current_id)
        self.ocr_worker.moveToThread(self.ocr_thread)
        self.ocr_thread.finished.connect(self.ocr_worker.deleteLater)
        self.ocr_thread.started.connect(self.ocr_worker.run)
        self.ocr_worker.preview_ready.connect(self.image_preview_widget.set_preview_image)
        self.ocr_worker.status.connect(self._set_scan_status)
        self.ocr_worker.finished.connect(self._import_finished)
        self.ocr_worker.failed.connect(self._import_failed)
        self.ocr_worker.finished.connect(self.ocr_thread.quit)
        self.ocr_worker.failed.connect(self.ocr_thread.quit)
        self.ocr_thread.finished.connect(self._clear_import_worker)
        self.ocr_thread.start(QThread.Priority.LowPriority)
        self.image_preview_widget.set_scanning(True)

    def _import_finished(self, result: ImageImportResult) -> None:
        self.select_button.setEnabled(True)
        stats = result["stats"]
        if stats or self.pending_echoes:
            self.pending_stats = stats
            echoes = result["echoes"]
            self.pending_echoes = echoes
            self.status_texts["detected"].setText("Leitura concluída")
            self._set_status_phase("detected")
            self.status_label.setText("Confira os dados e confirme a importação.")
            self.protocol_label.setText("PRÉVIA PRONTA")
            echo_count = len(echoes)
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
        if isinstance(error, InterruptedError):
            self.image_preview_widget.set_scanning(False)
            self.status_label.setText("Leitura cancelada.")
            self.live_telemetry.setText("O processamento OCR foi encerrado.")
            self.protocol_label.setText("CANCELADO")
            self._set_status_phase("waiting")
            return
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
        self.image_preview_widget.set_scanning(False)
        self._set_status_phase("error")
        self.live_telemetry.setText("Falha na leitura da build card")
        self.status_texts["error"].setText("Erro de leitura")
        self.protocol_label.setText("ERRO DE LEITURA")
        self.status_label.setText(message)
        QMessageBox.critical(self, title, message)

    def _clear_import_worker(self) -> None:
        self.image_preview_widget.set_scanning(False)
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

    def shutdown_ocr(self, timeout_ms: int = 5000) -> bool:
        thread = self.ocr_thread
        worker = self.ocr_worker
        if thread is None or not thread.isRunning():
            return True
        if worker is not None:
            worker.cancel()
        thread.quit()
        if not thread.wait(timeout_ms):
            return False
        self._clear_import_worker()
        return True
