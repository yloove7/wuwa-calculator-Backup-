from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from src.wuwa_calculator.app import pity_tracker
from src.wuwa_calculator.app.image_import import image_import_worker
from src.wuwa_calculator.app.multimedia.dps_simulation_panel import DpsSimulationPanel
from src.wuwa_calculator.app.home_tab import BannerWorker, CatalogWorker, HomeTab
from src.wuwa_calculator.app.image_import.image_import_worker import ImageImportWorker
from src.wuwa_calculator.app.import_dialog import CustomImportPopup
from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab
from src.wuwa_calculator.app.window import WuwaQtWindow


class _FakeReader:
    def setAutoTransform(self, _enabled: bool) -> None:
        pass

    def read(self):
        return SimpleNamespace(isNull=lambda: True)


class _FakeProcess:
    def __init__(self, output: str = "", *, timeout_forever: bool = False) -> None:
        self.output = output
        self.timeout_forever = timeout_forever
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.started = threading.Event()

    def communicate(self, timeout: float | None = None):
        self.started.set()
        if self.timeout_forever and not self.terminated and not self.killed:
            wait_seconds = min(timeout or 0.01, 0.02)
            time.sleep(wait_seconds)
            raise image_import_worker.subprocess.TimeoutExpired("ocr", wait_seconds)
        self.returncode = 0 if not self.killed else -9
        return self.output, ""

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout: float | None = None):
        if self.killed:
            self.returncode = -9
        elif self.returncode is None:
            self.returncode = -15
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _ocr_output() -> str:
    return "RESULT\t" + json.dumps(
        {"stats": {"crit_rate": 5.0}, "character_id": "jiyan", "echoes": []}
    )


def test_ocr_worker_normal_process_completion() -> None:
    process = _FakeProcess(_ocr_output())
    worker = ImageImportWorker("image.png", "jiyan")
    results: list[object] = []
    worker.finished.connect(results.append)
    with (
        patch.object(image_import_worker, "QImageReader", return_value=_FakeReader()),
        patch.object(image_import_worker.subprocess, "Popen", return_value=process),
    ):
        worker.run()
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, dict)
    assert result["stats"] == {"crit_rate": 5.0}
    assert process.returncode == 0


def test_ocr_worker_timeout_terminates_process() -> None:
    process = _FakeProcess(timeout_forever=True)
    worker = ImageImportWorker("image.png", "jiyan")
    worker.PROCESS_TIMEOUT_SECONDS = 0.01
    failures: list[object] = []
    worker.failed.connect(failures.append)
    with (
        patch.object(image_import_worker, "QImageReader", return_value=_FakeReader()),
        patch.object(image_import_worker.subprocess, "Popen", return_value=process),
    ):
        worker.run()
    assert failures
    assert process.terminated
    assert process.returncode is not None


def test_ocr_worker_cancel_before_spawn_still_reports_completion_path() -> None:
    worker = ImageImportWorker("image.png", "jiyan")
    worker.cancel()
    failures: list[object] = []
    worker.failed.connect(failures.append)
    with (
        patch.object(image_import_worker, "QImageReader", return_value=_FakeReader()),
        patch.object(image_import_worker.subprocess, "Popen") as popen,
    ):
        worker.run()
    popen.assert_not_called()
    assert failures


def test_ocr_worker_cancel_terminates_active_process() -> None:
    process = _FakeProcess(timeout_forever=True)
    worker = ImageImportWorker("image.png", "jiyan")
    worker.PROCESS_TIMEOUT_SECONDS = 5.0
    failures: list[object] = []
    results: list[object] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(results.append)
    with (
        patch.object(image_import_worker, "QImageReader", return_value=_FakeReader()),
        patch.object(image_import_worker.subprocess, "Popen", return_value=process),
    ):
        runner = threading.Thread(target=worker.run)
        runner.start()
        assert process.started.wait(1.0)
        worker.cancel()
        runner.join(1.0)
    assert not runner.is_alive()
    assert process.terminated
    assert process.returncode is not None
    assert not results


