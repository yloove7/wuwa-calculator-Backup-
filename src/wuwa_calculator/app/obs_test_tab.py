"""OBS-style settings surface for the existing WGC capture pipeline."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.wuwa_calculator.app.capture.settings import (
    CaptureRate,
    CaptureSettings,
    ColorSpace,
    WindowMatchPriority,
)
from src.wuwa_calculator.app.components import Card, TitleLabel


class ObsTestTab(QWidget):
    settingsChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = CaptureSettings()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = TitleLabel("OBS Teste")
        layout.addWidget(title)
        intro = QLabel(
            "Configurações pós-captura para o adaptador WGC. "
            "O núcleo de captura existente permanece intacto."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        video_card = Card()
        video_layout = QVBoxLayout(video_card)
        video_layout.addWidget(QLabel("Vídeo e processamento"))
        form = QFormLayout()

        self.capture_cursor = QCheckBox("Capturar cursor")
        self.capture_cursor.setChecked(self.settings.capture_cursor)
        form.addRow(self.capture_cursor)

        self.allow_transparency = QCheckBox("Preservar transparência")
        form.addRow(self.allow_transparency)
        self.premultiplied_alpha = QCheckBox("Alpha premultiplicado")
        self.premultiplied_alpha.setEnabled(False)
        self.premultiplied_alpha.setToolTip("Disponível quando a transparência estiver ativa")
        form.addRow(self.premultiplied_alpha)
        self.allow_transparency.toggled.connect(self.premultiplied_alpha.setEnabled)

        self.limit_framerate = QCheckBox("Limitar FPS processado")
        form.addRow(self.limit_framerate)
        fps_row = QHBoxLayout()
        self.max_framerate = QSpinBox()
        self.max_framerate.setRange(1, 240)
        self.max_framerate.setValue(self.settings.max_framerate)
        self.max_framerate.setSuffix(" FPS")
        fps_row.addWidget(self.max_framerate)
        fps_row.addStretch(1)
        form.addRow("Máximo", fps_row)
        self.limit_framerate.toggled.connect(self.max_framerate.setEnabled)
        self.max_framerate.setEnabled(False)

        self.capture_rate = QComboBox()
        self.capture_rate.addItems([rate.value for rate in CaptureRate])
        self.capture_rate.setCurrentText(self.settings.capture_rate.value)
        form.addRow("Taxa de processamento", self.capture_rate)

        self.color_space = QComboBox()
        self.color_space.addItems([space.value for space in ColorSpace])
        form.addRow("Espaço de cor", self.color_space)
        video_layout.addLayout(form)
        layout.addWidget(video_card)

        target_card = Card()
        target_layout = QFormLayout(target_card)
        target_layout.addRow(QLabel("Janela alvo"))
        self.window_priority = QComboBox()
        self.window_priority.addItems([priority.value for priority in WindowMatchPriority])
        target_layout.addRow("Prioridade", self.window_priority)
        layout.addWidget(target_card)

        backend_card = Card()
        backend_layout = QFormLayout(backend_card)
        self.capture_audio = QCheckBox("Capturar áudio")
        self.capture_audio.setEnabled(False)
        self.capture_audio.setToolTip("Requer um backend de áudio separado")
        backend_layout.addRow(self.capture_audio)
        self.capture_overlays = QCheckBox("Capturar overlays")
        self.capture_overlays.setEnabled(False)
        self.capture_overlays.setToolTip("Requer Game Capture/Hook; não é simulado pelo WGC")
        backend_layout.addRow(self.capture_overlays)
        self.anti_cheat = QCheckBox("Compatibilidade anti-cheat")
        self.anti_cheat.setEnabled(False)
        self.anti_cheat.setToolTip("Requer Game Capture/Hook; não é simulado pelo WGC")
        backend_layout.addRow(self.anti_cheat)
        layout.addWidget(backend_card)

        actions = QHBoxLayout()
        apply_button = QPushButton("Aplicar configurações")
        apply_button.setObjectName("primaryAction")
        apply_button.clicked.connect(self._emit_settings)
        actions.addWidget(apply_button)
        self.status = QLabel("Pronto")
        self.status.setObjectName("muted")
        actions.addWidget(self.status)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

    def current_settings(self) -> CaptureSettings:
        return CaptureSettings(
            capture_cursor=self.capture_cursor.isChecked(),
            allow_transparency=self.allow_transparency.isChecked(),
            premultiplied_alpha=self.premultiplied_alpha.isChecked(),
            limit_framerate=self.limit_framerate.isChecked(),
            max_framerate=self.max_framerate.value(),
            capture_rate=CaptureRate(self.capture_rate.currentText()),
            color_space=ColorSpace(self.color_space.currentText()),
            window_match_priority=WindowMatchPriority(self.window_priority.currentText()),
        )

    def _emit_settings(self) -> None:
        self.settings = self.current_settings()
        self.settingsChanged.emit(self.settings)
        self.status.setText("Configurações aplicadas ao próximo ciclo de captura")
