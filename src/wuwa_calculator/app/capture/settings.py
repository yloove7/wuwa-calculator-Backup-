"""Configuration types for the capture pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaptureRate(str, Enum):
    SLOW = "Slow"
    NORMAL = "Normal"
    FAST = "Fast"
    SUPER_FAST = "SuperFast"


class ColorSpace(str, Enum):
    SRGB = "sRGB"
    REC2100_PQ = "Rec.2100 PQ"


class WindowMatchPriority(str, Enum):
    TITLE = "Título"
    CLASS_NAME = "Classe da janela"
    EXECUTABLE = "Executável"


@dataclass(slots=True)
class CaptureSettings:
    capture_cursor: bool = True
    capture_audio: bool = False
    allow_transparency: bool = False
    premultiplied_alpha: bool = False
    limit_framerate: bool = False
    max_framerate: int = 60
    capture_overlays: bool = True
    anti_cheat_compatibility: bool = False
    capture_rate: CaptureRate = CaptureRate.NORMAL
    color_space: ColorSpace = ColorSpace.SRGB
    window_match_priority: WindowMatchPriority = WindowMatchPriority.TITLE
