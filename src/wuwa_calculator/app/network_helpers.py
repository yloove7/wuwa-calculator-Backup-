"""Small shared Qt network helpers used by the app UI."""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkReply


def read_network_reply(reply: object) -> bytes:
    """Return the payload bytes for a successful Qt network reply.

    This preserves the existing app behavior for empty replies and failed
    requests: on error or closed replies, it returns an empty byte string.
    """
    if not isinstance(reply, QNetworkReply):
        return b""
    if reply.error() != QNetworkReply.NetworkError.NoError or not reply.isOpen():
        return b""
    try:
        return bytes(reply.readAll().data())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return b""


def pixmap_from_bytes(data: bytes) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(data)
    return pixmap
