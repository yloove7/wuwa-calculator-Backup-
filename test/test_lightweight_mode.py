from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QParallelAnimationGroup
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from src.wuwa_calculator.app.multimedia.multimedia_tab import (
    _FrequencyMaintenanceOverlay,
)
from src.wuwa_calculator.app.pity_tracker import PityTrackerWidget


_APPLICATION = QApplication.instance() or QApplication([])


def test_light_mode_pauses_decorative_carousel_but_keeps_event_timer() -> None:
    tracker = PityTrackerWidget(defer_news_load=True, defer_hero_images=True)
    slide_timer = tracker.slide_timer
    event_timer = tracker.event_timer
    assert slide_timer.isActive()
    assert event_timer.isActive()

    tracker.hero_image.setPixmap(QPixmap(32, 24))
    tracker.hero_next_image.setPixmap(QPixmap(32, 24))
    tracker.hero_index = 1
    tracker.hero_image.move(18, 0)
    tracker.hero_next_image.move(-18, 0)
    tracker.hero_next_image.show()
    tracker._slide_group = QParallelAnimationGroup(tracker)

    tracker.set_performance_mode(True)
    assert not slide_timer.isActive()
    assert event_timer.isActive()
    assert tracker._slide_group is None
    assert tracker.hero_image.pos() == QPoint(0, 0)
    assert tracker.hero_next_image.isHidden()
    incoming_pixmap = tracker.hero_next_image.pixmap()
    assert incoming_pixmap is None or incoming_pixmap.isNull()

    tracker.set_active(False)
    assert not slide_timer.isActive()
    assert not event_timer.isActive()
    tracker.set_active(True)
    assert not slide_timer.isActive()
    assert event_timer.isActive()

    tracker.set_performance_mode(False)
    assert slide_timer.isActive()
    assert event_timer.isActive()
    assert tracker.slide_timer is slide_timer
    assert tracker.event_timer is event_timer
    tracker.deleteLater()


def test_frequency_overlay_covers_content_and_consumes_mouse_input() -> None:
    parent = QWidget()
    parent.resize(640, 420)
    underlying = QPushButton("underlying control", parent)
    underlying.setGeometry(220, 175, 200, 48)
    clicks: list[bool] = []
    underlying.clicked.connect(lambda: clicks.append(True))
    overlay = _FrequencyMaintenanceOverlay(parent)
    overlay.setGeometry(parent.rect())
    parent.show()
    overlay.show()
    overlay.raise_()
    _APPLICATION.processEvents()

    assert underlying.isVisible()
    assert overlay.isVisible()
    assert overlay.geometry() == parent.rect()
    message_text = [label.text() for label in overlay.findChildren(QLabel)]
    assert "EM MANUTENÇÃO" in message_text
    assert "TBA" in message_text

    mouse_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(320, 200),
        QPointF(parent.mapToGlobal(QPoint(320, 200))),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert QApplication.sendEvent(overlay, mouse_event)
    assert mouse_event.isAccepted()
    assert clicks == []
    overlay.hide()
    assert underlying.isVisible()
    parent.deleteLater()
