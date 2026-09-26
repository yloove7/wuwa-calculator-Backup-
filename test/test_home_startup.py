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

    def start_hero_image_load(self) -> None:
        self.started = True

    def start_news_load(self, finished_callback=None) -> None:
        self.started = True


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
