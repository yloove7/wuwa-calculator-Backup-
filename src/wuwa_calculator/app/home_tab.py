"""Home tab for Tethys."""

from __future__ import annotations

import builtins
import math
import os
import sys
from typing import TextIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import (
    QByteArray, QEasingCurve, QObject, QEvent, QPoint, QParallelAnimationGroup,
    QPropertyAnimation, QThread,
    QTimer, QRectF, Qt, Signal, Slot,
)
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPaintEvent, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.wuwa_calculator.app.components import Card, TitleLabel, WuWaKuroBannerCard
from src.wuwa_calculator.app.banners.banner_service import fetch_current_banner
from src.wuwa_calculator.app.pity_tracker import PityTrackerWidget
from src.wuwa_calculator.app.styles import apply_glow
from src.wuwa_calculator.storage.banner_cache import load_cached_banner, save_cached_banner


_print = builtins.print


def _debug_print(
    *args: object,
    sep: str | None = " ",
    end: str | None = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    if os.environ.get("TETHYS_DEBUG_BANNER") == "1":
        _print(*args, sep=sep, end=end, file=file, flush=flush)


print = _debug_print


def _rounded_banner_pixmap(source: QPixmap, width: int, height: int, radius: int = 12) -> QPixmap:
    scaled = source.scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    painter.setClipPath(path)
    x = (width - scaled.width()) // 2
    y = (height - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas


class CollapsibleTrackerDrawer(QFrame):
    """Horizontal drawer that keeps the tracker alive while collapsed."""

    EXPANDED_WIDTH = 360

    def __init__(self, tracker: PityTrackerWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("noticeBoardDrawer")
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(480)
        self._expanded = True

        tracker.setMinimumWidth(0)
        tracker.setFixedWidth(self.EXPANDED_WIDTH)
        tracker.setMinimumHeight(0)
        tracker.setMaximumHeight(16777215)
        tracker.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.tracker = tracker
        tracker.setParent(self)
        self.content_widget = tracker

        self.toggle_button = QPushButton("‹", self)
        self.toggle_button.setObjectName("conveneTrackerToggle")
        self.toggle_button.setFixedWidth(34)
        self.toggle_button.setToolTip("Avisos e Notícias")
        self.toggle_button.setAccessibleName("Avisos e Notícias")
        self.toggle_button.clicked.connect(self.toggle)
        self.toggle_button.hide()

        self._animation = QParallelAnimationGroup(self)
        self._width_animations: list[QPropertyAnimation] = []
        for property_name in (b"minimumWidth", b"maximumWidth"):
            width_animation = QPropertyAnimation(self, property_name, self._animation)
            width_animation.setDuration(250)
            width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._width_animations.append(width_animation)
            self._animation.addAnimation(width_animation)
        self._position_animation = QPropertyAnimation(
            self.content_widget, b"pos", self._animation
        )
        self._position_animation.setDuration(250)
        self._position_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.addAnimation(self._position_animation)
        self._animation.finished.connect(self._on_animation_finished)
        self._sync_tracker_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_tracker_geometry()

    def _sync_tracker_geometry(self) -> None:
        self.content_widget.setGeometry(
            self.content_widget.x(),
            0,
            self.EXPANDED_WIDTH,
            max(0, self.height()),
        )

    def _on_animation_started(self) -> None:
        scroll_area = getattr(self.tracker, "scroll_area", None)
        if scroll_area is not None:
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _on_animation_finished(self) -> None:
        scroll_area = getattr(self.tracker, "scroll_area", None)
        if scroll_area is not None:
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if self._expanded
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll_area.setVerticalScrollBarPolicy(policy)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._animation.stop()
        self._on_animation_started()
        start_width = self.width()
        end_width = self.EXPANDED_WIDTH if self._expanded else 0
        start_x = self.content_widget.pos().x()
        end_x = 0 if self._expanded else self.EXPANDED_WIDTH
        for width_animation in self._width_animations:
            width_animation.setStartValue(start_width)
            width_animation.setEndValue(end_width)
        self._position_animation.setStartValue(QPoint(start_x, 0))
        self._position_animation.setEndValue(QPoint(end_x, 0))
        self.toggle_button.setText("‹" if self._expanded else "›")
        self.toggle_button.setToolTip(
            "Retrair Avisos e Notícias" if self._expanded else "Expandir Avisos e Notícias"
        )
        self._animation.start()


def _full_banner_pixmap(
    source: QPixmap,
    width: int,
    height: int,
    radius: int = 16,
    vertical_offset: int = 0,
) -> QPixmap:
    scaled = source.scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#0C101E"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(0, 0, width, height).adjusted(2, 2, -2, -2),
        max(0, radius - 2),
        max(0, radius - 2),
    )
    painter.setClipPath(path)
    x = (width - scaled.width()) // 2
    centered_y = (height - scaled.height()) // 2
    y = min(0, centered_y + vertical_offset)
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas


def _apply_rounded_image_mask(widget: QWidget, radius: int = 16) -> None:
    mask = QPixmap(widget.size())
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(0, 0, widget.width(), widget.height()).adjusted(2, 2, -2, -2),
        max(0, radius - 2),
        max(0, radius - 2),
    )
    painter.fillPath(path, QColor(Qt.GlobalColor.white))
    painter.end()
    widget.setMask(mask.createMaskFromColor(
        QColor(Qt.GlobalColor.transparent),
        Qt.MaskMode.MaskInColor,
    ))


class BannerWorker(QObject):
    finished = Signal(object)
    completed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            if self._cancelled:
                return
            print("[BannerWorker] Iniciando trabalho...")
            result = fetch_current_banner()
            if self._cancelled:
                return
            if isinstance(result, dict):
                save_cached_banner(result)
            print(f"[BannerWorker] Resultado: {type(result)} - {result if not isinstance(result, dict) else 'dict com dados'}")
            self.finished.emit(result)
        finally:
            self.completed.emit()


class CatalogWorker(QObject):
    finished = Signal(object)
    completed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            if self._cancelled:
                return
            from src.wuwa_calculator.app.banners.wuwa_tracker_adapter import fetch_banner_catalog
            records = fetch_banner_catalog()
            if not self._cancelled:
                self.finished.emit(records)
        finally:
            self.completed.emit()


class UpcomingBannerCard(QFrame):
    def __init__(self, record: dict[str, object], state: str,
                 compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("upcomingBannerPastCard" if compact else "upcomingBannerCard")
        self.setFixedSize(320, 128)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setProperty("hovered", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _apply_rounded_image_mask(self, radius=16)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 125))
        self.setGraphicsEffect(shadow)

        image = QLabel(self)
        image.setObjectName("upcomingBannerImage")
        image_margin = 2
        image.setGeometry(
            image_margin,
            image_margin,
            self.width() - image_margin * 2,
            self.height() - image_margin * 2,
        )
        image.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        image.setScaledContents(False)
        image_bytes = record.get("image_bytes", b"")
        pixmap = QPixmap()
        if isinstance(image_bytes, bytes):
            pixmap.loadFromData(QByteArray(image_bytes))
        if not pixmap.isNull():
            image.setPixmap(_full_banner_pixmap(
                pixmap,
                image.width(),
                image.height(),
                radius=14,
                vertical_offset=14,
            ))
        else:
            image.setText("Esperando anúncio oficial")
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)

        overlay = QFrame(self)
        overlay.setObjectName("upcomingBannerOverlay")
        overlay_width = 180
        overlay.setGeometry(10, self.height() - 50, overlay_width, 40)
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(7, 3, 7, 3)
        overlay_layout.setSpacing(0)

        name = QLabel(str(record.get("name", "Aguardando anúncio oficial")), overlay)
        name.setObjectName("upcomingBannerName")
        overlay_layout.addWidget(name)

        rarity = record.get("rarity", 5)
        try:
            rarity_value = int(rarity) if isinstance(rarity, (str, int, float)) and not isinstance(rarity, bool) else 5
        except (TypeError, ValueError, OverflowError):
            rarity_value = 5
        details = QLabel(
            f"Raridade: ★{rarity_value}\n"
            f"{record.get('date_label', 'Data: Próximo banner')}"
        , overlay)
        details.setObjectName("upcomingBannerDetails")
        overlay_layout.addWidget(details)
        image.lower()
        overlay.raise_()
        self.hologram_overlay = QLabel(self)
        self.hologram_overlay.setFixedSize(self.size())
        self.hologram_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hologram_overlay.setStyleSheet("background: transparent;")
        self.hologram_phase = 0.0
        self._apply_hologram_mask()
        self._update_hologram()
        self.hologram_timer = QTimer(self)
        self.hologram_timer.timeout.connect(self._update_hologram)
        self.hologram_timer.start(50)
        self.hologram_overlay.raise_()

        self.hover_frame = QFrame(self)
        self.hover_frame.setGeometry(0, 0, self.width(), self.height())
        self.hover_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hover_frame.setStyleSheet(
            "QFrame { background: transparent; border: 3px solid #00F5FF; "
            "border-radius: 16px; }"
        )
        self.hover_frame.hide()
        self.hover_frame.raise_()
        image.installEventFilter(self)
        overlay.installEventFilter(self)

    def _apply_hologram_mask(self) -> None:
        if self.width() <= 0 or self.height() <= 0 or not self.hologram_overlay:
            return
        mask = QPixmap(self.size())
        mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(mask)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 16, 16)
        painter.fillPath(path, Qt.GlobalColor.white)
        painter.end()
        self.hologram_overlay.setMask(
            mask.createMaskFromColor(
                QColor(Qt.GlobalColor.transparent),
                Qt.MaskMode.MaskInColor,
            )
        )

    def _update_hologram(self) -> None:
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0 or not self.hologram_overlay:
            return
        overlay = QPixmap(width, height)
        overlay.fill(Qt.GlobalColor.transparent)
        painter = QPainter(overlay)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), 16, 16)
        painter.setClipPath(path)

        shift = -320.0 + (720.0 * self.hologram_phase)
        prism = QLinearGradient(-80 + shift, 0, 90 + shift, height)
        prism.setColorAt(0.18, QColor(255, 70, 120, 0))
        prism.setColorAt(0.36, QColor(255, 70, 120, 38))
        prism.setColorAt(0.46, QColor(255, 220, 80, 42))
        prism.setColorAt(0.54, QColor(75, 240, 210, 38))
        prism.setColorAt(0.63, QColor(90, 150, 255, 45))
        prism.setColorAt(0.73, QColor(210, 95, 255, 38))
        prism.setColorAt(0.84, QColor(255, 70, 180, 0))
        painter.fillRect(0, 0, width, height, prism)

        highlight = QLinearGradient(-35 + shift, 0, 45 + shift, height)
        highlight.setColorAt(0.40, QColor(255, 255, 255, 0))
        highlight.setColorAt(0.50, QColor(255, 255, 255, 55))
        highlight.setColorAt(0.60, QColor(255, 255, 255, 0))
        painter.fillRect(0, 0, width, height, highlight)

        border = QLinearGradient(0, 0, width, height)
        border.setColorAt(0.00, QColor(70, 235, 255, 190))
        border.setColorAt(0.35, QColor(190, 110, 255, 150))
        border.setColorAt(0.60, QColor(255, 220, 100, 180))
        border.setColorAt(1.00, QColor(255, 70, 180, 170))
        painter.setPen(QPen(QBrush(border), 2.0))
        painter.drawPath(path)

        for index, (x_ratio, y_ratio) in enumerate(
            ((0.10, 0.16), (0.30, 0.88), (0.52, 0.12), (0.73, 0.84), (0.91, 0.28))
        ):
            x = x_ratio * width + math.sin(
                self.hologram_phase * 6.283 + index) * 2
            y = y_ratio * height + math.cos(
                self.hologram_phase * 6.283 + index) * 2
            glow = QRadialGradient(x, y, 10)
            glow.setColorAt(0.0, QColor(255, 255, 255, 180))
            glow.setColorAt(0.35, QColor(100, 220, 255, 80))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QRectF(x - 10, y - 10, 20, 20))

        painter.end()
        self.hologram_overlay.setPixmap(overlay)
        self.hologram_phase = (self.hologram_phase + 0.012) % 1.0

    def _set_hovered(self, hovered: bool) -> None:
        self.hover_frame.setVisible(hovered)
        self.setProperty("hovered", hovered)
        self.style().unpolish(self)
        self.style().polish(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Enter:
            self._set_hovered(True)
        elif event.type() == QEvent.Type.Leave:
            self._set_hovered(False)
        return super().eventFilter(watched, event)

    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)


