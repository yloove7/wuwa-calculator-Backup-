"""Post-WGC frame processing and backend lifecycle adapter."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable

from .settings import CaptureSettings


class FrameProcessor:
    """Applies optional processing after a frame arrives from WGC."""

    def __init__(self, settings: CaptureSettings | None = None) -> None:
        self.settings = settings or CaptureSettings()
        self._last_frame_at = 0.0
        self._lock = Lock()

    def configure(self, settings: CaptureSettings) -> None:
        with self._lock:
            self.settings = settings
            self._last_frame_at = 0.0

    def process(self, frame: Any, now: float | None = None) -> Any | None:
        if frame is None:
            return None
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            settings = self.settings
            if settings.limit_framerate:
                interval = 1.0 / max(1, min(240, int(settings.max_framerate)))
                if self._last_frame_at and timestamp - self._last_frame_at < interval:
                    return None
                self._last_frame_at = timestamp
            processed = self._process_alpha(frame, settings)
            return self._process_color(processed, settings)

    @staticmethod
    def _process_alpha(frame: Any, settings: CaptureSettings) -> Any:
        if not settings.allow_transparency and not settings.premultiplied_alpha:
            return frame
        shape = getattr(frame, "shape", ())
        if len(shape) < 3 or shape[2] < 4:
            return frame
        if settings.allow_transparency:
            if settings.premultiplied_alpha:
                return FrameProcessor._premultiply_alpha(frame)
            return frame
        frame[:, :, 3] = 255
        return frame

    @staticmethod
    def _premultiply_alpha(frame: Any) -> Any:
        import numpy as np

        alpha = frame[:, :, 3:4].astype(np.uint16)
        frame[:, :, :3] = ((frame[:, :, :3].astype(np.uint16) * alpha) // 255).astype(np.uint8)
        return frame

    @staticmethod
    def _process_color(frame: Any, settings: CaptureSettings) -> Any:
        # WGC currently supplies BGRA8; other formats require renderer support.
        return frame


class CaptureController:
    """Thin lifecycle adapter around the existing capture backend."""

    def __init__(self, start_backend: Callable[[int], None], stop_backend: Callable[[], None]) -> None:
        self._start_backend = start_backend
        self._stop_backend = stop_backend
        self.settings = CaptureSettings()
        self.processor = FrameProcessor(self.settings)

    def configure(self, settings: CaptureSettings) -> None:
        self.settings = settings
        self.processor.configure(settings)

    def start(self, hwnd: int) -> None:
        self._start_backend(hwnd)

    def stop(self) -> None:
        self._stop_backend()

    def process_frame(self, frame: Any) -> Any | None:
        return self.processor.process(frame)
