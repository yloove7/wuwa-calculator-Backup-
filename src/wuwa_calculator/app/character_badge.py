"""Shared character badge visual component."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class CharacterBadgeWidget(QWidget):
    """Badge circular de personagem com ícone de arma sobreposto."""

    def __init__(self, char_icon_path: str | None = None,
                 weapon_icon_path: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.char_pixmap = QPixmap(char_icon_path) if char_icon_path else QPixmap()
        self.weapon_pixmap = QPixmap(weapon_icon_path) if weapon_icon_path else QPixmap()
        self.setFixedSize(64, 64)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_pixmaps(self, char_pixmap: QPixmap | None = None,
                    weapon_pixmap: QPixmap | None = None) -> None:
        if char_pixmap is not None:
            self.char_pixmap = char_pixmap
        if weapon_pixmap is not None:
            self.weapon_pixmap = weapon_pixmap
        self.update()

    def set_icons(self, char_path: str | None, weapon_path: str | None) -> None:
        self.char_pixmap = QPixmap(char_path) if char_path else QPixmap()
        self.weapon_pixmap = QPixmap(weapon_path) if weapon_path else QPixmap()
        self.update()

    @staticmethod
    def _fit_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        avatar_rect = QRectF(2, 2, 56, 56)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(avatar_rect)

        if not self.char_pixmap.isNull():
            avatar_path = QPainterPath()
            avatar_path.addEllipse(avatar_rect)
            fitted_avatar = self._fit_pixmap(self.char_pixmap, 56)
            avatar_x = int(2 + (56 - fitted_avatar.width()) / 2)
            avatar_y = int(2 + (56 - fitted_avatar.height()) / 2)
            painter.save()
            painter.setClipPath(avatar_path)
            painter.drawPixmap(avatar_x, avatar_y, fitted_avatar)
            painter.restore()

        if not self.weapon_pixmap.isNull():
            weapon_rect = QRectF(37, 37, 22, 22)
            painter.setPen(QPen(QColor("#FFA500"), 2))
            painter.setBrush(QBrush(QColor("#1A1A1A")))
            painter.drawEllipse(weapon_rect)
            weapon_path = QPainterPath()
            weapon_path.addEllipse(weapon_rect)
            fitted_weapon = self._fit_pixmap(self.weapon_pixmap, 18)
            weapon_x = int(37 + (22 - fitted_weapon.width()) / 2)
            weapon_y = int(37 + (22 - fitted_weapon.height()) / 2)
            painter.save()
            painter.setClipPath(weapon_path)
            painter.drawPixmap(weapon_x, weapon_y, fitted_weapon)
            painter.restore()
