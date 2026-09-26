from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from threading import Event

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

from src.wuwa_calculator.app import home_tab


_APPLICATION = QApplication.instance() or QApplication([])


class _TrackerStub(QWidget):
    worker = None

    def __init__(self, **_kwargs: object) -> None:
        super().__init__()

    def start_hero_image_load(self) -> None:
        pass

    def start_news_load(self, _finished_callback=None) -> None:
        pass


def _run_worker(worker: home_tab.BannerWorker | home_tab.CatalogWorker) -> None:
    thread = QThread()
    loop = QEventLoop()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(thread.quit)
    thread.finished.connect(loop.quit)
    thread.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert not thread.isRunning(), "worker did not finish before the test timeout"
    _APPLICATION.processEvents()


def test_home_workers_run_in_their_threads_and_callbacks_run_in_gui(
    monkeypatch,
) -> None:
    gui_thread = _APPLICATION.thread()
    worker_threads: dict[str, QThread] = {}
    callback_threads: dict[str, QThread] = {}

    def record_banner_fetch() -> None:
        worker_threads["banner"] = QThread.currentThread()
        return None

    def record_catalog_fetch() -> list[object]:
        worker_threads["catalog"] = QThread.currentThread()
        return []

    monkeypatch.setattr(home_tab, "fetch_current_banner", record_banner_fetch)
    monkeypatch.setattr(home_tab, "save_cached_banner", lambda _result: None)
    monkeypatch.setattr(
        "src.wuwa_calculator.app.banners.wuwa_tracker_adapter.fetch_banner_catalog",
        record_catalog_fetch,
    )
    monkeypatch.setattr(home_tab, "PityTrackerWidget", _TrackerStub)
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)

    home = home_tab.HomeTab()
    original_print = home_tab.print

    def record_print(*args: object) -> None:
        if args and str(args[0]).startswith("[HomeTab] _banner_loaded chamado"):
            callback_threads["banner"] = QThread.currentThread()
        original_print(*args)

    monkeypatch.setattr(home_tab, "print", record_print)

    def record_cards(_records: list[dict[str, object]]) -> None:
        callback_threads["catalog"] = QThread.currentThread()

    monkeypatch.setattr(home.timeline_panel, "set_cards", record_cards)

    banner_worker = home_tab.BannerWorker()
    banner_worker.finished.connect(home._banner_loaded)
    _run_worker(banner_worker)

    catalog_worker = home_tab.CatalogWorker()
    catalog_worker.finished.connect(home._catalog_loaded)
    _run_worker(catalog_worker)

    assert worker_threads["banner"] == banner_worker.thread()
    assert worker_threads["banner"] != gui_thread
    assert worker_threads["catalog"] == catalog_worker.thread()
    assert worker_threads["catalog"] != gui_thread
    assert callback_threads == {"banner": gui_thread, "catalog": gui_thread}

    home.deleteLater()
    _APPLICATION.processEvents()


def test_home_heartbeat_and_close_event_continue_during_worker_fetches(
    monkeypatch,
) -> None:
    release_fetches = Event()

    def blocked_banner_fetch() -> None:
        release_fetches.wait(1.0)
        return None

    def blocked_catalog_fetch() -> list[object]:
        release_fetches.wait(1.0)
        return []

    class ClosingHomeTab(home_tab.HomeTab):
        heartbeat_count = 0
        closed_on_gui = False
        workers_active_at_close = False
        heartbeat_count_at_close = 0

        def closeEvent(self, event: QCloseEvent) -> None:
            self.closed_on_gui = QThread.currentThread() == _APPLICATION.thread()
            self.workers_active_at_close = any(
                thread is not None and thread.isRunning()
                for thread in (self.banner_thread, self.catalog_thread)
            )
            self.heartbeat_count_at_close = self.heartbeat_count
            super().closeEvent(event)

    monkeypatch.setattr(home_tab, "fetch_current_banner", blocked_banner_fetch)
    monkeypatch.setattr(home_tab, "save_cached_banner", lambda _result: None)
    monkeypatch.setattr(
        "src.wuwa_calculator.app.banners.wuwa_tracker_adapter.fetch_banner_catalog",
        blocked_catalog_fetch,
    )
    monkeypatch.setattr(home_tab, "PityTrackerWidget", _TrackerStub)
    monkeypatch.setattr(home_tab, "load_cached_banner", lambda: None)

    home = ClosingHomeTab()
    home._startup_work_scheduled = True
    home.show()
    assert home.isVisible()
    home._start_banner_refresh()
    home._start_catalog_refresh()
    assert home.banner_thread is not None
    assert home.catalog_thread is not None

    loop = QEventLoop()
    completed_threads: list[bool] = []

    def record_thread_finished() -> None:
        completed_threads.append(True)
        if len(completed_threads) == 2:
            loop.quit()

    home.banner_thread.finished.connect(record_thread_finished)
    home.catalog_thread.finished.connect(record_thread_finished)

    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: setattr(
        home, "heartbeat_count", home.heartbeat_count + 1
    ))
    heartbeat.start()
    QTimer.singleShot(30, home.close)
    QTimer.singleShot(3000, loop.quit)
    try:
        loop.exec()
    finally:
        release_fetches.set()
        heartbeat.stop()

    _APPLICATION.processEvents()
    assert home.closed_on_gui
    assert home.workers_active_at_close
    assert home.heartbeat_count_at_close > 0
    assert home.heartbeat_count >= 5
    assert len(completed_threads) == 2
    home.deleteLater()
    _APPLICATION.processEvents()
