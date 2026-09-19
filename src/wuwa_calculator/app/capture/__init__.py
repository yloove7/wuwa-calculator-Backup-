"""Capture backends, settings, and frame-processing adapters."""

from .controller import CaptureController, FrameProcessor
from .damage_events import DamageEventTracker
from .settings import CaptureRate, CaptureSettings, ColorSpace, WindowMatchPriority

__all__ = [
    "CaptureController",
    "CaptureRate",
    "CaptureSettings",
    "ColorSpace",
    "DamageEventTracker",
    "FrameProcessor",
    "WindowMatchPriority",
]
