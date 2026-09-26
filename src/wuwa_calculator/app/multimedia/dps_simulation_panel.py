"""Interactive DPS timeline synchronized with the native Tethys video player."""

from __future__ import annotations

import math
import os
import re
import sys
import time
from collections import defaultdict
from threading import Lock
from typing import Any, cast
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pyqtgraph as pg
from PySide6.QtCore import QElapsedTimer, QObject, QTime, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox, QGraphicsLayout, QHBoxLayout, QLabel, QTimeEdit, QVBoxLayout, QWidget,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.wuwa_calculator.app.multimedia.history_video_player import HistoryVideoPlayer

from src.wuwa_calculator.app.components import Card
from src.wuwa_calculator.app.capture.controller import FrameProcessor
from src.wuwa_calculator.app.capture.damage_events import DamageEventTracker
from src.wuwa_calculator.app.capture.learning import LearningStore, classify_screen_text
from src.wuwa_calculator.app.capture.settings import CaptureSettings


ANALYSIS_BUCKET_SECONDS = 5.0
INACTIVITY_TIMEOUT = 12.0
MIN_INACTIVITY_ANALYSIS_SECONDS = 15.0
OCR_SAMPLE_FPS = 10.0
DEFAULT_PREVIEW_FPS = 60.0
# A cadence of 30 FPS is steadier for WGC previews than following monitor Hz.
PREVIEW_OUTPUT_FPS = 45.0
MAX_PREVIEW_FPS = 240.0
MAX_LIVE_HIT_MARKERS = 3000
COMBAT_ROI = (0.15, 0.90, 0.03, 0.97)
MAX_DAMAGE_VALUE = 10_000_000
MAP_ROI = (0.05, 0.15, 0.02, 0.20)
PALAVRAS_IGNORADAS = ("PHYSX", "CPU", "GPU", "FPS", "MSI", "NVIDIA", "RAM", "MS")
MAP_UI_ROI = (0.02, 0.24, 0.68, 0.99)
FORA_DE_COMBATE = "FORA_DE_COMBATE"
EM_COMBATE = "EM_COMBATE"
EXPLORACAO = "EXPLORACAO"
MAPA_ABERTO = "MAPA_ABERTO"
EM_MENU = "EM_MENU"
INTERFACE_OU_MENU = "INTERFACE_OU_MENU"
PRE_COMBATE = "PRE_COMBATE"
FIM_DE_COMBATE = "FIM_DE_COMBATE"
TELA_DE_RECOMPENSA = "TELA_DE_RECOMPENSA"
LOGIN = "LOGIN"
CARREGANDO = "CARREGANDO"
FORA_DO_JOGO = "FORA_DO_JOGO"


class CombatStateMachine:
    """Track combat segments without counting traversal or menu time as DPS."""

    def __init__(self) -> None:
        self.state = FORA_DE_COMBATE
        self._last_damage_at: float | None = None
        self._segment_started_at: float | None = None
        self._active_seconds = 0.0

    def update(self, timestamp: float, has_damage: bool) -> tuple[str, bool]:
        changed = False
        if self.state in {
            MAPA_ABERTO,
            EM_MENU,
            INTERFACE_OU_MENU,
            PRE_COMBATE,
            FIM_DE_COMBATE,
            TELA_DE_RECOMPENSA,
            LOGIN,
            CARREGANDO,
            FORA_DO_JOGO,
        }:
            if self.state == PRE_COMBATE and has_damage:
                self.state = EM_COMBATE
                self._segment_started_at = timestamp
                self._last_damage_at = timestamp
                return self.state, True
            return self.state, False
        if has_damage:
            if self.state != EM_COMBATE:
                self.state = EM_COMBATE
                self._segment_started_at = timestamp
                changed = True
            self._last_damage_at = timestamp
        elif (
            self.state == EM_COMBATE
            and self._last_damage_at is not None
            and timestamp - self._last_damage_at > 3.0
        ):
            if self._segment_started_at is not None:
                self._active_seconds += max(0.0, self._last_damage_at - self._segment_started_at)
            self._segment_started_at = None
            self.state = FORA_DE_COMBATE
            changed = True
        return self.state, changed

    def set_map_open(self, is_open: bool) -> tuple[str, bool]:
        return self.set_interface_open(is_open, MAPA_ABERTO)

    def set_interface_open(
        self,
        is_open: bool,
        state_name: str = EM_MENU,
    ) -> tuple[str, bool]:
        if is_open:
            if self.state in {
                PRE_COMBATE,
                FIM_DE_COMBATE,
                TELA_DE_RECOMPENSA,
                LOGIN,
                CARREGANDO,
                FORA_DO_JOGO,
            }:
                return self.state, False
            if self.state != state_name:
                if self.state == EM_COMBATE and self._segment_started_at is not None:
                    last_damage = self._last_damage_at or self._segment_started_at
                    self._active_seconds += max(0.0, last_damage - self._segment_started_at)
                self.state = state_name
                self._segment_started_at = None
                return self.state, True
            return self.state, False
        if self.state in {
            MAPA_ABERTO,
            EM_MENU,
            INTERFACE_OU_MENU,
            PRE_COMBATE,
            FIM_DE_COMBATE,
            TELA_DE_RECOMPENSA,
            LOGIN,
            CARREGANDO,
            FORA_DO_JOGO,
        }:
            self.state = EXPLORACAO
            self._last_damage_at = None
            self._segment_started_at = None
            return self.state, True
        return self.state, False

    def set_pre_combat(self) -> tuple[str, bool]:
        if self.state != PRE_COMBATE:
            self._freeze_segment()
            self.state = PRE_COMBATE
            return self.state, True
        return self.state, False

    def set_finished(self) -> tuple[str, bool]:
        if self.state != FIM_DE_COMBATE:
            self._freeze_segment()
            self.state = FIM_DE_COMBATE
            return self.state, True
        return self.state, False

    def set_reward_screen(self) -> tuple[str, bool]:
        if self.state != TELA_DE_RECOMPENSA:
            self._freeze_segment()
            self.state = TELA_DE_RECOMPENSA
            return self.state, True
        return self.state, False

    def set_login(self) -> tuple[str, bool]:
        if self.state != FORA_DO_JOGO:
            self._freeze_segment()
            self.state = FORA_DO_JOGO
            return self.state, True
        return self.state, False

    def set_outside_game(self) -> tuple[str, bool]:
        return self.set_login()

    def set_loading(self) -> tuple[str, bool]:
        if self.state != CARREGANDO:
            self._freeze_segment()
            self.state = CARREGANDO
            return self.state, True
        return self.state, False

    def resume_from_loading(self, hud_ready: bool) -> tuple[str, bool]:
        if self.state in {LOGIN, CARREGANDO, FORA_DO_JOGO} and hud_ready:
            self.state = EXPLORACAO
            self._last_damage_at = None
            self._segment_started_at = None
            return self.state, True
        return self.state, False

    def resume_new_battle(self) -> tuple[str, bool]:
        was_suspended = self.state in {
            PRE_COMBATE,
            FIM_DE_COMBATE,
            TELA_DE_RECOMPENSA,
            MAPA_ABERTO,
            EM_MENU,
            INTERFACE_OU_MENU,
            LOGIN,
            CARREGANDO,
            FORA_DO_JOGO,
        }
        self._active_seconds = 0.0
        self._last_damage_at = None
        self._segment_started_at = None
        self.state = EXPLORACAO
        return self.state, was_suspended

    def _freeze_segment(self) -> None:
        if self._segment_started_at is not None:
            last_damage = self._last_damage_at or self._segment_started_at
            self._active_seconds += max(0.0, last_damage - self._segment_started_at)
        self._segment_started_at = None
        self._last_damage_at = None

    def active_seconds(self, timestamp: float) -> float:
        active_seconds = self._active_seconds
        if self.state == EM_COMBATE and self._segment_started_at is not None:
            active_seconds += max(0.0, timestamp - self._segment_started_at)
        return active_seconds


class DeteccaoTracker:
    """Reject repeated HUD text using its bounding box and lifetime."""

    def __init__(self) -> None:
        self._observations: list[tuple[tuple[int, int, int, int], float, float]] = []

    def expire(self, timestamp: float) -> None:
        self._observations = [
            observation
            for observation in self._observations
            if timestamp - observation[2] <= 0.8
        ]

    @staticmethod
    def _iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        intersection = max(0, right - left) * max(0, bottom - top)
        first_area = max(1, first[2] - first[0]) * max(1, first[3] - first[1])
        second_area = max(1, second[2] - second[0]) * max(1, second[3] - second[1])
        return intersection / max(1, first_area + second_area - intersection)

    def accept(
        self,
        center_x: int,
        center_y: int,
        item_width: int,
        item_height: int,
        timestamp: float,
    ) -> bool:
        box = (
            center_x - item_width // 2,
            center_y - item_height // 2,
            center_x + (item_width + 1) // 2,
            center_y + (item_height + 1) // 2,
        )
        for index, (previous_box, first_seen, last_seen) in enumerate(self._observations):
            if self._iou(box, previous_box) < 0.25:
                continue
            self._observations[index] = (box, first_seen, timestamp)
            if timestamp - first_seen > 1.0:
                return False
            if timestamp - last_seen <= 0.8:
                return False
            return True
        self._observations.append((box, timestamp, timestamp))
        return True


DamageDetectionTracker = DeteccaoTracker


CLASSES_DE_JOGOS = (
    "UnrealWindow",
    "UnityWndClass",
    "GLFW30",
    "SDL_app",
)
TITULOS_DE_JOGOS = (
    "wuthering waves",
    "league of legends",
    "league of legends™ client",
    "league of legends tm client",
    "honkai star rail",
    "honkai: star rail",
)
TITULOS_DE_LEAGUE = (
    "league of legends",
    "league of legends (tm) client",
    "league of legends™ client",
    "league of legends tm client",
)


