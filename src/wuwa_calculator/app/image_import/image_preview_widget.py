"""Image preview and scan-line presentation for the import dialog."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.wuwa_calculator.app.image_import.adaptive_widgets import AdaptiveDataGrid
from src.wuwa_calculator.app.styles import ThemeConfig


class ImagePreviewWidget(QWidget):
    def __init__(self, theme: ThemeConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._scanning = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scan_grid = AdaptiveDataGrid(theme)
        grid_layout = QVBoxLayout(self.scan_grid)
        grid_layout.setContentsMargins(18, 18, 18, 18)
        grid_layout.addStretch(1)
        self.grid_hint = QLabel(
            "Aguardando imagem\n\nArraste ou selecione uma screenshot de atributos"
        )
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

        layout.addWidget(self.scan_grid, 1)
        QTimer.singleShot(0, self._update_scan_line_geometry)
        self.set_theme(theme)

    def set_preview_image(self, image: QImage) -> None:
        self._source_pixmap = QPixmap.fromImage(image)
        if self._source_pixmap.isNull():
            return
        self.grid_hint.hide()
        self._refresh_source_preview()

    def set_scanning(self, active: bool) -> None:
        self._scanning = active
        self._update_scan_line_geometry()
        if active and self.scan_animation.state() != QAbstractAnimation.State.Running:
            self.scan_animation.start()
        elif not active:
            self.scan_animation.stop()

    def set_theme(self, theme: ThemeConfig) -> None:
        self.scan_grid.set_theme(theme)
        scan_effect = QGraphicsDropShadowEffect(self.scan_line)
        scan_effect.setBlurRadius(14)
        scan_effect.setOffset(0, 0)
        scan_effect.setColor(QColor(theme.primary_neon_color))
        self.scan_line.setGraphicsEffect(scan_effect)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_source_preview()
        self._update_scan_line_geometry()
        if (
            self._scanning
            and self.scan_animation.state() != QAbstractAnimation.State.Running
        ):
            self.scan_animation.start()
        elif not self._scanning:
            self.scan_animation.stop()

    def _refresh_source_preview(self) -> None:
        if self._source_pixmap.isNull() or self.image_preview.size().isEmpty():
            return
        self.image_preview.setPixmap(self._source_pixmap.scaled(
            self.image_preview.contentsRect().size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _update_scan_line_geometry(self) -> None:
        width = max(1, self.scan_grid.width() - 16)
        y = max(8, self.scan_grid.height() // 2)
        self.scan_line.setFixedWidth(width)
        self.scan_line.move(8, y)
        bottom_y = max(8, self.scan_grid.height() - 8)
        self.scan_animation.setStartValue(QPoint(8, 8))
        self.scan_animation.setKeyValueAt(0.5, QPoint(8, bottom_y))
        self.scan_animation.setEndValue(QPoint(8, 8))
