from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication
import pytest

from src.wuwa_calculator.app.dev_ipc import (
    DevCommandServer,
    send_dev_toggle,
)


_existing_application = QApplication.instance()
_APPLICATION = (
    _existing_application
    if isinstance(_existing_application, QApplication)
    else QApplication([])
)


def test_dev_command_reports_no_running_instance_without_starting_one() -> None:
    server_name = f"Tethys.DevControl.Test.{uuid4().hex}"

    assert send_dev_toggle(server_name, timeout_ms=100) is None


def test_dev_command_activates_existing_local_server_on_gui_thread() -> None:
    server_name = f"Tethys.DevControl.Test.{uuid4().hex}"
    states = [False]
    activations: list[object] = []

    def toggle() -> bool:
        states[0] = not states[0]
        activations.append(QThread.currentThread())
        return states[0]

    server = DevCommandServer(
        toggle,
        server_name=server_name,
    )
    assert server.listen()

    client_script = (
        "import os; "
        "from src.wuwa_calculator.app.dev_ipc import send_dev_toggle; "
        "state = send_dev_toggle(os.environ['TETHYS_DEV_SERVER_NAME'], "
        "timeout_ms=2000); "
        "raise SystemExit(0 if state is True else 1)"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", client_script],
        env={**os.environ, "TETHYS_DEV_SERVER_NAME": server_name},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)

    def finish_when_client_exits() -> None:
        if worker.poll() is not None:
            loop.quit()

    poll.timeout.connect(finish_when_client_exits)
    poll.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    poll.stop()
    if worker.poll() is None:
        worker.kill()
    stdout, stderr = worker.communicate(timeout=2)
    server.close()

    assert worker.returncode == 0, (stdout, stderr)
    assert activations == [_APPLICATION.thread()]
    assert states == [True]


def test_tethys_dev_argument_uses_running_instance_without_starting_an_app() -> None:
    states = [False]
    activations: list[object] = []

    def toggle() -> bool:
        states[0] = not states[0]
        activations.append(QThread.currentThread())
        return states[0]

    server = DevCommandServer(
        toggle,
    )
    if not server.listen():
        pytest.skip("The default Tethys DEV channel is already in use.")

    project_root = Path(__file__).resolve().parents[1]
    expected_outputs = (
        (True, "MODO DEV ativado."),
        (False, "MODO DEV desativado."),
        (True, "MODO DEV ativado."),
        (False, "MODO DEV desativado."),
    )
    for expected_state, expected_message in expected_outputs:
        worker = subprocess.Popen(
            [sys.executable, str(project_root / "main.py"), "--dev"],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(5)
        poll.timeout.connect(
            lambda current_worker=worker: (
                loop.quit() if current_worker.poll() is not None else None
            )
        )
        poll.start()
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        poll.stop()
        if worker.poll() is None:
            worker.kill()
        stdout, stderr = worker.communicate(timeout=2)

        assert worker.returncode == 0, (stdout, stderr)
        assert expected_message in stdout
        assert states[0] is expected_state

    server.close()
    assert activations == [_APPLICATION.thread()] * 4
