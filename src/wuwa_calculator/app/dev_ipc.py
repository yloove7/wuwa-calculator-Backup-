"""Private local IPC for activating development mode in a running instance."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket


SERVER_NAME = "Tethys.DevControl.v1"
_TOGGLE_DEV = b"TOGGLE_DEV\n"
_ENABLED = b"ON\n"
_DISABLED = b"OFF\n"
_REJECTED = b"ERROR\n"


def send_dev_toggle(
    server_name: str = SERVER_NAME,
    timeout_ms: int = 1000,
) -> bool | None:
    """Toggle DEV in the running app; None means no successful reply."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return None
    if socket.write(_TOGGLE_DEV) != len(_TOGGLE_DEV):
        socket.abort()
        return None
    if not socket.waitForBytesWritten(timeout_ms):
        socket.abort()
        return None
    response = bytearray()
    while b"\n" not in response:
        if not socket.bytesAvailable() and not socket.waitForReadyRead(timeout_ms):
            socket.abort()
            return None
        response.extend(socket.readAll().data())
    socket.disconnectFromServer()
    if bytes(response) == _ENABLED:
        return True
    if bytes(response) == _DISABLED:
        return False
    return None


class DevCommandServer(QObject):
    """Receive the single supported DEV activation command in the GUI process."""

    def __init__(
        self,
        toggle_dev: Callable[[], bool],
        server_name: str = SERVER_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._toggle_dev = toggle_dev
        self._server = QLocalServer(self)
        self._request_buffers: dict[int, bytearray] = {}
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept_connection)
        self.server_name = server_name

    def listen(self) -> bool:
        return self._server.listen(self.server_name)

    @property
    def error_string(self) -> str:
        return self._server.errorString()

    def close(self) -> None:
        self._server.close()

    @Slot()
    def _accept_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket_id = id(socket)
            self._request_buffers[socket_id] = bytearray()
            socket.readyRead.connect(
                lambda current_socket=socket: self._process_command(current_socket)
            )
            socket.disconnected.connect(
                lambda current_id=socket_id: self._request_buffers.pop(
                    current_id, None
                )
            )
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._process_command(socket)

    def _process_command(self, socket: QLocalSocket) -> None:
        socket_id = id(socket)
        request = self._request_buffers.get(socket_id)
        if request is None:
            return
        request.extend(socket.readAll().data())
        if b"\n" not in request:
            return
        command = bytes(request)
        self._request_buffers.pop(socket_id, None)
        if command != _TOGGLE_DEV:
            socket.write(_REJECTED)
            socket.flush()
            socket.disconnectFromServer()
            return
        enabled = self._toggle_dev()
        socket.write(_ENABLED if enabled else _DISABLED)
        socket.flush()
        socket.disconnectFromServer()