def test_powershell_clipboard_capture_starts_import_while_window_remains_open() -> None:
    class Timer:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    class Process:
        def poll(self):
            return None

    imported: list[tuple[str, pity_tracker.ConveneCaptureContext | None]] = []
    process = Process()
    def start_import(
        url: str,
        *,
        capture_context: pity_tracker.ConveneCaptureContext | None = None,
    ) -> None:
        imported.append((url, capture_context))

    owner = SimpleNamespace(
        _pwsh_process=process,
        _pwsh_poll_timer=Timer(),
        _pwsh_cancelled=False,
        _clipboard_before_external="old clipboard",
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _start_import=start_import,
    )
    clipboard_url = (
        "https://aki-gm-resources.example/record?player_id=p2&record_id=r2&"
        "svr_id=s2&resources_id=c2&lang=en"
    )
    clipboard = SimpleNamespace(text=lambda: clipboard_url)
    with patch.object(pity_tracker.QApplication, "clipboard", return_value=clipboard), patch.object(
        pity_tracker, "get_brave_cdp_convene_url", return_value="stale-brave-url"
    ) as brave:
        pity_tracker.LegacyPityTrackerWidget._await_wuwatracker_import(cast(pity_tracker.LegacyPityTrackerWidget, owner))
    assert owner._pwsh_process is None
    assert owner._pwsh_poll_timer.stopped
    assert imported[0][0] == clipboard_url
    capture = imported[0][1]
    assert capture is not None
    assert capture.source_url == clipboard_url
    assert capture.discovery_source == "external_clipboard"
    assert owner._pwsh_process is None  # Handle is released; visible shell is not terminated.
    assert process.poll() is None
    brave.assert_not_called()


def test_powershell_polling_rejects_unchanged_clipboard() -> None:
    class Timer:
        def stop(self) -> None:
            pass

    class Process:
        def poll(self):
            return 0

    stale_url = (
        "https://aki-gm-resources.example/record?player_id=p1&record_id=r1&"
        "svr_id=s1&resources_id=c1&lang=en"
    )
    imported: list[object] = []
    owner = SimpleNamespace(
        _pwsh_process=Process(),
        _pwsh_poll_timer=Timer(),
        _pwsh_cancelled=False,
        _clipboard_before_external=stale_url,
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _start_import=lambda url, *, capture_context=None: imported.append(url),
        _on_sync_error=lambda message: imported.append(message),
    )
    clipboard = SimpleNamespace(text=lambda: stale_url)

    with patch.object(pity_tracker.QApplication, "clipboard", return_value=clipboard):
        pity_tracker.LegacyPityTrackerWidget._await_wuwatracker_import(
            cast(pity_tracker.LegacyPityTrackerWidget, owner)
        )

    assert imported == [
        "The external URL finder did not provide a new valid clipboard URL."
    ]


def test_powershell_callback_after_cleanup_does_not_restart_import() -> None:
    class Timer:
        def stop(self) -> None:
            pass

    imported: list[str] = []
    owner = SimpleNamespace(
        _pwsh_process=None,
        _pwsh_poll_timer=Timer(),
        _pwsh_cancelled=False,
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _start_import=imported.append,
    )
    pity_tracker.LegacyPityTrackerWidget._await_wuwatracker_import(cast(pity_tracker.LegacyPityTrackerWidget, owner))
    assert imported == []


def test_powershell_shutdown_stops_monitoring_without_terminating_process() -> None:
    process = _FakeProcess(timeout_forever=True)

    class Timer:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    owner = SimpleNamespace(
        _pwsh_process=process,
        _pwsh_poll_timer=Timer(),
        _import_thread=None,
        _pwsh_cancelled=False,
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
    )
    assert pity_tracker.LegacyPityTrackerWidget.shutdown_workers(cast(pity_tracker.LegacyPityTrackerWidget, owner))
    assert not process.terminated
    assert not process.killed
    assert owner._pwsh_process is None
    assert owner._pwsh_poll_timer.stopped


class _RunningThread:
    def __init__(self, wait_result: bool) -> None:
        self.wait_result = wait_result

    def isRunning(self) -> bool:
        return True

    def quit(self) -> None:
        pass

    def requestInterruption(self) -> None:
        pass

    def wait(self, _timeout: int) -> bool:
        return self.wait_result


def test_home_shutdown_requests_async_cancel_for_banner_catalog_and_news_workers() -> None:
    class ActiveThread:
        def isRunning(self) -> bool:
            return True

        def quit(self) -> None:
            pass

        def requestInterruption(self) -> None:
            pass

        def wait(self, _timeout: int) -> bool:
            pytest.fail("Home shutdown must not block on worker threads")

    class Worker:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    banner_thread = ActiveThread()
    catalog_thread = ActiveThread()
    news_thread = ActiveThread()
    banner_worker = Worker()
    catalog_worker = Worker()
    owner = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_completion_emitted=False,
        banner_thread=banner_thread,
        banner_worker=banner_worker,
        catalog_thread=catalog_thread,
        catalog_worker=catalog_worker,
        pity_tracker=SimpleNamespace(worker=news_thread),
        _clear_banner_worker=lambda: None,
        _clear_catalog_worker=lambda: None,
    )
    assert not HomeTab.shutdown_workers(cast(HomeTab, owner))
    assert owner._shutdown_requested
    assert banner_worker.cancelled
    assert catalog_worker.cancelled