class GameWindowGuard:
    """Resolve the active game window without depending on a fixed executable name."""

    WINDOW_TITLE = "Wuthering Waves"
    WINDOW_CLASS = "UnrealWindow"
    GAME_WINDOW_CLASSES = CLASSES_DE_JOGOS

    def __init__(self) -> None:
        self._user32 = None
        if sys.platform == "win32":
            import ctypes

            self._user32 = ctypes.windll.user32

    def _foreground_window(self) -> int | None:
        if sys.platform != "win32":
            return None
        import importlib

        def _coerce(handle):
            try:
                value = int(handle)
            except (TypeError, ValueError):
                return None
            return value or None

        try:
            win32gui = importlib.import_module("win32gui")
            hwnd = getattr(win32gui, "GetForegroundWindow", None)
            if hwnd is None:
                return None
            return _coerce(hwnd())
        except ImportError:
            pass

        if self._user32 is None:
            return None
        foreground = getattr(self._user32, "GetForegroundWindow", None)
        if foreground is None:
            return None
        return _coerce(foreground())

    def list_active_windows(self) -> list[tuple[int, str, str, tuple[int, int, int, int]]]:
        if sys.platform != "win32":
            return []
        import importlib

        try:
            win32gui = importlib.import_module("win32gui")
        except ImportError:
            return self._list_active_windows_with_ctypes()

        matches: list[tuple[int, str, str, tuple[int, int, int, int]]] = []

        def callback(hwnd, _extra):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            window_class = win32gui.GetClassName(hwnd)
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left <= 400 or bottom - top <= 300:
                return True
            matches.append((int(hwnd), title, window_class, (left, top, right, bottom)))
            return True

        win32gui.EnumWindows(callback, None)
        return matches

    def _list_active_windows_with_ctypes(self) -> list[tuple[int, str, str, tuple[int, int, int, int]]]:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        get_text_length = user32.GetWindowTextLengthW
        get_text = user32.GetWindowTextW
        get_class = user32.GetClassNameW
        matches: list[tuple[int, str, str, tuple[int, int, int, int]]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _extra):
            if not user32.IsWindowVisible(hwnd):
                return True
            title_length = get_text_length(hwnd)
            title = ctypes.create_unicode_buffer(max(1, title_length + 1))
            get_text(hwnd, title, len(title))
            window_class = ctypes.create_unicode_buffer(256)
            get_class(hwnd, window_class, len(window_class))
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            if rect.right - rect.left <= 400 or rect.bottom - rect.top <= 300:
                return True
            matches.append((int(hwnd), title.value, window_class.value, (rect.left, rect.top, rect.right, rect.bottom)))
            return True

        user32.EnumWindows(callback, 0)
        return matches

    def _is_game_window(self, title: str, window_class: str) -> bool:
        normalized_title = title.casefold()
        if window_class in self.GAME_WINDOW_CLASSES:
            return True
        if self.WINDOW_CLASS == window_class:
            return True
        if any(title_hint in normalized_title for title_hint in TITULOS_DE_JOGOS):
            return True
        if "abyss" in normalized_title or "game" in normalized_title:
            return True
        return False

    @staticmethod
    def _is_league_window(title: str) -> bool:
        normalized_title = title.casefold()
        return any(title_hint in normalized_title for title_hint in TITULOS_DE_LEAGUE)

    def locate_league_window(self) -> tuple[int, tuple[int, int, int, int]] | None:
        if sys.platform != "win32":
            return None
        windows = self.list_active_windows()
        foreground = self._foreground_window()
        if foreground is not None:
            for hwnd, title, _window_class, bounds in windows:
                if int(hwnd) == int(foreground) and self._is_league_window(title):
                    return hwnd, bounds
        for hwnd, title, _window_class, bounds in windows:
            if self._is_league_window(title):
                return hwnd, bounds
        return None

    def locate_wuthering_window(self) -> tuple[int, tuple[int, int, int, int]] | None:
        if sys.platform != "win32":
            return None
        windows = self.list_active_windows()
        foreground = self._foreground_window()
        candidates = [
            (hwnd, title, window_class, bounds)
            for hwnd, title, window_class, bounds in windows
            if self.WINDOW_TITLE.casefold() in title.casefold()
            or window_class == self.WINDOW_CLASS
        ]
        if foreground is not None:
            for hwnd, _title, _window_class, bounds in candidates:
                if int(hwnd) == int(foreground):
                    return hwnd, bounds
            return None
        if candidates:
            hwnd, _title, _window_class, bounds = candidates[0]
            return hwnd, bounds
        return None

    def locate(self) -> tuple[int, tuple[int, int, int, int]] | None:
        if sys.platform != "win32":
            return None
        active_windows = self.list_active_windows()
        if not active_windows:
            return None

        foreground_hwnd = self._foreground_window()
        if foreground_hwnd is not None:
            foreground_match = None
            for hwnd, title, window_class, bounds in active_windows:
                if int(hwnd) == int(foreground_hwnd):
                    foreground_match = (hwnd, title, window_class, bounds)
                    break

            if foreground_match is None:
                return None

            hwnd, title, window_class, bounds = foreground_match
            if self._is_game_window(title, window_class):
                return hwnd, bounds
            return None

        for hwnd, title, window_class, bounds in active_windows:
            if self._is_game_window(title, window_class):
                return hwnd, bounds

        return None

    def _locate_with_ctypes(self) -> tuple[int, tuple[int, int, int, int]] | None:
        active_windows = self.list_active_windows()
        if not active_windows:
            return None
        foreground_hwnd = self._foreground_window()
        if foreground_hwnd is not None:
            foreground_match = None
            for hwnd, title, window_class, bounds in active_windows:
                if int(hwnd) == int(foreground_hwnd):
                    foreground_match = (hwnd, title, window_class, bounds)
                    break

            if foreground_match is None:
                return None

            hwnd, title, window_class, bounds = foreground_match
            if self._is_game_window(title, window_class):
                return hwnd, bounds
            return None
        for hwnd, title, window_class, bounds in active_windows:
            if self._is_game_window(title, window_class):
                return hwnd, bounds
        return None

    def is_minimized(self, hwnd: int) -> bool:
        if sys.platform != "win32":
            return False
        import importlib

        try:
            win32gui = importlib.import_module("win32gui")
            return bool(win32gui.IsIconic(hwnd))
        except ImportError:
            import ctypes

            return bool(ctypes.windll.user32.IsIconic(hwnd))

    @staticmethod
    def monitor_for_window(bounds: tuple[int, int, int, int]) -> tuple[int, tuple[int, int, int, int]]:
        """Return the DXGI-like monitor ordinal and its desktop rectangle."""
        if sys.platform != "win32":
            return 0, (0, 0, 0, 0)
        import ctypes
        from ctypes import wintypes

        monitors: list[tuple[int, int, int, int]] = []
        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        def callback(_monitor, _dc, rect_ptr, _data):
            rect = rect_ptr.contents
            monitors.append((rect.left, rect.top, rect.right, rect.bottom))
            return True

        user32.EnumDisplayMonitors(None, None, callback, 0)
        if not monitors:
            return 0, (0, 0, 0, 0)
        left, top, right, bottom = bounds
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        containing = [
            (index, rect)
            for index, rect in enumerate(monitors)
            if rect[0] <= center_x < rect[2] and rect[1] <= center_y < rect[3]
        ]
        if containing:
            return containing[0]
        return min(
            enumerate(monitors),
            key=lambda item: abs((item[1][0] + item[1][2]) // 2 - center_x)
            + abs((item[1][1] + item[1][3]) // 2 - center_y),
        )


class CombatFrameGate:
    """Reject black, uniform, or paused frames before OCR is invoked."""

    def __init__(self) -> None:
        self._previous_scene = None
        self._static_since: float | None = None

    def reset(self) -> None:
        self._previous_scene = None
        self._static_since = None

    def allow(self, frame, timestamp: float) -> bool:
        import cv2

        height, width = frame.shape[:2]
        roi_top, roi_bottom, roi_left, roi_right = LiveDamageAnalysisWorker._combat_roi(width, height)
        scene = frame[roi_top:roi_bottom, roi_left:roi_right]
        gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
        mean_value = float(gray.mean())
        contrast = float(gray.std())
        if mean_value < 25.0 or contrast < 12.0:
            self._previous_scene = None
            self._static_since = timestamp
            return False
        sample = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
        if self._previous_scene is not None:
            delta = float(cv2.absdiff(sample, self._previous_scene).mean())
            if delta < 1.5:
                if self._static_since is None:
                    self._static_since = timestamp
                if timestamp - self._static_since >= 0.5:
                    self._previous_scene = sample
                    return False
            else:
                self._static_since = None
        self._previous_scene = sample
        return True


class MapInterfaceDetector:
    """Detect the static dark map/menu surface without sending it to damage OCR."""

    def __init__(self) -> None:
        self._previous_sample = None
        self._static_since: float | None = None

    def reset(self) -> None:
        self._previous_sample = None
        self._static_since = None

    def is_open(self, frame, timestamp: float) -> bool:
        import cv2

        height, width = frame.shape[:2]
        top, bottom, left, right = MAP_UI_ROI
        crop = frame[int(height * top):int(height * bottom), int(width * left):int(width * right)]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mean_value = float(gray.mean())
        contrast = float(gray.std())
        edges = cv2.Canny(gray, 70, 150)
        edge_ratio = float((edges > 0).mean())
        candidate = mean_value < 125.0 and contrast > 8.0 and edge_ratio > 0.006
        sample = cv2.resize(gray, (64, 32), interpolation=cv2.INTER_AREA)
        if not candidate:
            self.reset()
            return False
        if self._previous_sample is not None:
            delta = float(cv2.absdiff(sample, self._previous_sample).mean())
            if delta < 1.5:
                if self._static_since is None:
                    self._static_since = timestamp
                self._previous_sample = sample
                return timestamp - self._static_since >= 0.7
        self._static_since = timestamp
        self._previous_sample = sample
        return False


class InterfaceMenuDetector:
    """Detect map, menu, inventory, convene, and character-screen interfaces."""

    def __init__(self) -> None:
        self._map_detector = MapInterfaceDetector()
        self._no_hud_since: float | None = None

    def reset(self) -> None:
        self._map_detector.reset()
        self._no_hud_since = None

    def is_menu(self, frame, timestamp: float) -> bool:
        if self._map_detector.is_open(frame, timestamp):
            return True
        if self.combat_hud_visible(frame):
            self._no_hud_since = None
            return False
        if self._no_hud_since is None:
            self._no_hud_since = timestamp
        return timestamp - self._no_hud_since >= 0.35

    @staticmethod
    def combat_hud_visible(frame, anchor_text: str = "") -> bool:
        import cv2

        height, width = frame.shape[:2]
        left = frame[int(height * 0.72):int(height * 0.98), :int(width * 0.23)]
        right = frame[int(height * 0.72):int(height * 0.98), int(width * 0.77):]
        samples = (left, right)
        bright_ratio = 0.0
        saturated_ratio = 0.0
        edge_ratio = 0.0
        for sample in samples:
            hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
            bright_ratio = max(bright_ratio, float((hsv[:, :, 2] > 175).mean()))
            saturated_ratio = max(saturated_ratio, float((hsv[:, :, 1] > 65).mean()))
            edges = cv2.Canny(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY), 70, 150)
            edge_ratio = max(edge_ratio, float((edges > 0).mean()))
        visual_hud = bright_ratio > 0.015 or saturated_ratio > 0.035 or edge_ratio > 0.045
        normalized = anchor_text.casefold().replace(" ", "")
        has_hp_shape = bool(re.search(r"\d{1,7}/\d{1,7}", normalized))
        shortcut_count = sum(key in normalized for key in ("q", "e", "r", "t"))
        return visual_hud or (has_hp_shape and shortcut_count >= 2)


class LoadingScreenDetector:
    """Detect static dark loading screens without invoking central damage OCR."""

    def __init__(self) -> None:
        self._previous_sample = None
        self._static_since: float | None = None

    def reset(self) -> None:
        self._previous_sample = None
        self._static_since = None

    def is_loading(self, frame, timestamp: float) -> bool:
        import cv2

        height, width = frame.shape[:2]
        scene = frame[int(height * 0.18):int(height * 0.82), int(width * 0.12):int(width * 0.88)]
        gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
        mean_value = float(gray.mean())
        saturation = float(hsv[:, :, 1].mean())
        candidate = mean_value < 105.0 and saturation < 105.0
        if not candidate:
            self.reset()
            return False
        sample = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
        if self._previous_sample is not None:
            delta = float(cv2.absdiff(sample, self._previous_sample).mean())
            if delta < 1.2:
                if self._static_since is None:
                    self._static_since = timestamp
                self._previous_sample = sample
                return timestamp - self._static_since >= 0.6
        self._static_since = timestamp
        self._previous_sample = sample
        return False


class DpsPlotWidget(pg.PlotWidget):
    timestampClicked = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        axis_items = {
            "bottom": TimelineAxis(orientation="bottom"),
            "left": NumericAxis(orientation="left"),
            "right": NumericAxis(orientation="right"),
        }
        super().__init__(axisItems=axis_items, parent=parent)
        scene = cast(pg.GraphicsScene, self.scene())
        scene.sigMouseClicked.connect(self._on_scene_clicked)

    def _on_scene_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        plot_item = _plot_item(self)
        view_box = cast(pg.ViewBox, plot_item.vb)
        if not view_box.sceneBoundingRect().contains(event.scenePos()):
            return
        point = view_box.mapSceneToView(event.scenePos())
        if point.x() >= 0:
            self.timestampClicked.emit(float(point.x()))


def _plot_item(widget: pg.PlotWidget) -> pg.PlotItem:
    plot_item = widget.getPlotItem()
    if plot_item is None:
        raise RuntimeError("PlotWidget did not create its PlotItem")
    return cast(pg.PlotItem, plot_item)


def _plot_view_box(plot_item: pg.PlotItem) -> pg.ViewBox:
    view_box = plot_item.vb
    if not isinstance(view_box, pg.ViewBox):
        raise RuntimeError("PlotItem did not create its ViewBox")
    return view_box


class NumericAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f"{value:,.0f}" for value in values]


class TimelineAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        labels = []
        for value in values:
            total = max(0, int(value))
            labels.append(f"{total // 60}:{total % 60:02d}")
        return labels


class CvDamageAnalysisWorker(QObject):
    progress = Signal(int)
    finished = Signal(object, float)
    failed = Signal(str)

    def __init__(self, video_path: str, skip_seconds: float, block_seconds: float) -> None:
        super().__init__()
        self.video_path = video_path
        self.skip_seconds = max(0.0, skip_seconds)
        self.block_seconds = max(1.0, block_seconds)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import cv2

        capture = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self.failed.emit("Não foi possível abrir o vídeo para análise OpenCV")
            return
        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = frame_count / fps if frame_count else 0.0
            capture.set(cv2.CAP_PROP_POS_MSEC, self.skip_seconds * 1000.0)
            buckets: defaultdict[int, float] = defaultdict(float)
            recent_detections: dict[tuple[int, int, int], tuple[float, float]] = {}
            frame_index = int(self.skip_seconds * fps)
            last_progress = -1
            while not self._cancelled:
                success, frame = capture.read()
                if not success:
                    break
                timestamp = frame_index / fps
                for value, center_x, center_y in self._detect_damage_events(frame):
                    signature = (center_x // 50, center_y // 30, value // 100)
                    previous = recent_detections.get(signature)
                    if previous and timestamp - previous[0] < 0.35:
                        continue
                    recent_detections[signature] = (timestamp, value)
                    buckets[int(timestamp // self.block_seconds)] += value
                frame_index += 1
                if frame_count:
                    progress = int(min(100, frame_index / frame_count * 100))
                    if progress != last_progress:
                        self.progress.emit(progress)
                        last_progress = progress
            if self._cancelled:
                self.finished.emit([], duration)
                return
            end_time = max(duration, self.skip_seconds)
            block_count = max(1, math.ceil(max(0.0, end_time - self.skip_seconds) / self.block_seconds))
            results = []
            accumulated = 0.0
            for index in range(block_count):
                damage = buckets.get(index + int(self.skip_seconds // self.block_seconds), 0.0)
                accumulated += damage
                timestamp = self.skip_seconds + (index + 1) * self.block_seconds
                results.append((min(timestamp, end_time), damage / self.block_seconds, accumulated))
            self.finished.emit(results, end_time)
        except (OSError, RuntimeError, ValueError) as error:
            self.failed.emit(f"Falha durante análise OpenCV: {error}")
        finally:
            capture.release()

    @staticmethod
    def _detect_damage_events(frame) -> list[tuple[int, int, int]]:
        import cv2

        height, width = frame.shape[:2]
        crop = frame[int(height * 0.05):int(height * 0.65), int(width * 0.10):int(width * 0.90)]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        bright_text = cv2.inRange(hsv, (0, 0, 180), (180, 125, 255))
        warm_text = cv2.inRange(hsv, (5, 65, 130), (45, 255, 255))
        mask = cv2.bitwise_or(bright_text, warm_text)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        components = []
        for contour in contours:
            x, y, item_width, item_height = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if area < 8 or item_width < 2 or item_height < 7:
                continue
            if item_width > 100 or item_height > 80 or item_width / max(1, item_height) > 4:
                continue
            components.append((x, y, item_width, item_height, area))
        try:
            from src.wuwa_calculator.native import group_damage_components
        except ImportError:
            group_damage_components = None
        if group_damage_components is not None:
            return group_damage_components(components, width, height)

        components.sort(key=lambda item: (item[1], item[0]))
        groups: list[list[tuple[int, int, int, int, float]]] = []
        for component in components:
            x, y, item_width, item_height, _area = component
            center_y = y + item_height / 2
            if groups:
                group = groups[-1]
                group_center_y = sum(item[1] + item[3] / 2 for item in group) / len(group)
                group_right = max(item[0] + item[2] for item in group)
                if abs(center_y - group_center_y) <= max(12, item_height * 0.7) and x <= group_right + 28:
                    group.append(component)
                    continue
            groups.append([component])
        events = []
        for group in groups:
            left = min(item[0] for item in group)
            right = max(item[0] + item[2] for item in group)
            top = min(item[1] for item in group)
            bottom = max(item[1] + item[3] for item in group)
            group_width = right - left
            group_height = bottom - top
            if len(group) < 2 and group_width < 16:
                continue
            filled_area = sum(item[4] for item in group)
            density = min(1.0, filled_area / max(1, group_width * group_height))
            estimated_damage = int(min(9_999_999_999, max(100, group_width * group_height * (1.0 + density))))
            events.append((estimated_damage, int(width * 0.10 + (left + right) / 2), int(height * 0.05 + (top + bottom) / 2)))
        return events


class LiveDamageAnalysisWorker(QObject):
    damage_detected = Signal(dict)
    analysis_completed = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        video_path: str,
        skip_seconds: float,
        end_seconds: float = 0.0,
        start_time: float | None = None,
    ) -> None:
        super().__init__()
        self.video_path = video_path
        self.skip_seconds = max(0.0, skip_seconds)
        self.end_seconds = max(0.0, end_seconds)
        self.start_time = max(0.0, start_time if start_time is not None else skip_seconds)
        self._cancelled = False
        self._position_lock = Lock()
        self._target_seconds = self.start_time
        self._frame_processing = False
        self._idle_interval = 0.22
        self._active_interval = 1.0 / OCR_SAMPLE_FPS
        self.no_damage_timeout = INACTIVITY_TIMEOUT

    def update_position(self, seconds: float) -> None:
        with self._position_lock:
            if self._frame_processing:
                return
            # Mailbox de um único frame: posições intermediárias são descartadas.
            self._target_seconds = max(0.0, float(seconds))

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "1")
        os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "1")
        import cv2
        from rapidocr_onnxruntime import RapidOCR

        capture = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        last_hit_time = self.start_time
        completion_reason = "video_end"
        try:
            if not capture.isOpened():
                self.failed.emit("Não foi possível abrir o vídeo para análise ao vivo")
                return
            cv2.setNumThreads(1)
            ocr = RapidOCR()
            fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = frame_count / fps if frame_count else 0.0
            capture.set(cv2.CAP_PROP_POS_MSEC, self.start_time * 1000.0)
            initial_success, _initial_frame = capture.read()
            if not initial_success:
                self.failed.emit("Não foi possível posicionar o vídeo no início da análise")
                return
            detection_tracker = DamageDetectionTracker()
            frame_gate = CombatFrameGate()
            warmup_observations: set[tuple[int, int, int]] = set()
            warmup_started: float | None = None
            learned_profile: tuple[float, float, float] | None = None
            combat_confirmed = False
            last_position = -1.0
            accumulated = 0.0
            last_detection_time = -1.0
            # O timeout ignora todo o vídeo anterior ao início efetivo da análise.
            no_damage_timer = 0.0
            while not self._cancelled:
                with self._position_lock:
                    target = self._target_seconds
                startup_window = self.start_time <= target < self.start_time + 2.0
                interval = 0.0 if startup_window else (
                    self._active_interval
                    if last_detection_time >= 0 and target - last_detection_time < 1.5
                    else self._idle_interval
                )
                if target < self.skip_seconds or abs(target - last_position) < interval:
                    QThread.msleep(45)
                    continue
                if duration:
                    target = min(target, duration)
                no_damage_timer = max(0.0, target - last_hit_time) if last_hit_time >= 0 else 0.0
                if self.end_seconds and target >= self.end_seconds:
                    completion_reason = "manual_limit"
                    break
                analysis_elapsed = max(0.0, target - self.start_time)
                if (
                    not self.end_seconds
                    and analysis_elapsed >= MIN_INACTIVITY_ANALYSIS_SECONDS
                    and no_damage_timer >= self.no_damage_timeout
                ):
                    completion_reason = "inactivity"
                    break
                capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
                success, frame = capture.read()
                if not success:
                    QThread.msleep(70)
                    continue
                if not self._is_game_screen(frame) or not frame_gate.allow(frame, target):
                    last_position = target
                    QThread.msleep(45)
                    continue
                with self._position_lock:
                    self._frame_processing = True
                try:
                    values = self._read_values(frame, ocr)
                finally:
                    with self._position_lock:
                        self._frame_processing = False
                if not values:
                    last_position = target
                    QThread.msleep(45)
                    continue
                detection_tracker.expire(target)
                fresh_values = []
                for value, center_x, center_y, item_width, item_height, color_score, _confidence in values:
                    if combat_confirmed and learned_profile is not None:
                        learned_width, learned_height, learned_color = learned_profile
                        size_match = (
                            learned_width * 0.45 <= item_width <= learned_width * 2.2
                            and learned_height * 0.45 <= item_height <= learned_height * 2.2
                        )
                        if not size_match or color_score < learned_color * 0.35:
                            continue
                    if not detection_tracker.accept(
                        center_x, center_y, item_width, item_height, target
                    ):
                        continue
                    fresh_values.append(value)
                    if not combat_confirmed:
                        warmup_observations.add((value, center_x // 50, center_y // 30))
                        warmup_started = target if warmup_started is None else warmup_started
                if not combat_confirmed:
                    if len(warmup_observations) < 2 or warmup_started is None or target - warmup_started < 0.25:
                        last_position = target
                        QThread.msleep(45)
                        continue
                    combat_confirmed = True
                    learned_values = [item for item in values if (item[0], item[1] // 50, item[2] // 30) in warmup_observations]
                    if learned_values:
                        learned_profile = (
                            sum(item[3] for item in learned_values) / len(learned_values),
                            sum(item[4] for item in learned_values) / len(learned_values),
                            sum(item[5] for item in learned_values) / len(learned_values),
                        )
                damage = float(sum(fresh_values))
                accumulated += damage
                if fresh_values:
                    last_detection_time = target
                    last_hit_time = target
                    no_damage_timer = 0.0
                self.damage_detected.emit({
                    "timestamp": target,
                    "damage": damage,
                    "hits": len(fresh_values),
                    "peak": max(fresh_values, default=0),
                    "accumulated": accumulated,
                })
                last_position = target
                QThread.msleep(45)
        except (OSError, RuntimeError, ValueError) as error:
            self.failed.emit(f"Falha durante análise ao vivo: {error}")
        finally:
            capture.release()
            if not self._cancelled:
                self.analysis_completed.emit({
                    "reason": completion_reason,
                    "last_hit": last_hit_time,
                })
            self.finished.emit()

    @staticmethod
    def _is_game_screen(frame) -> bool:
        import cv2

        height, width = frame.shape[:2]
        roi_top, roi_bottom, roi_left, roi_right = LiveDamageAnalysisWorker._combat_roi(width, height)
        scene = frame[roi_top:roi_bottom, roi_left:roi_right]
        hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
        mean_value = float(hsv[:, :, 2].mean())
        saturated_ratio = float((hsv[:, :, 1] > 55).mean())
        bright_ratio = float((hsv[:, :, 2] > 180).mean())
        return mean_value < 232.0 and (saturated_ratio > 0.04 or bright_ratio > 0.015)

    @staticmethod
    def _combat_roi(width: int, height: int) -> tuple[int, int, int, int]:
        top, bottom, left, right = COMBAT_ROI
        return (
            int(height * top),
            int(height * bottom),
            int(width * left),
            int(width * right),
        )

    @staticmethod
    def _read_values(frame, ocr: Any) -> list[tuple[int, int, int, int, int, float, float]]:
        import cv2

        height, width = frame.shape[:2]
        roi_top, roi_bottom, roi_left, roi_right = LiveDamageAnalysisWorker._combat_roi(width, height)
        crop = frame[roi_top:roi_bottom, roi_left:roi_right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        white_mask = cv2.inRange(hsv, (0, 0, 190), (180, 85, 255))
        color_masks = (
            cv2.inRange(hsv, (18, 80, 130), (42, 255, 255)),
            cv2.inRange(hsv, (0, 80, 130), (14, 255, 255)),
            cv2.inRange(hsv, (160, 80, 130), (180, 255, 255)),
            cv2.inRange(hsv, (125, 70, 110), (165, 255, 255)),
            cv2.inRange(hsv, (80, 70, 120), (110, 255, 255)),
            cv2.inRange(hsv, (35, 70, 110), (85, 255, 255)),
        )
        candidate_mask = white_mask
        for color_mask in color_masks:
            candidate_mask = cv2.bitwise_or(candidate_mask, color_mask)
        candidate_mask = cv2.morphologyEx(
            candidate_mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )
        contours, _ = cv2.findContours(candidate_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not any(cv2.contourArea(contour) >= 12 for contour in contours):
            return []
        enlarged = cv2.resize(crop, None, fx=1.15, fy=1.15, interpolation=cv2.INTER_LINEAR)
        result, _ = ocr(enlarged)
        values = []
        for item in result or []:
            if len(item) < 3:
                continue
            box, text, confidence = item
            raw_text = str(text).strip()
            digits = re.sub(r"[^0-9]", "", raw_text)
            if not digits or len(digits) > 8:
                continue
            ocr_confidence = float(confidence)
            if ocr_confidence < 0.55:
                continue
            value = int(digits)
            if value < 5 or value > MAX_DAMAGE_VALUE:
                continue
            points = [(point[0] / 1.15, point[1] / 1.15) for point in box]
            left = max(0, int(min(point[0] for point in points)))
            top = max(0, int(min(point[1] for point in points)))
            right = min(crop.shape[1], int(max(point[0] for point in points)) + 1)
            bottom = min(crop.shape[0], int(max(point[1] for point in points)) + 1)
            patch = crop[top:bottom, left:right]
            if patch.size == 0:
                continue
            patch_hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            bright_ratio = float((patch_hsv[:, :, 2] > 190).mean())
            color_ratio = float(((patch_hsv[:, :, 1] > 70) & (patch_hsv[:, :, 2] > 120)).mean())
            surrounding = crop[max(0, top - 8):min(crop.shape[0], bottom + 8), max(0, left - 8):min(crop.shape[1], right + 8)]
            surrounding_hsv = cv2.cvtColor(surrounding, cv2.COLOR_BGR2HSV)
            surrounding_value = float(surrounding_hsv[:, :, 2].mean())
            surrounding_saturation = float((surrounding_hsv[:, :, 1] > 45).mean())
            if surrounding_value > 238 and color_ratio < 0.08:
                continue
            if surrounding_saturation < 0.02 and bright_ratio < 0.35:
                continue
            color_score = max(color_ratio, bright_ratio * 0.35)
            if color_score < 0.10:
                continue
            candidate_confidence = min(
                1.0,
                ocr_confidence * 0.55
                + min(1.0, color_score / 0.35) * 0.30
                + min(1.0, bright_ratio) * 0.15,
            )
            center_x = int(sum(point[0] for point in points) / len(points) + roi_left)
            center_y = int(sum(point[1] for point in points) / len(points) + roi_top)
            values.append((
                value,
                center_x,
                center_y,
                max(1, right - left),
                max(1, bottom - top),
                color_score,
                candidate_confidence,
            ))
        return values


class WorkerCapturaNativa(QObject):
    damage_detected = Signal(dict)
    game_detected = Signal(str)
    frame_preview_signal = Signal(QImage)
    frame_preview_frame_signal = Signal(object)
    frame_processamento_signal = Signal(object)
    capture_status = Signal(str)
    status_signal = Signal(str)
    combat_state_changed = Signal(str)
    battle_restarted = Signal()
    map_detected = Signal(str)
    analysis_completed = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        start_time: float = 0.0,
        end_seconds: float = 0.0,
        capture_mode: str = "WUTHERING_WAVES",
        capture_settings: CaptureSettings | None = None,
    ) -> None:
        super().__init__()
        self.start_time = max(0.0, float(start_time))
        self.end_seconds = max(0.0, float(end_seconds))
        self.capture_mode = capture_mode
        self.capture_settings = capture_settings or CaptureSettings()
        self._frame_processor = FrameProcessor(self.capture_settings)
        self._cancelled = False
        self._capture_elapsed = QElapsedTimer()
        self._detection_tracker = DamageDetectionTracker()
        self._damage_events = DamageEventTracker()
        self._learning_store = LearningStore()
        self._learning_profile = self._learning_store.profile(capture_mode)
        self._frame_gate = CombatFrameGate()
        self._interface_detector = InterfaceMenuDetector()
        self._loading_detector = LoadingScreenDetector()
        self._combat_state = CombatStateMachine()
        self._accumulated = 0.0
        self._last_hit_time = self.start_time
        self._wgc_control = None
        self._wgc_hwnd: int | None = None
        self._wgc_disabled_hwnd: int | None = None
        self._wgc_frame = None
        self._wgc_lock = Lock()
        self._last_wgc_copy_at = 0.0
        self._wgc_client_crop: tuple[float, float, float, float] | None = None
        self._linux_capture = None
        self._linux_monitor = None
        self._preview_fps = DEFAULT_PREVIEW_FPS
        self._last_preview_at = 0.0
        self._preview_signal_lock = Lock()
        self._preview_signal_pending = False
        self._window_guard = GameWindowGuard()
        self.hwnd_jogo: int | None = None
        self._last_map_read_at = -4.0
        self._last_anchor_read_at = -1.0
        self._last_anchor_text = ""
        self._last_capture_status = ""
        self._last_logged_hwnd: int | None = None
        self._last_vision_at = 0.0
        self._capture_log_started_at = 0.0
        self._capture_log_frame_count = 0
        self._capture_log_last_frame_count = 0
        self._capture_log_changed_count = 0
        self._capture_log_last_changed_count = 0
        self._capture_log_last_focus: bool | None = None
        self._capture_log_first_frame = True
        self._wgc_log_started_at = 0.0
        self._wgc_log_frame_count = 0
        self._wgc_log_changed_count = 0
        self._wgc_log_last_sample = None

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "1")
        os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "1")
        try:
            import cv2
            from rapidocr_onnxruntime import RapidOCR
            cv2.setNumThreads(1)

            if sys.platform != "win32":
                try:
                    import mss
                    self._linux_capture = mss.mss()
                    self._linux_monitor = self._linux_capture.monitors[1]
                    self._set_capture_status(
                        "Captura Linux ativa pelo monitor primário (mss)"
                    )
                except Exception as error:
                    self._set_capture_status(f"Captura Linux indisponível: {error}")
                    return
            self._capture_elapsed.start()
            if sys.platform == "win32":
                self._set_capture_status("Captura nativa isolada por HWND")
            ocr = RapidOCR()
            while not self._cancelled:
                if sys.platform == "win32":
                    located = self._locate_target_window()
                    if located is None:
                        status = (
                            "Aguardando Wuthering Waves..."
                            if self.capture_mode == "WUTHERING_WAVES"
                            else "Aguardando janela de jogo em foco..."
                        )
                        self._set_capture_status(status)
                        QThread.msleep(500)
                        continue
                    hwnd, _bounds = located
                    self.hwnd_jogo = hwnd
                    self._preview_fps = self._refresh_rate_for_hwnd(hwnd)
                    if self._last_logged_hwnd != int(hwnd):
                        self._last_logged_hwnd = int(hwnd)
                        window_title = self._window_title(hwnd)
                        self.game_detected.emit(self._display_game_name(window_title))
                        self._debug_log(
                            f"HWND selecionado: {int(hwnd)}; "
                            f"título: {window_title!r}; "
                            f"refresh: {self._preview_fps:.0f} Hz"
                        )
                    if self._window_guard.is_minimized(hwnd):
                        self._set_capture_status("Janela do jogo minimizada; captura pausada")
                        QThread.msleep(200)
                        continue
                    self._ensure_windows_graphics_capture(hwnd)
                try:
                    frame = self._read_capture_frame()
                except (OSError, RuntimeError, ValueError, AttributeError) as error:
                    self._set_capture_status(f"Falha temporária na captura: {error}")
                    QThread.msleep(200)
                    continue
                if frame is None:
                    QThread.msleep(16)
                    continue
                frame = self._frame_processor.process(frame)
                if frame is None:
                    continue
                now = time.monotonic()
                self._capture_log_frame_count += 1
                if self._capture_log_first_frame:
                    self._capture_log_first_frame = False
                    self._capture_log_started_at = now
                    self._debug_log(
                        f"Primeiro frame nativo: {frame.shape[1]}x{frame.shape[0]}"
                    )
                elif now - self._capture_log_started_at >= 5.0:
                    elapsed = now - self._capture_log_started_at
                    frames = self._capture_log_frame_count - self._capture_log_last_frame_count
                    self._capture_log_last_frame_count = self._capture_log_frame_count
                    self._capture_log_started_at = now
                    self._debug_log(f"FPS processamento nativo: {frames / elapsed:.1f}")
                timestamp = self.start_time + self._capture_elapsed.elapsed() / 1000.0
                if self.end_seconds and timestamp >= self.end_seconds:
                    break
                if frame is not None and hasattr(frame, "shape") and len(frame.shape) >= 2:
                    if now - self._last_vision_at < 1.0 / OCR_SAMPLE_FPS:
                        QThread.msleep(1)
                        continue
                    self._last_vision_at = now
                    self.frame_processamento_signal.emit(frame)
                    completion, pre_combat, reward_screen, login, loading, anchor_text = (
                        False,
                        False,
                        False,
                        False,
                        False,
                        "",
                    )
                    if timestamp - self._last_anchor_read_at >= 1.0:
                        (
                            completion,
                            pre_combat,
                            reward_screen,
                            login,
                            loading,
                            anchor_text,
                        ) = self._read_ui_anchors(frame, ocr)
                        self._last_anchor_read_at = timestamp
                        self._last_anchor_text = anchor_text
                    else:
                        anchor_text = self._last_anchor_text
                    if completion:
                        self._damage_events.reset()
                        _state, state_changed = self._combat_state.set_finished()
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        QThread.msleep(40)
                        continue
                    if login:
                        self._damage_events.reset()
                        _state, state_changed = self._combat_state.set_outside_game()
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        QThread.msleep(40)
                        continue
                    if loading or self._loading_detector.is_loading(frame, timestamp):
                        self._damage_events.reset()
                        _state, state_changed = self._combat_state.set_loading()
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        QThread.msleep(40)
                        continue
                    if pre_combat:
                        self._damage_events.reset()
                        _state, state_changed = self._combat_state.set_pre_combat()
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        QThread.msleep(40)
                        continue
                    if reward_screen:
                        self._damage_events.reset()
                        _state, state_changed = self._combat_state.set_reward_screen()
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        QThread.msleep(40)
                        continue
                    if timestamp - self._last_map_read_at >= 4.0:
                        map_name = self._read_map_name(frame, ocr)
                        self._last_map_read_at = timestamp
                        if map_name:
                            self.map_detected.emit(map_name)
                    if not self._frame_gate.allow(frame, timestamp):
                        self._update_combat_state(timestamp, False)
                        QThread.msleep(40)
                        continue
                    values = [
                        value
                        for value in LiveDamageAnalysisWorker._read_values(frame, ocr)
                        if self._learning_profile.accepts(value[3], value[4], value[5])
                    ]
                    damage_events = self._damage_events.update(values, timestamp)
                    hud_ready = self._interface_detector.combat_hud_visible(frame, anchor_text)
                    menu_open = self._interface_detector.is_menu(frame, timestamp) and not hud_ready
                    _state, state_changed = self._combat_state.set_interface_open(menu_open)
                    if state_changed:
                        self.combat_state_changed.emit(_state)
                    if menu_open:
                        self._damage_events.reset()
                        QThread.msleep(40)
                        continue
                    if self._combat_state.state in {LOGIN, CARREGANDO}:
                        _state, state_changed = self._combat_state.resume_from_loading(hud_ready)
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                        if not hud_ready:
                            QThread.msleep(40)
                            continue
                    if self._combat_state.state in {PRE_COMBATE, FIM_DE_COMBATE}:
                        if not hud_ready:
                            QThread.msleep(40)
                            continue
                        _state, state_changed = self._combat_state.set_interface_open(False)
                        if state_changed:
                            self.combat_state_changed.emit(_state)
                    if hud_ready and self._combat_state.state == TELA_DE_RECOMPENSA:
                        _state, restarted = self._combat_state.resume_new_battle()
                        if restarted:
                            self.combat_state_changed.emit(_state)
                            self.battle_restarted.emit()
                    if not hud_ready:
                        if damage_events:
                            self._emit_damage_events(damage_events, timestamp)
                        else:
                            self._update_combat_state(timestamp, False)
                        QThread.msleep(40)
                        continue
                    if not damage_events:
                        self._update_combat_state(timestamp, False)
                        QThread.msleep(40)
                        continue
                    self._emit_damage_events(damage_events, timestamp)
                QThread.msleep(1)
        except Exception as error:
            self.failed.emit(f"Falha durante captura em tempo real: {error}")
        finally:
            if self._wgc_control is not None:
                try:
                    self._wgc_control.stop()
                    self._wgc_control.wait()
                except Exception:
                    pass
                self._wgc_control = None
            if self._linux_capture is not None:
                self._linux_capture.close()
                self._linux_capture = None
            self._learning_store.save()
            self.analysis_completed.emit({
                "reason": "live_capture",
                "last_hit": self._last_hit_time,
            })
            self.finished.emit()

    def _emit_damage_events(self, events, timestamp: float) -> None:
        self._learning_profile.observe(events)
        fresh_values = [event[0] for event in events]
        self._update_combat_state(timestamp, True)
        damage = float(sum(fresh_values))
        self._accumulated += damage
        self._last_hit_time = timestamp
        self.damage_detected.emit({
            "timestamp": timestamp,
            "damage": damage,
            "hits": len(fresh_values),
            "peak": max(fresh_values, default=0),
            "accumulated": self._accumulated,
            "combat_state": self._combat_state.state,
            "combat_elapsed": self._combat_state.active_seconds(timestamp),
            "confidence": min(event[6] for event in events),
        })

    def _locate_target_window(self):
        from src.wuwa_calculator.app.capture.window_utils import obter_hwnd_jogo

        detected_hwnd = obter_hwnd_jogo(self.capture_mode)
        if detected_hwnd is not None:
            for hwnd, _title, _window_class, bounds in self._window_guard.list_active_windows():
                if int(hwnd) == int(detected_hwnd):
                    return hwnd, bounds

        if self.capture_mode == "GENERIC_WINDOW":
            league_window = self._window_guard.locate_league_window()
            return league_window or self._locate_foreground_window()
        return self._window_guard.locate_wuthering_window()

    def _locate_foreground_window(self):
        if sys.platform != "win32":
            return None
        windows = self._window_guard.list_active_windows()
        if not windows:
            return None
        foreground = self._window_guard._foreground_window()
        if foreground is not None:
            for hwnd, title, window_class, bounds in windows:
                if int(hwnd) == int(foreground):
                    if self._window_guard._is_game_window(title, window_class):
                        return hwnd, bounds
                    break

        for hwnd, title, window_class, bounds in windows:
            if self._window_guard._is_game_window(title, window_class):
                return hwnd, bounds

        return None

    def _wait_for_game_window(self):
        while not self._cancelled:
            located = self._locate_target_window()
            if located is not None and not self._window_guard.is_minimized(located[0]):
                return located
            if self.capture_mode == "GENERIC_WINDOW":
                self._set_capture_status("Aguardando qualquer jogo em foco...")
            else:
                self._set_capture_status("Aguardando Wuthering Waves...")
            time.sleep(1.0)
        return None

    def _crop_game_frame(self, frame, region):
        if region is None or len(frame.shape) < 2:
            return None
        left, top, right, bottom = region
        height, width = frame.shape[:2]
        left = max(0, min(left, width - 1))
        top = max(0, min(top, height - 1))
        right = max(left + 1, min(right, width))
        bottom = max(top + 1, min(bottom, height))
        return frame[top:bottom, left:right]

    def _debug_log(self, message: str) -> None:
        mode = self.capture_mode.casefold()
        print(f"[DEBUG_CAPTURE][{mode}] {message}", flush=True)

    def _set_capture_status(self, status: str) -> None:
        if status != self._last_capture_status:
            self._last_capture_status = status
            self.capture_status.emit(status)
            self.status_signal.emit(status)
            self._debug_log(status)

    def _window_title(self, hwnd: int) -> str:
        if sys.platform != "win32":
            return ""
        import ctypes

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(int(hwnd))
        title = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(int(hwnd), title, len(title))
        return title.value

    @staticmethod
    def _display_game_name(window_title: str) -> str:
        normalized = window_title.casefold().replace("™", "")
        known_games = (
            ("league of legends", "League of Legends"),
            ("wuthering waves", "Wuthering Waves"),
            ("honkai: star rail", "Honkai: Star Rail"),
            ("honkai star rail", "Honkai: Star Rail"),
            ("genshin impact", "Genshin Impact"),
            ("zenless zone zero", "Zenless Zone Zero"),
            ("valorant", "VALORANT"),
            ("minecraft", "Minecraft"),
        )
        for marker, display_name in known_games:
            if marker in normalized:
                return display_name
        return window_title.strip() or "Jogo detectado"

    @staticmethod
    def _preview_image(frame) -> QImage:
        import cv2

        if len(frame.shape) == 2:
            rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        return QImage(
            rgb.data,
            width,
            height,
            int(rgb.strides[0]),
            QImage.Format.Format_RGB888,
        ).copy()

    @staticmethod
    def _preview_image_rgb(rgb) -> QImage:
        height, width = rgb.shape[:2]
        return QImage(
            rgb.data,
            width,
            height,
            int(rgb.strides[0]),
            QImage.Format.Format_RGB888,
        ).copy()

    def _update_combat_state(self, timestamp: float, has_damage: bool) -> None:
        state, changed = self._combat_state.update(timestamp, has_damage)
        if changed:
            self.combat_state_changed.emit(state)

    @staticmethod
    def _read_map_name(frame, ocr: Any) -> str:
        import cv2

        height, width = frame.shape[:2]
        top, bottom, left, right = MAP_ROI
        crop = frame[
            int(height * top):int(height * bottom),
            int(width * left):int(width * right),
        ]
        if crop.size == 0 or float(crop.mean()) < 18.0:
            return ""
        enlarged = cv2.resize(crop, None, fx=1.25, fy=1.25, interpolation=cv2.INTER_LINEAR)
        result, _ = ocr(enlarged)
        fragments = []
        for item in result or []:
            if len(item) < 3 or float(item[2]) < 0.60:
                continue
            text = re.sub(r"[^\wÀ-ÿ' -]", "", str(item[1])).strip()
            if len(text) >= 3 and any(character.isalpha() for character in text):
                normalized = text.upper()
                if any(term in normalized for term in PALAVRAS_IGNORADAS):
                    return ""
                fragments.append(text)
        return " ".join(fragments[:3]).strip()

    @staticmethod
    def _read_ui_anchors(frame, ocr: Any) -> tuple[bool, bool, bool, bool, bool, str]:
        import cv2

        height, width = frame.shape[:2]
        crop = frame[int(height * 0.02):int(height * 0.98), int(width * 0.03):int(width * 0.97)]
        if crop.size == 0:
            return False, False, False, False, False, ""
        enlarged = cv2.resize(crop, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
        result, _ = ocr(enlarged)
        texts = []
        for item in result or []:
            if len(item) < 3 or float(item[2]) < 0.60:
                continue
            text = str(item[1]).strip()
            if text:
                texts.append(text)
        combined = " ".join(texts)
        flags = classify_screen_text(combined)
        return (
            flags["completion"],
            flags["pre_combat"],
            flags["reward_screen"],
            flags["login"],
            flags["loading"],
            combined,
        )

    def mark_preview_consumed(self) -> None:
        with self._preview_signal_lock:
            self._preview_signal_pending = False

    @staticmethod
    def _refresh_rate_for_hwnd(hwnd: int) -> float:
        if sys.platform != "win32":
            return DEFAULT_PREVIEW_FPS
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        device_context = user32.GetDC(int(hwnd))
        if not device_context:
            return DEFAULT_PREVIEW_FPS
        try:
            refresh_rate = int(gdi32.GetDeviceCaps(device_context, 116))
        finally:
            user32.ReleaseDC(int(hwnd), device_context)
        if refresh_rate <= 0:
            return DEFAULT_PREVIEW_FPS
        return min(MAX_PREVIEW_FPS, max(1.0, float(refresh_rate)))

    def _ensure_windows_graphics_capture(self, hwnd: int) -> None:
        if self._wgc_hwnd == int(hwnd) and self._wgc_control is not None:
            return
        if self._wgc_disabled_hwnd == int(hwnd):
            return
        if self._wgc_control is not None:
            try:
                self._wgc_control.stop()
                self._wgc_control.wait()
            except Exception:
                pass
            self._wgc_control = None
        try:
            from windows_capture import WindowsCapture

            def on_frame_arrived(frame, _capture_control) -> None:
                try:
                    image = frame.frame_buffer
                    if image is None or image.size == 0:
                        return
                    now = time.monotonic()
                    with self._wgc_lock:
                        if now - self._last_wgc_copy_at < 1.0 / PREVIEW_OUTPUT_FPS:
                            return
                        self._last_wgc_copy_at = now
                    bgr = image[:, :, :3].copy()
                    bgr = self._crop_wgc_to_client_area(bgr, int(hwnd))
                    if bgr is None or bgr.size == 0:
                        return
                    with self._wgc_lock:
                        self._wgc_log_frame_count += 1
                        frames = self._wgc_log_frame_count
                        if self._wgc_log_started_at <= 0.0:
                            self._wgc_log_started_at = now
                        elapsed = now - self._wgc_log_started_at
                        should_log = elapsed >= 5.0
                        if should_log:
                            self._wgc_log_started_at = now
                            self._wgc_log_frame_count = 0
                    if should_log:
                        self._debug_log(f"FPS WGC recebido: {frames / elapsed:.1f}")
                    with self._wgc_lock:
                        self._wgc_frame = bgr
                    preview_fps = min(max(self._preview_fps, 1.0), PREVIEW_OUTPUT_FPS)
                    if now - self._last_preview_at >= 1.0 / preview_fps:
                        self._last_preview_at = now
                        with self._preview_signal_lock:
                            if not self._preview_signal_pending:
                                self._preview_signal_pending = True
                                self.frame_preview_frame_signal.emit(bgr)
                except Exception:
                    return

            def on_closed() -> None:
                return

            capture = WindowsCapture(
                cursor_capture=self.capture_settings.capture_cursor,
                draw_border=False,
                minimum_update_interval=0,
                dirty_region=False,
                window_hwnd=int(hwnd),
            )
            capture.event(on_frame_arrived)
            capture.event(on_closed)
            self._wgc_hwnd = int(hwnd)
            self._wgc_frame = None
            self._wgc_client_crop = None
            self._wgc_control = capture.start_free_threaded()
            self._set_capture_status("Captura WGC assíncrona isolada por HWND")
        except Exception as error:
            self._wgc_control = None
            self._wgc_hwnd = None
            self._wgc_disabled_hwnd = int(hwnd)
            self._set_capture_status(f"WGC indisponível: {error}")

    def _crop_wgc_to_client_area(self, frame, hwnd: int):
        """Remove title bar and borders from a WGC window frame."""
        if sys.platform != "win32":
            return frame
        try:
            import ctypes
            from ctypes import wintypes

            if self._wgc_client_crop is None:
                user32 = ctypes.windll.user32
                window_rect = wintypes.RECT()
                client_rect = wintypes.RECT()
                client_origin = wintypes.POINT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
                    return frame
                if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
                    return frame
                client_origin.x = client_rect.left
                client_origin.y = client_rect.top
                if not user32.ClientToScreen(hwnd, ctypes.byref(client_origin)):
                    return frame
                window_width = window_rect.right - window_rect.left
                window_height = window_rect.bottom - window_rect.top
                if window_width <= 0 or window_height <= 0:
                    return frame
                self._wgc_client_crop = (
                    (client_origin.x - window_rect.left) / window_width,
                    (client_origin.y - window_rect.top) / window_height,
                    (client_origin.x - window_rect.left + client_rect.right - client_rect.left) / window_width,
                    (client_origin.y - window_rect.top + client_rect.bottom - client_rect.top) / window_height,
                )
            left_ratio, top_ratio, right_ratio, bottom_ratio = self._wgc_client_crop
            height, width = frame.shape[:2]
            left = max(0, min(width - 1, round(width * left_ratio)))
            top = max(0, min(height - 1, round(height * top_ratio)))
            right = max(left + 1, min(width, round(width * right_ratio)))
            bottom = max(top + 1, min(height, round(height * bottom_ratio)))
            return frame[top:bottom, left:right]
        except (AttributeError, OSError, TypeError, ValueError):
            return frame

    def _read_capture_frame(self):
        if sys.platform != "win32":
            if self._linux_capture is None or self._linux_monitor is None:
                return None
            import cv2
            import numpy as np

            screenshot = np.asarray(self._linux_capture.grab(self._linux_monitor))
            return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        if self._wgc_control is not None:
            with self._wgc_lock:
                return self._wgc_frame
        return None


class DpsSimulationPanel(Card):
    shutdown_finished = Signal()

    def __init__(self, video_player: HistoryVideoPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.video_player = video_player
        self.capture_settings = CaptureSettings()
        self.modo_analise = "VIDEO"
        self._performance_mode = False
        self.duration_seconds = 163.0
        self._dps_start_time = 0.0
        self.live_thread: QThread | None = None
        self.live_worker: LiveDamageAnalysisWorker | WorkerCapturaNativa | None = None
        self._live_blocks: defaultdict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        self._total_hits = 0
        self._peak_hit = 0
        self._hit_times: list[float] = []
        self._observed_damage = 0.0
        self._observed_dps = 0.0
        self._combat_elapsed_seconds = 0.0
        self.has_real_data = False
        self._pending_position_ms = 0
        self._plot_dirty = False
        self._plot_update_timer = QTimer(self)
        self._plot_update_timer.setInterval(100)
        self._plot_update_timer.timeout.connect(self._flush_plot_update)
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(33)
        self._position_timer.timeout.connect(self._flush_position)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        panel_title = QLabel("Simulação de DPS x Tempo")
        panel_title.setObjectName("mediaSectionTitle")
        header.addWidget(panel_title)
        dps_key = QLabel("●  DPS real")
        dps_key.setObjectName("dpsLegend")
        damage_key = QLabel("●  Dano Acumulado")
        damage_key.setObjectName("damageLegend")
        hit_key = QLabel("●  Hit = novo número de dano")
        hit_key.setObjectName("hitLegend")
        header.addWidget(dps_key)
        header.addWidget(damage_key)
        header.addWidget(hit_key)

        for legend in (dps_key, damage_key, hit_key):
            legend.hide()
        self.analysis_status = QLabel("Aguardando números reais")
        self.analysis_status.setObjectName("dpsAnalysisStatus")
        header.addWidget(self.analysis_status)
        self.combat_state_label = QLabel(f"Estado: {FORA_DE_COMBATE}")
        self.combat_state_label.setObjectName("dpsCombatState")
        header.addWidget(self.combat_state_label)
        self.map_label = QLabel("Mapa Atual: --")
        self.map_label.setObjectName("dpsMapContext")
        header.addWidget(self.map_label)
        self.hit_label = QLabel("Hits: 0")
        self.hit_label.setObjectName("dpsCursorLabel")
        header.addWidget(self.hit_label)
        self.position_label = QLabel("Cursor: 0.00s")
        self.position_label.setObjectName("dpsCursorLabel")
        header.addWidget(self.position_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(10)
        self.damage_metric = self._metric(metrics, "Dano acumulado")
        self.hits_metric = self._metric(metrics, "Hits")
        self.dps_metric = self._metric(metrics, "DPS médio")
        self.peak_metric = self._metric(metrics, "Maior hit")
        layout.addLayout(metrics)
        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        form = QHBoxLayout()
        form.setSpacing(6)
        self.skip_intro_time = self._time_box()
        self.analysis_start_time = self._time_box()
        self.analysis_end_time = self._time_box()
        form.addWidget(QLabel("Ignorar vinheta"))
        form.addWidget(self.skip_intro_time)
        form.addWidget(QLabel("Início da análise"))
        form.addWidget(self.analysis_start_time)
        form.addWidget(QLabel("Fim da análise"))
        form.addWidget(self.analysis_end_time)
        form.addWidget(QLabel("Modo de Análise"))
        self.analysis_source = QComboBox()
        self.analysis_source.setObjectName("analysisSourceCombo")
        self.analysis_source.setMinimumWidth(210)
        self.analysis_source.addItems((
            "Vídeo Local (MP4)",
            "Ao Vivo (Captura nativa por HWND)",
            "Teste: qualquer jogo em foco (League of Legends™ Client)",
        ))
        self.analysis_source.currentIndexChanged.connect(self._on_analysis_source_changed)
        form.addWidget(self.analysis_source)
        self._analysis_interval_widgets: list[QWidget] = []
        for index in range(form.count()):
            item = form.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None and widget is not self.analysis_source:
                self._analysis_interval_widgets.append(widget)
        controls.addLayout(form)
        layout.addLayout(controls)

        self.plot = DpsPlotWidget(self)
        self.plot_item = _plot_item(self.plot)
        self.plot.setObjectName("dpsPlot")
        self.plot_item.hideButtons()
        self.plot.setBackground("#080B18")
        self.plot.setMinimumHeight(141)
        self.plot.setMaximumHeight(260)
        cast(QGraphicsLayout, self.plot_item.layout).setContentsMargins(2, 2, 2, 2)
        self.plot.setLabel("bottom", "")
        self.plot.setLabel("left", "")
        self.plot.showAxis("right")
        damage_axis = cast(pg.AxisItem, self.plot_item.getAxis("right"))
        damage_axis.setLabel("")
        damage_axis.setWidth(68)
        damage_axis.setPen(pg.mkPen("#6870A8"))
        damage_axis.setTextPen(pg.mkPen("#C7C8EA"))
        self.damage_view = pg.ViewBox()
        self.plot.scene().addItem(self.damage_view)
        damage_axis.linkToView(self.damage_view)
        plot_view = cast(pg.ViewBox, self.plot_item.vb)
        self.damage_view.setXLink(plot_view)
        plot_view.sigResized.connect(self._sync_damage_view)
        self.plot.showGrid(x=True, y=True, alpha=0.16)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot_item.setMenuEnabled(False)
        self.plot.setAntialiasing(False)
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.enableAutoRange(False)
        for axis_name in ("left", "bottom"):
            axis = cast(pg.AxisItem, self.plot_item.getAxis(axis_name))
            axis.setPen(pg.mkPen("#6870A8"))
            axis.setTextPen(pg.mkPen("#C7C8EA"))
        self.glow_curve = self.plot.plot([], [], pen=pg.mkPen((0, 217, 255, 70), width=7))
        self.curve = self.plot.plot([], [], pen=pg.mkPen("#00D9FF", width=2.5))
        self.damage_glow_curve = pg.PlotDataItem(pen=pg.mkPen((61, 196, 255, 65), width=6))
        self.damage_curve = pg.PlotDataItem(pen=pg.mkPen("#55D6FF", width=2))
        self.damage_view.addItem(self.damage_glow_curve)
        self.damage_view.addItem(self.damage_curve)
        self.damage_peaks = pg.ScatterPlotItem(
            size=10,
            symbol="t",
            brush=pg.mkBrush("#FFD76A"),
            pen=pg.mkPen("#FFF4B0", width=1),
        )
        self.damage_lows = pg.ScatterPlotItem(
            size=8,
            symbol="o",
            brush=pg.mkBrush("#55D6FF"),
            pen=pg.mkPen("#C7F5FF", width=1),
        )
        self.plot.addItem(self.damage_peaks)
        self.plot.addItem(self.damage_lows)
        self.cursor_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#67D9FF", width=2),
        )
        self.plot.addItem(self.cursor_line)
        self.cutoff_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#FFD76A", width=2, style=Qt.PenStyle.DashLine),
        )
        self.cutoff_line.hide()
        self.plot.addItem(self.cutoff_line)
        self.mini_plot = pg.PlotWidget(self)
        self.mini_plot_item = _plot_item(self.mini_plot)
        self.mini_plot.setObjectName("dpsMiniPlot")
        self.mini_plot_item.hideButtons()
        self.mini_plot.setBackground("#0B1023")
        self.mini_plot.setFixedHeight(14)
        self.mini_plot.hideAxis("left")
        self.mini_plot.hideAxis("bottom")
        self.mini_plot.setMouseEnabled(x=False, y=False)
        self.mini_plot_item.setMenuEnabled(False)
        self.mini_plot.setAntialiasing(False)
        self.mini_plot.setClipToView(True)
        self.mini_plot.setDownsampling(auto=True, mode="peak")
        self.mini_plot.enableAutoRange(False)
        self.mini_curve = self.mini_plot.plot([], [], pen=pg.mkPen((117, 75, 255, 120), width=2))
        self.mini_markers = pg.ScatterPlotItem(size=7, brush=pg.mkBrush("#B77CFF"), pen=pg.mkPen("#FFFFFF", width=1))
        self.mini_plot.addItem(self.mini_markers)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.mini_plot)

        self.plot.timestampClicked.connect(self._seek_video)
        self.video_player.media_player.positionChanged.connect(
            self._queue_position,
            Qt.ConnectionType.QueuedConnection,
        )
        self.video_player.media_player.durationChanged.connect(self._on_duration_changed)
        self.video_player.videoLoaded.connect(self._on_video_loaded)
        self.video_player.videoStopped.connect(self._on_video_stopped)
        self._set_analysis_source_ui(False)
        self._render_curve()

    @staticmethod
    def _metric(layout: QHBoxLayout, title: str) -> QLabel:
        label = QLabel(f"{title}: --")
        label.setObjectName("dpsMetric")
        layout.addWidget(label, 1)
        return label

    @staticmethod
    def _time_box() -> QTimeEdit:
        control = QTimeEdit(QTime(0, 0, 0))
        control.setDisplayFormat("mm:ss")
        control.setTimeRange(QTime(0, 0, 0), QTime(23, 59, 59))
        control.setKeyboardTracking(False)
        control.setFixedWidth(78)
        return control

    def _render_curve(self) -> None:
        self.glow_curve.setData([], [])
        self.curve.setData([], [])
        self.damage_glow_curve.setData([], [])
        self.damage_curve.setData([], [])
        self.damage_peaks.setData([], [])
        self.damage_lows.setData([], [])
        self.mini_curve.setData([], [])
        self.mini_markers.setData([], [])
        plot_view = _plot_view_box(self.plot_item)
        plot_view.setXRange(0, max(1.0, self.duration_seconds), padding=0.02)
        plot_view.setYRange(0, 1, padding=0)
        self.plot.showAxis("bottom", True)
        self.plot.showAxis("left", False)
        self.plot.showAxis("right", True)
        self.plot.setTitle("Aguardando dano real do vídeo...", color="#A8A8D5", size="11pt")
        self.damage_metric.setText("Dano acumulado: --")
        self.hits_metric.setText("Hits: 0")
        self.dps_metric.setText("DPS médio: --")
        self.peak_metric.setText("Maior hit: --")
        self.damage_view.setYRange(0, 100, 0)
        if self._dps_start_time >= 0:
            self._render_initial_analysis_point()

    def _render_initial_analysis_point(self) -> None:
        self._set_plot_data(
            [self._dps_start_time],
            [0.0],
            [0.0],
            [],
            x_duration=self._analysis_end_seconds() or self.duration_seconds,
        )

    def _sync_damage_view(self) -> None:
        plot_view = cast(pg.ViewBox, self.plot_item.vb)
        self.damage_view.setGeometry(plot_view.sceneBoundingRect())

    def _set_plot_data(
        self,
        times: list[float],
        values: list[float],
        accumulated: list[float],
        marker_times: list[float],
        x_duration: float | None = None,
    ) -> None:
        visible_duration = max(1.0, x_duration or self.duration_seconds)
        peak = max(values, default=1.0)
        total_damage = max(accumulated, default=0.0)
        scaled_accumulated = accumulated
        self.glow_curve.setData(times, values)
        self.curve.setData(times, values)
        self.damage_glow_curve.setData(times, scaled_accumulated)
        self.damage_curve.setData(times, scaled_accumulated)
        peak_points, low_points = self._extreme_points(times, values)
        self.damage_peaks.setData(
            x=[point[0] for point in peak_points],
            y=[point[1] for point in peak_points],
        )
        self.damage_lows.setData(
            x=[point[0] for point in low_points],
            y=[point[1] for point in low_points],
        )
        self.plot.showAxis("bottom", True)
        self.plot.showAxis("left", True)
        self.plot.showAxis("right", True)
        self.plot.setTitle("")
        self.plot.getAxis("left").setTicks(None)
        self.plot.getAxis("right").setTicks(None)
        plot_view = _plot_view_box(self.plot_item)
        plot_view.setXRange(0, visible_duration, padding=0.02)
        plot_view.setYRange(0, max(1.0, peak) * 1.12, padding=0)
        self.damage_view.setYRange(0, max(100.0, total_damage) * 1.12, 0)
        self._sync_damage_view()
        self.mini_curve.setData(times, values)
        visible_markers = [timestamp for timestamp in marker_times if timestamp <= visible_duration]
        self.mini_markers.setData(x=visible_markers, y=[max(1.0, peak) * 0.5] * len(visible_markers))
        mini_plot_view = _plot_view_box(self.mini_plot_item)
        mini_plot_view.setXRange(0, visible_duration, padding=0)
        mini_plot_view.setYRange(0, max(1.0, peak), padding=0)

    @staticmethod
    def _extreme_points(
        times: list[float], values: list[float]
    ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Find local damage peaks and meaningful low points for chart markers."""
        if len(values) < 3:
            return [], []
        peaks: list[tuple[float, float]] = []
        lows: list[tuple[float, float]] = []
        positive_values = [value for value in values if value > 0]
        floor = min(positive_values, default=0.0)
        for index in range(1, len(values) - 1):
            previous_value = values[index - 1]
            value = values[index]
            next_value = values[index + 1]
            if value <= 0:
                continue
            if value >= previous_value and value >= next_value and value > previous_value:
                peaks.append((times[index], value))
            if value <= previous_value and value <= next_value and value <= next_value and value <= floor * 1.15:
                lows.append((times[index], value))
        if not peaks:
            highest_index = max(range(len(values)), key=values.__getitem__)
            if values[highest_index] > 0:
                peaks.append((times[highest_index], values[highest_index]))
        return peaks, lows

    def _render_live_blocks(self) -> None:
        if not self._live_blocks:
            return
        block_seconds = ANALYSIS_BUCKET_SECONDS
        analysis_start = self._dps_start_time
        analysis_end = self._analysis_end_seconds()
        maximum_block = max(self._live_blocks)
        entries = [
            (index, self._live_blocks.get(index, [0.0, 0.0, 0.0]))
            for index in range(maximum_block + 1)
        ]
        times = [analysis_start]
        dps_values = [0.0]
        accumulated = [0.0]
        running_total = 0.0
        for _, values in entries:
            running_total += values[0]
            block_time = analysis_start + (len(times) - 0.5) * block_seconds
            if analysis_end:
                block_time = min(block_time, analysis_end)
            times.append(block_time)
            dps_values.append(values[0] / block_seconds)
            accumulated.append(running_total)
        self._set_plot_data(
            times,
            dps_values,
            accumulated,
            self._hit_times,
            x_duration=analysis_end or self.duration_seconds,
        )
        self._observed_damage = running_total
        last_observed_time = self._live_blocks[maximum_block][2]
        elapsed = max(0.0, min(last_observed_time, analysis_end or last_observed_time) - analysis_start)
        active_elapsed = self._combat_elapsed_seconds or elapsed
        self._observed_dps = self._observed_damage / max(0.1, active_elapsed)
        self.damage_metric.setText(f"Dano acumulado: {self._observed_damage:,.0f}")
        self.hits_metric.setText(f"Hits: {self._total_hits}")
        self.dps_metric.setText(f"DPS médio: {self._observed_dps:,.0f}")
        self.peak_metric.setText(f"Maior hit: {self._peak_hit:,.0f}")

    def _on_video_loaded(self, video_path: str) -> None:
        if self.modo_analise == "VIDEO" and not self._performance_mode:
            self._start_live_analysis(video_path)

    def set_performance_mode(self, enabled: bool) -> None:
        """Cooperatively stop active analysis and suppress automatic OCR."""
        entering_performance_mode = enabled and not self._performance_mode
        self._performance_mode = enabled
        if entering_performance_mode and self.live_worker is not None:
            self._stop_live_analysis()

    def _on_video_stopped(self) -> None:
        if self.modo_analise == "VIDEO":
            self._stop_live_analysis()

    def _analysis_start_seconds(self) -> float:
        """Return the manual video timestamp where live analysis should begin."""
        return self._time_to_seconds(self.analysis_start_time)

    def _scan_start_seconds(self) -> float:
        return max(
            self._time_to_seconds(self.skip_intro_time),
            self._analysis_start_seconds(),
        )

    def _analysis_end_seconds(self) -> float:
        """Return zero for an unlimited analysis end time."""
        return self._time_to_seconds(self.analysis_end_time)

    @staticmethod
    def _time_to_seconds(control: QTimeEdit) -> float:
        time = control.time()
        return float(time.hour() * 3600 + time.minute() * 60 + time.second())

    def _toggle_live_analysis(self) -> None:
        self.analysis_source.setCurrentIndex(0 if self.modo_analise == "LIVE" else 1)

    def _on_analysis_source_changed(self, index: int) -> None:
        if index == 1:
            self._switch_to_live_mode()
        elif index == 2:
            self._switch_to_generic_live_mode()
        else:
            self._switch_to_video_mode()

    def _set_analysis_source_ui(self, live: bool) -> None:
        setter = getattr(self.video_player, "set_live_capture_mode", None)
        if setter is not None:
            setter(live)
        for widget in self._analysis_interval_widgets:
            widget.setVisible(not live)

    def _switch_to_live_mode(self) -> None:
        self.modo_analise = "LIVE"
        self._start_live_capture("WUTHERING_WAVES")

    def _switch_to_generic_live_mode(self) -> None:
        self.modo_analise = "LIVE"
        self._start_live_capture("GENERIC_WINDOW")

    def _start_live_capture(self, capture_mode: str) -> None:
        if not self._stop_live_analysis():
            self.analysis_status.setText("Aguardando encerramento da análise anterior")
            return
        self.video_player.media_player.pause()
        self._set_analysis_source_ui(True)
        self._reset_live_plot()
        self.analysis_status.setText("Captura em tempo real ativa")

        video_path = getattr(self.video_player, "video_path", "")
        if self._is_live_capture_available():
            self.live_thread = QThread(self)
            worker = WorkerCapturaNativa(
                start_time=self._analysis_start_seconds(),
                end_seconds=self._analysis_end_seconds(),
                capture_mode=capture_mode,
                capture_settings=getattr(self, "capture_settings", None),
            )
            self.live_worker = worker
            worker.moveToThread(self.live_thread)
            self.live_thread.finished.connect(worker.deleteLater)
            self.live_thread.started.connect(worker.run)
            worker.frame_preview_frame_signal.connect(self._on_live_preview_frame)
            worker.game_detected.connect(self.video_player.set_live_game_title)
            worker.capture_status.connect(self._on_capture_status)
            worker.damage_detected.connect(self._on_live_damage)
            worker.combat_state_changed.connect(self._on_combat_state_changed)
            worker.battle_restarted.connect(self._on_battle_restarted)
            worker.map_detected.connect(self._on_map_detected)
            worker.analysis_completed.connect(self._on_analysis_completed)
            worker.failed.connect(self._on_live_failed)
            worker.finished.connect(self._on_live_finished)
            thread = self.live_thread
            thread.finished.connect(self._on_live_thread_finished)
            thread.start()
            thread.setPriority(QThread.Priority.LowPriority)
            return

        self.analysis_status.setText(
            "Captura nativa por HWND indisponível neste sistema"
        )

    def _switch_to_video_mode(self) -> None:
        self.modo_analise = "VIDEO"
        self._set_analysis_source_ui(False)
        if not self._stop_live_analysis():
            self.analysis_status.setText("Aguardando encerramento da análise anterior")
            return
        self.analysis_status.setText("Retornando ao fluxo do player de vídeo")
        video_path = getattr(self.video_player, "video_path", "")
        if video_path:
            self._start_live_analysis(video_path)

    def _reset_live_plot(self) -> None:
        self._dps_start_time = 0.0
        self._plot_update_timer.stop()
        self._plot_dirty = False
        self.cutoff_line.hide()
        self._live_blocks.clear()
        self._render_initial_analysis_point()

    def set_capture_settings(self, settings: CaptureSettings) -> None:
        self.capture_settings = settings
        self._total_hits = 0
        self._peak_hit = 0
        self._hit_times.clear()
        self.has_real_data = False
        self._combat_elapsed_seconds = 0.0
        self.combat_state_label.setText(f"Estado: {FORA_DE_COMBATE}")
        self.map_label.setText("Mapa Atual: aguardando leitura...")
        self.damage_metric.setText("Dano acumulado: --")
        self.dps_metric.setText("DPS médio: --")
        self.peak_metric.setText("Maior hit: --")
        self.hit_label.setText("Hits: 0")

    @staticmethod
    def _is_live_capture_available() -> bool:
        try:
            if sys.platform != "win32":
                import mss
                return bool(mss.mss().monitors)
            import ctypes
            return ctypes.windll.user32 is not None and ctypes.windll.gdi32 is not None
        except Exception:
            return False

    def _start_live_analysis(self, video_path: str) -> None:
        if not self._stop_live_analysis():
            self.analysis_status.setText("Aguardando encerramento da análise anterior")
            return
        self._dps_start_time = self._analysis_start_seconds()
        self._plot_update_timer.stop()
        self._plot_dirty = False
        self.cutoff_line.hide()
        self._live_blocks.clear()
        self._render_initial_analysis_point()
        self._total_hits = 0
        self._peak_hit = 0
        self._hit_times.clear()
        self.has_real_data = False
        self._combat_elapsed_seconds = 0.0
        self.combat_state_label.setText(f"Estado: {FORA_DE_COMBATE}")
        self.map_label.setText("Mapa Atual: --")
        self.damage_metric.setText("Dano acumulado: --")
        self.dps_metric.setText("DPS médio: --")
        self.peak_metric.setText("Maior hit: --")
        self.hit_label.setText("Hits: 0")
        self.analysis_status.setText(
            f"Aguardando números reais a partir de {self._analysis_start_seconds():.0f}s..."
        )
        self.live_thread = QThread(self)
        worker = LiveDamageAnalysisWorker(
            video_path,
            self._scan_start_seconds(),
            self._analysis_end_seconds(),
            self._analysis_start_seconds(),
        )
        self.live_worker = worker
        worker.moveToThread(self.live_thread)
        self.live_thread.finished.connect(worker.deleteLater)
        self.live_thread.started.connect(worker.run)
        worker.damage_detected.connect(self._on_live_damage)
        worker.analysis_completed.connect(self._on_analysis_completed)
        worker.failed.connect(self._on_live_failed)
        worker.finished.connect(self._on_live_finished)
        thread = self.live_thread
        thread.finished.connect(self._on_live_thread_finished)
        thread.start()
        thread.setPriority(QThread.Priority.LowPriority)

    def _on_analysis_completed(self, data: dict) -> None:
        last_hit = float(data.get("last_hit", -1.0))
        if last_hit < 0:
            last_hit = self._pending_position_ms / 1000.0
        self.cutoff_line.setValue(last_hit)
        self.cutoff_line.show()
        self.analysis_status.setText(
            f"Concluída (Último hit em {self._clock_seconds(last_hit)})"
        )
        self._plot_dirty = True
        if not self._plot_update_timer.isActive():
            self._plot_update_timer.start()

    def _on_live_damage(self, data: dict) -> None:
        timestamp = float(data.get("timestamp", 0.0))
        damage = float(data.get("damage", 0.0))
        hits = int(data.get("hits", 0))
        peak = float(data.get("peak", 0.0))
        if damage <= 0 or hits <= 0:
            return
        if timestamp < self._dps_start_time:
            return
        block_seconds = ANALYSIS_BUCKET_SECONDS
        block_index = int(max(0.0, timestamp - self._dps_start_time) // block_seconds)
        block = self._live_blocks[block_index]
        block[0] += damage
        block[1] += hits
        block[2] = timestamp
        block[3] = max(block[3], peak)
        self._total_hits += hits
        self._peak_hit = max(self._peak_hit, peak)
        self._combat_elapsed_seconds = max(
            self._combat_elapsed_seconds,
            float(data.get("combat_elapsed", 0.0)),
        )
        self._hit_times.extend([timestamp] * hits)
        if len(self._hit_times) > MAX_LIVE_HIT_MARKERS:
            self._hit_times = self._hit_times[-MAX_LIVE_HIT_MARKERS:]
        self.has_real_data = True
        self._plot_dirty = True
        if not self._plot_update_timer.isActive():
            self._plot_update_timer.start()
        self.hit_label.setText(f"Hits: {self._total_hits}")
        self.analysis_status.setText(f"Ao vivo {self._clock_seconds(timestamp)}")

    def _on_combat_state_changed(self, state: str) -> None:
        self.combat_state_label.setText(f"Estado: {state}")
        if state == FORA_DE_COMBATE:
            self.analysis_status.setText("Fora de combate: DPS pausado")
        elif state == TELA_DE_RECOMPENSA:
            self.analysis_status.setText("Recompensas: DPS congelado")
        elif state == LOGIN:
            self.analysis_status.setText("Login/servidor: OCR pausado")
        elif state == FORA_DO_JOGO:
            self.analysis_status.setText("Fora do jogo: OCR pausado")
        elif state == CARREGANDO:
            self.analysis_status.setText("Carregando: OCR pausado")

    def _on_battle_restarted(self) -> None:
        self._reset_live_plot()
        self.combat_state_label.setText(f"Estado: {EXPLORACAO}")
        self.analysis_status.setText("Novo combate: aguardando primeiro hit")

    def _on_map_detected(self, map_name: str) -> None:
        self.map_label.setText(f"Mapa Atual: {map_name}")

    def _on_capture_status(self, status: str) -> None:
        self.analysis_status.setText(status)

    def _on_live_preview(self, image: QImage) -> None:
        worker = self.live_worker
        try:
            self.video_player.set_live_preview(image)
        finally:
            if isinstance(worker, WorkerCapturaNativa):
                worker.mark_preview_consumed()

    def _on_live_preview_frame(self, frame) -> None:
        self._on_live_preview(WorkerCapturaNativa._preview_image(frame))

    def _flush_plot_update(self) -> None:
        if not self._plot_dirty:
            self._plot_update_timer.stop()
            return
        self._plot_dirty = False
        self._render_live_blocks()

    @staticmethod
    def _clock_seconds(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60}:{total % 60:02d}"

    def _on_live_failed(self, message: str) -> None:
        self.analysis_status.setText(message)

    def _on_live_finished(self) -> None:
        if self.live_thread is not None:
            self.live_thread.quit()

    def _on_live_thread_finished(self) -> None:
        finished_thread = self.live_thread
        if finished_thread is None:
            return
        thread = finished_thread
        self.live_worker = None
        self.live_thread = None
        thread.deleteLater()
        self.shutdown_finished.emit()

    def _stop_live_analysis(self) -> bool:
        worker = self.live_worker
        thread = self.live_thread
        if worker is None:
            return True
        worker.cancel()
        if thread is not None and thread.isRunning():
            thread.quit()
            return False
        self.live_worker = None
        self.live_thread = None
        if thread is not None:
            thread.deleteLater()
        self.analysis_status.setText("Análise ao vivo parada")
        return True

    def closeEvent(self, event) -> None:
        if not self._stop_live_analysis():
            event.ignore()
            return
        super().closeEvent(event)

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms > 0:
            self.duration_seconds = duration_ms / 1000.0
            if not self.has_real_data:
                self._render_curve()

    def _queue_position(self, position_ms: int) -> None:
        self._pending_position_ms = position_ms
        if not self._position_timer.isActive():
            self._position_timer.start()

    def _flush_position(self) -> None:
        self._position_timer.stop()
        if self.modo_analise == "LIVE":
            return
        position_ms = self._pending_position_ms
        seconds = max(0.0, position_ms / 1000.0)
        self.cursor_line.setValue(seconds)
        self.position_label.setText(f"Cursor: {seconds:.2f}s")
        if isinstance(self.live_worker, LiveDamageAnalysisWorker):
            self.live_worker.update_position(seconds)

    def _seek_video(self, seconds: float) -> None:
        self.video_player.seek_to_seconds(max(0.0, min(self.duration_seconds, seconds)))
