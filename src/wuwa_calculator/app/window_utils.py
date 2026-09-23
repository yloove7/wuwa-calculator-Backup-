"""Native Win32 game-window discovery for capture backends."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

GAME_WINDOW_CLASSES = {
    "RiotWindowClass",
    "UnrealWindow",
    "UnityWndClass",
    "GLFW30",
    "SDL_app",
}
GAME_TITLE_HINTS = (
    "wuthering waves",
    "league of legends",
    "honkai star rail",
    "honkai: star rail",
)
EXCLUDED_TITLE_HINTS = ("tethys protocol",)


def _window_text(user32, hwnd: int) -> tuple[str, str]:
    title_length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(max(1, title_length + 1))
    user32.GetWindowTextW(hwnd, title, len(title))
    window_class = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, window_class, len(window_class))
    return title.value, window_class.value


def _is_candidate(user32, hwnd: int) -> tuple[bool, tuple[int, int, int, int] | None]:
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False, None
    title, window_class = _window_text(user32, hwnd)
    normalized_title = title.casefold()
    if any(term in normalized_title for term in EXCLUDED_TITLE_HINTS):
        return False, None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False, None
    bounds = (rect.left, rect.top, rect.right, rect.bottom)
    if rect.right - rect.left <= 400 or rect.bottom - rect.top <= 300:
        return False, None
    is_game = window_class in GAME_WINDOW_CLASSES or any(
        hint in normalized_title for hint in GAME_TITLE_HINTS
    )
    return is_game, bounds


def obter_hwnd_jogo(mode: str = "WUTHERING_WAVES") -> int | None:
    """Return the best visible game HWND, preferring the foreground window."""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, tuple[int, int, int, int]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _extra):
        is_game, bounds = _is_candidate(user32, hwnd)
        if is_game and bounds is not None:
            candidates.append((int(hwnd), bounds))
        return True

    user32.EnumWindows(callback, 0)
    if not candidates:
        return None

    foreground = int(user32.GetForegroundWindow() or 0)
    if mode == "GENERIC_WINDOW":
        for hwnd, _bounds in candidates:
            if hwnd == foreground:
                return hwnd
        for hwnd, _bounds in candidates:
            title, _window_class = _window_text(user32, hwnd)
            if "league of legends" in title.casefold():
                return hwnd
        return candidates[0][0]

    wuthering = []
    for hwnd, bounds in candidates:
        title, window_class = _window_text(user32, hwnd)
        if "wuthering waves" in title.casefold() or window_class == "UnrealWindow":
            wuthering.append((hwnd, bounds))
    for hwnd, _bounds in wuthering:
        if hwnd == foreground:
            return hwnd
    return None