def test_home_cleanup_and_shutdown_signal_run_after_all_threads_finish() -> None:
    calls: list[str] = []

    class FinishedThread:
        def isRunning(self) -> bool:
            return False

        def deleteLater(self) -> None:
            calls.append("delete")

    class FinishedSignal:
        def emit(self) -> None:
            calls.append("shutdown-finished")

    owner = SimpleNamespace(
        _shutdown_requested=True,
        _shutdown_completion_emitted=False,
        banner_thread=FinishedThread(),
        banner_worker=object(),
        catalog_thread=FinishedThread(),
        catalog_worker=object(),
        pity_tracker=SimpleNamespace(worker=FinishedThread()),
        shutdown_finished=FinishedSignal(),
    )
    owner._clear_banner_worker = lambda: HomeTab._clear_banner_worker(
        cast(HomeTab, owner)
    )
    owner._clear_catalog_worker = lambda: HomeTab._clear_catalog_worker(
        cast(HomeTab, owner)
    )
    owner._check_shutdown_complete = lambda: HomeTab._check_shutdown_complete(
        cast(HomeTab, owner)
    )

    HomeTab._check_shutdown_complete(cast(HomeTab, owner))

    assert owner._shutdown_completion_emitted
    assert owner.banner_thread is None
    assert owner.banner_worker is None
    assert owner.catalog_thread is None
    assert owner.catalog_worker is None
    assert calls == ["delete", "delete", "shutdown-finished"]


def test_cancelled_home_workers_skip_work_or_discard_results(monkeypatch) -> None:
    completed: list[bool] = []
    banner_results: list[object] = []
    banner = BannerWorker()
    banner.finished.connect(banner_results.append)
    banner.completed.connect(lambda: completed.append(True))
    banner.cancel()
    monkeypatch.setattr(
        "src.wuwa_calculator.app.home_tab.fetch_current_banner",
        lambda: pytest.fail("cancelled banner worker started network work"),
    )
    banner.run()
    assert banner_results == []
    assert completed == [True]

    catalog_results: list[object] = []
    catalog = CatalogWorker()
    catalog.finished.connect(catalog_results.append)
    catalog.completed.connect(lambda: completed.append(True))

    def finish_catalog_after_cancel() -> list[object]:
        catalog.cancel()
        return []

    monkeypatch.setattr(
        "src.wuwa_calculator.app.banners.wuwa_tracker_adapter.fetch_banner_catalog",
        finish_catalog_after_cancel,
        raising=False,
    )
    catalog.run()
    assert catalog_results == []
    assert completed == [True, True]


def test_home_shutdown_without_active_workers_completes_without_waiting() -> None:
    class StoppedThread:
        def isRunning(self) -> bool:
            return False

        def deleteLater(self) -> None:
            pass

    owner = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_completion_emitted=False,
        banner_thread=StoppedThread(),
        banner_worker=object(),
        catalog_thread=StoppedThread(),
        catalog_worker=object(),
        pity_tracker=SimpleNamespace(worker=StoppedThread()),
    )
    owner._clear_banner_worker = lambda: HomeTab._clear_banner_worker(
        cast(HomeTab, owner)
    )
    owner._clear_catalog_worker = lambda: HomeTab._clear_catalog_worker(
        cast(HomeTab, owner)
    )
    owner._check_shutdown_complete = lambda: HomeTab._check_shutdown_complete(
        cast(HomeTab, owner)
    )
    assert HomeTab.shutdown_workers(cast(HomeTab, owner))
    assert owner._shutdown_requested
    assert owner._shutdown_completion_emitted
    assert owner.banner_thread is None
    assert owner.catalog_thread is None


def test_convene_shutdown_refuses_when_import_thread_remains_active() -> None:
    owner = SimpleNamespace(
        _pwsh_poll_timer=SimpleNamespace(stop=lambda: None),
        _pwsh_process=None,
        _import_thread=_RunningThread(False),
        _pwsh_cancelled=False,
    )
    assert not pity_tracker.LegacyPityTrackerWidget.shutdown_workers(cast(pity_tracker.LegacyPityTrackerWidget, owner), 1)


def test_home_and_convene_shutdown_complete_when_threads_stop() -> None:
    convene = SimpleNamespace(
        _pwsh_poll_timer=SimpleNamespace(stop=lambda: None),
        _pwsh_process=None,
        _import_thread=_RunningThread(True),
        _pwsh_cancelled=False,
        _clear_import=lambda: None,
    )
    assert pity_tracker.LegacyPityTrackerWidget.shutdown_workers(cast(pity_tracker.LegacyPityTrackerWidget, convene), 50)


