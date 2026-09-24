"""Adaptive visual widgets used by the image import dialog."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QWidget

from src.wuwa_calculator.app.styles import ThemeConfig


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
                round(center.x() - radius * 0.42),
                round(center.y() - radius * 0.42),
                round(center.x() + radius * 0.42),
                round(center.y() + radius * 0.42),
            )
            painter.drawLine(
                round(center.x() + radius * 0.42),
                round(center.y() - radius * 0.42),
                round(center.x() - radius * 0.42),
                round(center.y() + radius * 0.42),
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
