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
from src.wuwa_calculator.app.home_tab import HomeTab
from src.wuwa_calculator.app.image_import.image_import_worker import ImageImportWorker
from src.wuwa_calculator.app.import_dialog import CustomImportPopup
from src.wuwa_calculator.app.multimedia.multimedia_tab import MultimediaTab


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


def test_powershell_polling_stops_and_normal_exit_starts_import() -> None:
    class Timer:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    class Process:
        def poll(self):
            return 0

    imported: list[str] = []
    owner = SimpleNamespace(
        _pwsh_process=Process(),
        _pwsh_poll_timer=Timer(),
        _pwsh_cancelled=False,
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _start_import=imported.append,
    )
    with patch.object(pity_tracker, "get_brave_cdp_convene_url", return_value="local-url"):
        pity_tracker.LegacyPityTrackerWidget._await_wuwatracker_import(cast(pity_tracker.LegacyPityTrackerWidget, owner))
    assert owner._pwsh_process is None
    assert owner._pwsh_poll_timer.stopped
    assert imported == ["local-url"]


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


def test_powershell_shutdown_terminates_process_and_stops_timer() -> None:
    process = _FakeProcess(timeout_forever=True)

    class Timer:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    owner = SimpleNamespace(
        _pwsh_process=process,
        _pwsh_poll_timer=Timer(),
        _import_thread=None,
        _sync_worker=None,
        _pwsh_cancelled=False,
        sync_status=SimpleNamespace(setText=lambda _text: None),
        sync_label=SimpleNamespace(setText=lambda _text: None),
        sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
    )
    assert pity_tracker.LegacyPityTrackerWidget.shutdown_workers(cast(pity_tracker.LegacyPityTrackerWidget, owner))
    assert process.terminated
    assert owner._pwsh_process is None
    assert owner._pwsh_poll_timer.stopped


class _RunningThread:
    def __init__(self, wait_result: bool) -> None:
        self.wait_result = wait_result

    def isRunning(self) -> bool:
        return True

    def quit(self) -> None:
        pass

    def wait(self, _timeout: int) -> bool:
        return self.wait_result


def test_home_shutdown_refuses_when_thread_remains_active() -> None:
    owner = SimpleNamespace(
        banner_thread=_RunningThread(False),
        catalog_thread=None,
        pity_tracker=SimpleNamespace(worker=None),
    )
    assert not HomeTab.shutdown_workers(cast(HomeTab, owner), timeout_ms=1)


def test_convene_shutdown_refuses_when_import_thread_remains_active() -> None:
    owner = SimpleNamespace(
        _pwsh_poll_timer=SimpleNamespace(stop=lambda: None),
        _pwsh_process=None,
        _import_thread=_RunningThread(False),
        _sync_worker=None,
        _pwsh_cancelled=False,
    )
    assert not pity_tracker.LegacyPityTrackerWidget.shutdown_workers(cast(pity_tracker.LegacyPityTrackerWidget, owner), 1)


def test_home_and_convene_shutdown_complete_when_threads_stop() -> None:
    home = SimpleNamespace(
        banner_thread=_RunningThread(True),
        catalog_thread=_RunningThread(True),
        pity_tracker=SimpleNamespace(worker=_RunningThread(True)),
        _clear_banner_worker=lambda: None,
        _clear_catalog_worker=lambda: None,
    )
    assert HomeTab.shutdown_workers(cast(HomeTab, home), timeout_ms=50)

    convene = SimpleNamespace(
        _pwsh_poll_timer=SimpleNamespace(stop=lambda: None),
        _pwsh_process=None,
        _import_thread=_RunningThread(True),
        _sync_worker=_RunningThread(True),
        _pwsh_cancelled=False,
        _clear_import=lambda: None,
        _clear_sync_worker=lambda: None,
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