def test_dialog_shutdown_requests_ocr_cancel_and_waits() -> None:
    class Worker:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    worker = Worker()

    class Thread:
        def quit(self) -> None:
            pass

        def isRunning(self) -> bool:
            return True

        def wait(self, timeout: int) -> bool:
            assert timeout == 25
            return True

    dialog = SimpleNamespace(
        ocr_thread=Thread(), ocr_worker=worker, _clear_import_worker=lambda: None
    )
    assert CustomImportPopup.shutdown_ocr(cast(CustomImportPopup, dialog), 25)
    assert worker.cancelled


def test_multimedia_and_dps_close_ignore_when_stop_fails() -> None:
    class Event:
        ignored = False
        accepted = False

        def ignore(self) -> None:
            self.ignored = True

        def accept(self) -> None:
            self.accepted = True

    panel_event = Event()
    panel = SimpleNamespace(_stop_live_analysis=lambda: False)
    DpsSimulationPanel.closeEvent(cast(DpsSimulationPanel, panel), panel_event)
    assert panel_event.ignored and not panel_event.accepted

    media_event = Event()
    media = SimpleNamespace(
        dps_panel=panel,
        video_player=SimpleNamespace(stop_video=lambda: pytest.fail("video stopped")),
    )
    MultimediaTab.closeEvent(cast(MultimediaTab, media), media_event)
    assert media_event.ignored and not media_event.accepted


def test_multimedia_shutdown_stops_video_after_analysis_stops() -> None:
    stopped: list[bool] = []
    media = SimpleNamespace(
        dps_panel=SimpleNamespace(_stop_live_analysis=lambda: True),
        video_player=SimpleNamespace(stop_video=lambda: stopped.append(True)),
    )
    assert MultimediaTab.shutdown(cast(MultimediaTab, media))
    assert stopped == [True]


def test_live_analysis_shutdown_is_async_and_keeps_owner_references_until_finished() -> None:
    class Worker:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Thread:
        running = True
        quit_requested = False

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_requested = True

        def wait(self, _timeout: int) -> bool:
            pytest.fail("live shutdown must not block waiting for the worker")

        def deleteLater(self) -> None:
            pass

    worker = Worker()
    thread = Thread()
    status: list[str] = []
    panel = SimpleNamespace(
        live_worker=worker,
        live_thread=thread,
        analysis_status=SimpleNamespace(setText=status.append),
    )

    assert not DpsSimulationPanel._stop_live_analysis(
        cast(DpsSimulationPanel, panel)
    )
    assert worker.cancelled
    assert thread.quit_requested
    assert panel.live_worker is worker
    assert panel.live_thread is thread
    assert status == []

    thread.running = False
    assert DpsSimulationPanel._stop_live_analysis(cast(DpsSimulationPanel, panel))
    assert panel.live_worker is None
    assert panel.live_thread is None
    assert status == ["Análise ao vivo parada"]


def test_live_thread_finished_clears_references_then_notifies_pending_close() -> None:
    calls: list[str] = []

    class Thread:
        def deleteLater(self) -> None:
            calls.append("delete")

    class Signal:
        def emit(self) -> None:
            calls.append("finished")

    thread = Thread()
    panel = SimpleNamespace(
        live_worker=object(),
        live_thread=thread,
        shutdown_finished=Signal(),
    )

    DpsSimulationPanel._on_live_thread_finished(cast(DpsSimulationPanel, panel))

    assert panel.live_worker is None
    assert panel.live_thread is None
    assert calls == ["delete", "finished"]


def test_window_defers_confirmed_close_until_home_workers_finish(monkeypatch) -> None:
    class Event:
        ignored = False
        accepted = False

        def ignore(self) -> None:
            self.ignored = True

        def accept(self) -> None:
            self.accepted = True

    class ActiveHome:
        def shutdown_workers(self) -> bool:
            return False

    monkeypatch.setattr(
        "src.wuwa_calculator.app.window.HomeTab",
        ActiveHome,
    )
    event = Event()
    owner = SimpleNamespace(
        preferences=SimpleNamespace(value=lambda *_args, **_kwargs: False),
        _close_confirmation_accepted=False,
        _close_after_background_shutdown=False,
        _import_dialog=None,
        _tab_widgets={0: ActiveHome()},
    )

    WuwaQtWindow.closeEvent(cast(WuwaQtWindow, owner), event)

    assert event.ignored and not event.accepted
    assert owner._close_after_background_shutdown


def test_window_resumes_pending_close_only_after_shutdown_signal() -> None:
    closed: list[bool] = []
    owner = SimpleNamespace(
        _close_after_background_shutdown=True,
        close=lambda: closed.append(True),
    )

    WuwaQtWindow._resume_close_after_background_shutdown(cast(WuwaQtWindow, owner))

    assert not owner._close_after_background_shutdown
    assert closed == [True]
