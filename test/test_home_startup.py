from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QApplication, QWidget

from src.wuwa_calculator.app import home_tab
from src.wuwa_calculator.app.pity_tracker import (
    EVENT_RESONATOR_BANNER_URL,
    SIGNATURE_WEAPON_BANNER_URL,
    NoticeManager,
    NewsFetcherWorker,
    PityTrackerWidget,
)

_APPLICATION = QApplication.instance() or QApplication([])


class _Reply(QObject):
    finished = Signal()


class _TrackerStub(QWidget):
    worker = None

    def __init__(self, **kwargs: object) -> None:
        super().__init__()
        self.defer_news_load = kwargs.get("defer_news_load")
        self.defer_hero_images = kwargs.get("defer_hero_images")
        self.started = False
        self.performance_modes: list[bool] = []
        self.active_states: list[bool] = []

    def start_hero_image_load(self) -> None:
        self.started = True

    def start_news_load(self, finished_callback=None) -> None:
        self.started = True

    def set_performance_mode(self, enabled: bool) -> None:
        self.performance_modes.append(enabled)

    def set_active(self, active: bool) -> None:
        self.active_states.append(active)


def test_home_secondary_workers_start_after_first_paint(
    monkeypatch,
) -> None:
    scheduled: list[object] = []
    started: list[str] = []
    trackers: list[_TrackerStub] = []

    def make_tracker(**kwargs: object) -> _TrackerStub:
        tracker = _TrackerStub(**kwargs)
        trackers.append(tracker)
        return tracker

    monkeypatch.setattr(home_tab, "PityTrackerWidget", make_tracker)
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)
    monkeypatch.setattr(
        QTimer,
        "singleShot",
        lambda interval, callback: scheduled.append(callback),
    )
    monkeypatch.setattr(
        home_tab.HomeTab,
        "_start_banner_refresh",
        lambda self: started.append("banner"),
    )
    monkeypatch.setattr(
        home_tab.HomeTab,
        "_start_catalog_refresh",
        lambda self: started.append("catalog"),
    )

    home = home_tab.HomeTab()

    assert trackers[0].defer_news_load is True
    assert trackers[0].defer_hero_images is True
    assert started == []
    assert scheduled == []

    home.paintEvent(QPaintEvent(QRect(0, 0, 100, 100)))

    assert started == []
    assert len(scheduled) == 1
    callback = scheduled[0]
    assert callable(callback)
    callback()

    assert started == ["banner", "catalog"]
    assert trackers[0].started is True
    home.paintEvent(QPaintEvent(QRect(0, 0, 100, 100)))
    assert len(scheduled) == 1
    home.deleteLater()


def test_fast_startup_defers_secondary_home_work_without_changing_light_mode(
    monkeypatch,
) -> None:
    scheduled: list[tuple[int, object]] = []
    monkeypatch.setattr(home_tab, "PityTrackerWidget", _TrackerStub)
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)
    monkeypatch.setattr(
        QTimer,
        "singleShot",
        lambda interval, callback: scheduled.append((interval, callback)),
    )
    home = home_tab.HomeTab()

    home.set_fast_startup_mode(True)
    home.paintEvent(QPaintEvent(QRect(0, 0, 100, 100)))

    assert scheduled == [(1200, home._start_secondary_home_work)]
    assert home._performance_mode is False
    home.deleteLater()


def test_hero_reuses_inflight_requests_when_fallback_notices_arrive(
    monkeypatch,
) -> None:
    requested_urls: list[str] = []

    def record_get(manager, request):
        requested_urls.append(request.url().toString())
        return _Reply(manager)

    monkeypatch.setattr(QNetworkAccessManager, "get", record_get)
    widget = PityTrackerWidget(
        defer_news_load=True,
        defer_hero_images=True,
    )
    initial_requests = list(requested_urls)

    assert initial_requests == []
    widget.start_hero_image_load()
    initial_requests = list(requested_urls)

    widget._set_notices(NoticeManager().fallback())

    assert initial_requests == [
        EVENT_RESONATOR_BANNER_URL,
        SIGNATURE_WEAPON_BANNER_URL,
    ]
    assert requested_urls == initial_requests
    widget.deleteLater()