class UpcomingBannersSection(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("upcomingBannersSection")
        self.setFixedHeight(182)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(3)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Banners Anteriores e Futuros")
        title.setObjectName("upcomingBannersTitle")
        heading.addWidget(title)
        subtitle = QLabel("Confira o banner anterior e os próximos banners.")
        subtitle.setObjectName("upcomingBannersSubtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch(1)
        for symbol in ("<", ">"):
            arrow = QPushButton(symbol)
            arrow.setObjectName("bannerTimelineArrow")
            arrow.setFixedSize(28, 28)
            header.addWidget(arrow)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(20)
        self.past_layout = QHBoxLayout()
        self.past_layout.setSpacing(10)
        body.addLayout(self.past_layout, 1)
        first_separator = QFrame()
        first_separator.setObjectName("bannerTimelineSeparator")
        first_separator.setFrameShape(QFrame.Shape.VLine)
        first_separator.setFrameShadow(QFrame.Shadow.Plain)
        first_separator.setStyleSheet("color: rgba(210, 225, 245, 85);")
        body.addWidget(first_separator)
        self.current_layout = QHBoxLayout()
        self.current_layout.setSpacing(10)
        body.addLayout(self.current_layout, 1)
        second_separator = QFrame()
        second_separator.setObjectName("bannerTimelineSeparator")
        second_separator.setFrameShape(QFrame.Shape.VLine)
        second_separator.setFrameShadow(QFrame.Shadow.Plain)
        second_separator.setStyleSheet("color: rgba(210, 225, 245, 85);")
        body.addWidget(second_separator)
        self.future_layout = QHBoxLayout()
        self.future_layout.setSpacing(10)
        body.addLayout(self.future_layout, 1)
        body.setStretchFactor(self.past_layout, 1)
        body.setStretchFactor(self.current_layout, 1)
        body.setStretchFactor(self.future_layout, 1)
        root.addLayout(body, 1)
        self.set_cards([], loading=True)

    def set_cards(self, records: list[dict[str, object]], loading: bool = False) -> None:
        for layout in (self.past_layout, self.current_layout, self.future_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        columns = (
            (self.past_layout, "past", "BANNER PASSADO"),
            (self.current_layout, "current", "PRÓXIMOS CONFIRMADOS"),
            (self.future_layout, "future", "PRÓXIMOS CONFIRMADOS"),
        )
        for layout, kind, title in columns:
            record = next((item for item in records if item.get("kind") == kind), None)
            if record is not None:
                card = UpcomingBannerCard(record, title, compact=True)
                card.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
                layout.addWidget(card, 1)
            else:
                placeholder = QLabel(title + "\nSem dados importados.")
                placeholder.setObjectName("bannerTimelineEmpty")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
                layout.addWidget(placeholder)


class HomeTab(QWidget):
    shutdown_finished = Signal()

    def __init__(self, preloaded_banner: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shutdown_requested = False
        self._shutdown_completion_emitted = False
        self._startup_work_scheduled = False
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        intro = Card()
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(20, 18, 20, 18)
        intro_heading = QHBoxLayout()
        intro_heading.setSpacing(10)
        intro_heading.addWidget(TitleLabel("Tethys"))
        intro_heading.addStretch(1)
        self.convene_tracker_button = QPushButton("▣  Avisos e Notícias")
        self.convene_tracker_button.setObjectName("conveneTrackerHeaderButton")
        self.convene_tracker_button.setToolTip("Mostrar ou ocultar Avisos e Notícias")
        self.convene_tracker_button.clicked.connect(self._toggle_convene_tracker)
        intro_heading.addWidget(self.convene_tracker_button)
        intro_layout.addLayout(intro_heading)
        subtitle = QLabel("Motor de dano local para testar rotações, equipes e execução prática.")
        subtitle.setObjectName("muted")
        intro_layout.addWidget(subtitle)
        root.addWidget(intro)

        cached_banner = load_cached_banner() if preloaded_banner is None else None
        initial_banner = preloaded_banner or cached_banner
        self.banner_data: dict[str, object] | None = initial_banner
        self.banner_thread: QThread | None = None
        self.banner_worker: BannerWorker | None = None
        self.catalog_thread: QThread | None = None
        self.catalog_worker: CatalogWorker | None = None
        self._catalog_snapshot_source: tuple[dict[str, object], ...] = ()
        self.banner_card: WuWaKuroBannerCard | None = None
        
        page_layout = QHBoxLayout()
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)
        left_column = QWidget()
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(8)

        hero_surface = QWidget()
        hero_surface.setObjectName("homeHeroSurface")
        hero_surface_layout = QHBoxLayout(hero_surface)
        hero_surface_layout.setContentsMargins(0, 0, 0, 0)
        hero_surface_layout.setSpacing(0)
        banner_column = QWidget()
        banner_column_layout = QVBoxLayout(banner_column)
        banner_column_layout.setContentsMargins(0, 0, 0, 0)
        banner_column.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        # Container temporário para o banner enquanto carrega
        self.banner_placeholder = QFrame()
        self.banner_placeholder.setMinimumWidth(0)
        self.banner_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.banner_placeholder.setFixedHeight(480)
        placeholder_layout = QVBoxLayout(self.banner_placeholder)
        placeholder_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_label = QLabel("Carregando banner...")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setObjectName("muted")
        placeholder_layout.addWidget(placeholder_label)
        self.banner_container = banner_column_layout
        active_name = str(initial_banner.get("name", "qingxiao")) if initial_banner else "qingxiao"
        self.pity_tracker = PityTrackerWidget(
            active_character=active_name,
            banner_images={
                "resonator": initial_banner.get("image_bytes", b"")
                if initial_banner else b""
            },
            defer_news_load=True,
            defer_hero_images=True,
        )
        self.convene_tracker_drawer = CollapsibleTrackerDrawer(self.pity_tracker)
        hero_surface_layout.addWidget(banner_column, 1)
        left_column_layout.addWidget(hero_surface)
        left_column.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        page_layout.addWidget(left_column, 1)
        page_layout.addWidget(self.convene_tracker_drawer, 0)
        self.main_layout = page_layout
        self.convene_tracker_drawer._position_animation.valueChanged.connect(
            lambda _value: self.main_layout.activate()
        )
        
        # Se já tem banner pré-carregado, mostra imediatamente
        if initial_banner:
            print("[HomeTab] Banner pré-carregado recebido, criando card imediatamente...")
            self._banner_loaded(initial_banner)
        else:
            # Caso contrário, mostra placeholder e carrega em background
            self.banner_container.addWidget(self.banner_placeholder)

        self.timeline_panel = UpcomingBannersSection()
        self.timeline_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        left_column_layout.addWidget(self.timeline_panel)
        root.addLayout(page_layout, 1)
        root.addStretch(1)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._startup_work_scheduled:
            return
        self._startup_work_scheduled = True
        QTimer.singleShot(0, self._start_secondary_home_work)

    def _start_secondary_home_work(self) -> None:
        if self._shutdown_requested:
            return
        self.pity_tracker.start_hero_image_load()
        self._start_banner_refresh()
        self._start_catalog_refresh()
        self.pity_tracker.start_news_load(self._check_shutdown_complete)

    def _toggle_convene_tracker(self) -> None:
        drawer = getattr(self, "convene_tracker_drawer", None)
        if drawer is not None:
            drawer.toggle()

    def set_active(self, active: bool) -> None:
        if self.banner_card is not None:
            self.banner_card.set_active(active)

    def shutdown_workers(self, timeout_ms: int = 5000) -> bool:
        del timeout_ms  # Kept for compatibility with existing callers.
        self._shutdown_requested = True
        active_threads = False
        workers = (
            (self.banner_thread, self.banner_worker),
            (self.catalog_thread, self.catalog_worker),
            (self.pity_tracker.worker, None),
        )
        for thread, worker in workers:
            if thread is None:
                continue
            if thread.isRunning():
                active_threads = True
                if worker is not None:
                    worker.cancel()
                thread.requestInterruption()
                thread.quit()
        if active_threads:
            return False
        self._shutdown_completion_emitted = True
        self._clear_banner_worker()
        self._clear_catalog_worker()
        return True

    @Slot()
    def _check_shutdown_complete(self) -> None:
        if not self._shutdown_requested or self._shutdown_completion_emitted:
            return
        threads = (self.banner_thread, self.catalog_thread, self.pity_tracker.worker)
        if any(thread.isRunning() for thread in threads if thread is not None):
            return
        self._shutdown_completion_emitted = True
        self._clear_banner_worker()
        self._clear_catalog_worker()
        self.shutdown_finished.emit()

    def _start_catalog_refresh(self) -> None:
        if self._shutdown_requested:
            return
        self.catalog_thread = QThread(self)
        self.catalog_worker = CatalogWorker()
        self.catalog_worker.moveToThread(self.catalog_thread)
        self.catalog_thread.finished.connect(self.catalog_worker.deleteLater)
        self.catalog_thread.started.connect(self.catalog_worker.run)
        self.catalog_worker.finished.connect(self._catalog_loaded)
        self.catalog_worker.completed.connect(self.catalog_thread.quit)
        self.catalog_thread.finished.connect(self._clear_catalog_worker)
        self.catalog_thread.start()

    @staticmethod
    def _parse_catalog_date(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @Slot(object)
    def _catalog_loaded(self, data: object) -> None:
        records = data if isinstance(data, list) else []
        now = datetime.now(timezone.utc)
        future_limit = now + timedelta(days=14)
        visible: list[dict[str, object]] = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            starts_at = self._parse_catalog_date(raw.get("starts_at"))
            ends_at = self._parse_catalog_date(raw.get("ends_at"))
            if ends_at is None:
                continue
            if starts_at is not None and starts_at <= now <= ends_at:
                continue
            if ends_at < now:
                record = dict(raw)
                record["kind"] = "past"
                record["date_label"] = f"Data: {ends_at.strftime('%d/%m/%Y')}"
                visible.append(record)
            elif ends_at >= now and starts_at is not None and now < starts_at <= future_limit:
                if raw.get("speculated") or raw.get("isSpeculated"):
                    continue
                record = dict(raw)
                record["kind"] = "future"
                record["name"] = str(raw.get("name", "Personagem"))
                record["date_label"] = f"Data: {starts_at.strftime('%d/%m/%Y')}"
                visible.append(record)

        visible.sort(key=lambda item: str(item.get("ends_at", "")))
        self._catalog_snapshot_source = tuple(visible)
        self.timeline_panel.set_cards(visible)
    @Slot()
    def _clear_catalog_worker(self) -> None:
        if self.catalog_thread is not None:
            self.catalog_thread.deleteLater()
        self.catalog_worker = None
        self.catalog_thread = None
        self._check_shutdown_complete()

    def _start_banner_refresh(self) -> None:
        if self._shutdown_requested:
            return
        print("[HomeTab] Iniciando refresh de banner...")
        self.banner_thread = QThread(self)
        self.banner_worker = BannerWorker()
        self.banner_worker.moveToThread(self.banner_thread)
        self.banner_thread.finished.connect(self.banner_worker.deleteLater)
        self.banner_thread.started.connect(self.banner_worker.run)
        self.banner_worker.finished.connect(self._banner_loaded)
        self.banner_worker.completed.connect(self.banner_thread.quit)
        self.banner_thread.finished.connect(self._clear_banner_worker)
        self.banner_thread.start()
        print("[HomeTab] Thread de banner iniciada")

    @Slot(object)
    def _banner_loaded(self, data: object) -> None:
        print(f"[HomeTab] _banner_loaded chamado. data type: {type(data)}")
        
        if not isinstance(data, dict):
            print("[HomeTab] Banner data não é dict, mantendo placeholder")
            return
        
        self.banner_data = data
        character_name = str(data.get('name', 'Banner'))
        image_bytes = data.get('image_bytes', b'')
        ends_at_str = str(data.get('ends_at', ''))
        
        print(f"[HomeTab] character_name: {character_name}")
        print(f"[HomeTab] image_bytes length: {len(image_bytes) if isinstance(image_bytes, bytes) else 'NÃO É BYTES'}")
        print(f"[HomeTab] ends_at_str: {ends_at_str}")
        
        if not isinstance(image_bytes, bytes) or len(image_bytes) == 0:
            print("[HomeTab] image_bytes vazio, retornando")
            return
        
        try:
            ends_at = datetime.fromisoformat(ends_at_str)
            print(f"[HomeTab] ends_at parseado: {ends_at}")
        except (ValueError, TypeError) as e:
            print(f"[HomeTab] Erro ao parsear data: {e}")
            return

        starts_at = self._parse_catalog_date(data.get("starts_at"))
        if starts_at is None and character_name.casefold() == "jingran":
            starts_at = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)
        
        # Remove o placeholder e cria o novo banner card
        print("[HomeTab] Removendo placeholder...")
        if self.banner_placeholder and self.banner_placeholder.parent():
            self.banner_container.removeWidget(self.banner_placeholder)
            self.banner_placeholder.deleteLater()
            self.banner_placeholder = None

        if self.banner_card is not None:
            self.banner_container.removeWidget(self.banner_card)
            self.banner_card.deleteLater()
            self.banner_card = None
        
        print("[HomeTab] Criando WuWaKuroBannerCard...")
        self.banner_card = WuWaKuroBannerCard(
            character_name=character_name,
            image_bytes=image_bytes,
            end_date=ends_at,
            banner_start=starts_at,
            element=str(data.get("element", "")) or None,
        )
        self.banner_container.addWidget(self.banner_card)
        print("[HomeTab] Banner card criado e inserido no layout")

    @Slot()
    def _clear_banner_worker(self) -> None:
        print("[HomeTab] Limpando banner worker...")
        if self.banner_thread is not None:
            self.banner_thread.deleteLater()
        self.banner_worker = None
        self.banner_thread = None
        print("[HomeTab] Banner worker limpo")
        self._check_shutdown_complete()