def test_news_load_can_be_started_once_after_home_paint(monkeypatch) -> None:
    starts: list[NewsFetcherWorker] = []
    finished: list[bool] = []

    def start_worker(worker: NewsFetcherWorker) -> None:
        starts.append(worker)
        worker.finished.emit()

    monkeypatch.setattr(NewsFetcherWorker, "start", start_worker)
    monkeypatch.setattr(QNetworkAccessManager, "get", lambda manager, request: _Reply(manager))
    widget = PityTrackerWidget(defer_news_load=True)

    assert widget.worker is None
    widget.start_news_load(lambda: finished.append(True))
    widget.start_news_load()

    assert widget.worker is starts[0]
    assert len(starts) == 1
    assert finished == [True]
    widget.deleteLater()


def test_timeline_holograms_pause_resume_without_recreating_timers() -> None:
    section = home_tab.UpcomingBannersSection()
    section.set_cards([
        {"kind": "past", "name": "Anterior", "image_bytes": b""},
        {"kind": "future", "name": "Próximo", "image_bytes": b""},
    ])
    cards = section.findChildren(home_tab.UpcomingBannerCard)
    timers = [card.hologram_timer for card in cards]

    assert len(cards) == 2
    assert all(not timer.isActive() for timer in timers)

    section.set_active(True)
    assert all(timer.isActive() for timer in timers)
    for card in cards:
        card.hologram_phase = 0.61
    section.set_performance_mode(True)
    assert all(not timer.isActive() for timer in timers)
    assert all(card.hologram_phase == 0.0 for card in cards)
    assert all(card.hologram_overlay.isHidden() for card in cards)
    assert all(
        card.hologram_overlay.pixmap() is None
        or card.hologram_overlay.pixmap().isNull()
        for card in cards
    )
    section.set_performance_mode(False)
    assert all(timer.isActive() for timer in timers)
    assert all(not card.hologram_overlay.isHidden() for card in cards)
    section.set_active(False)
    assert all(not timer.isActive() for timer in timers)

    section.set_active(True)
    assert all(timer.isActive() for timer in timers)
    assert timers == [card.hologram_timer for card in cards]
    section.deleteLater()


def test_home_animation_activity_requires_active_tab_and_unminimized_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)
    trackers: list[_TrackerStub] = []

    def make_tracker(**kwargs: object) -> _TrackerStub:
        tracker = _TrackerStub(**kwargs)
        trackers.append(tracker)
        return tracker

    monkeypatch.setattr(home_tab, "PityTrackerWidget", make_tracker)
    home = home_tab.HomeTab()
    home.timeline_panel.set_cards([
        {"kind": "past", "name": "Anterior", "image_bytes": b""},
    ])
    card = home.timeline_panel.findChild(home_tab.UpcomingBannerCard)
    assert card is not None
    timer = card.hologram_timer
    assert not timer.isActive()

    home.set_active(True)
    assert timer.isActive()
    home.set_window_visible(False)
    assert not timer.isActive()
    home.set_active(False)
    home.set_window_visible(True)
    assert not timer.isActive()
    home.set_active(True)
    assert timer.isActive()
    home.deleteLater()


def test_home_performance_mode_pauses_decorative_timers_only(
    monkeypatch,
) -> None:
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)
    trackers: list[_TrackerStub] = []

    def make_tracker(**kwargs: object) -> _TrackerStub:
        tracker = _TrackerStub(**kwargs)
        trackers.append(tracker)
        return tracker

    monkeypatch.setattr(home_tab, "PityTrackerWidget", make_tracker)
    home = home_tab.HomeTab()
    home.timeline_panel.set_cards([
        {"kind": "future", "name": "Próximo", "image_bytes": b""},
    ])
    card = home.timeline_panel.findChild(home_tab.UpcomingBannerCard)
    assert card is not None
    home.set_active(True)
    assert card.hologram_timer.isActive()

    home.set_performance_mode(True)
    assert not card.hologram_timer.isActive()
    assert trackers[0].performance_modes == [False, True]

    home.set_performance_mode(False)
    assert card.hologram_timer.isActive()
    assert trackers[0].performance_modes == [False, True, False]
    home.deleteLater()
