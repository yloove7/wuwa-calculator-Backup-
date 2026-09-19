"""Persistent, conservative learning profiles for damage detection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from src.wuwa_calculator.utils.paths import get_user_data_path


@dataclass
class DamageLearningProfile:
    """Learn only from confirmed damage events, never from uncertain OCR."""

    confirmed_events: int = 0
    widths: list[float] = field(default_factory=list)
    heights: list[float] = field(default_factory=list)
    color_scores: list[float] = field(default_factory=list)

    @property
    def warming_up(self) -> bool:
        return self.confirmed_events < 8

    def accepts(self, width: int, height: int, color_score: float) -> bool:
        if self.warming_up or not self.widths or not self.heights:
            return True
        average_width = sum(self.widths) / len(self.widths)
        average_height = sum(self.heights) / len(self.heights)
        average_color = sum(self.color_scores) / max(1, len(self.color_scores))
        return (
            average_width * 0.35 <= width <= average_width * 2.8
            and average_height * 0.35 <= height <= average_height * 2.8
            and color_score >= average_color * 0.25
        )

    def observe(self, events: list[tuple[int, int, int, int, int, float, float]]) -> None:
        for _value, _x, _y, width, height, color_score, confidence in events:
            if confidence < 0.80:
                continue
            self.confirmed_events += 1
            self.widths.append(float(width))
            self.heights.append(float(height))
            self.color_scores.append(float(color_score))
        self.widths = self.widths[-64:]
        self.heights = self.heights[-64:]
        self.color_scores = self.color_scores[-64:]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DamageLearningProfile":
        return cls(
            confirmed_events=max(0, int(value.get("confirmed_events", 0))),
            widths=[float(item) for item in value.get("widths", [])][-64:],
            heights=[float(item) for item in value.get("heights", [])][-64:],
            color_scores=[float(item) for item in value.get("color_scores", [])][-64:],
        )


class LearningStore:
    """Keep learning data in one dedicated user-data directory."""

    PATH = get_user_data_path(Path("capture_learning") / "damage_profiles.json")

    def __init__(self) -> None:
        self._lock = Lock()
        self._profiles: dict[str, DamageLearningProfile] = {}
        self._load()

    def profile(self, key: str) -> DamageLearningProfile:
        with self._lock:
            return self._profiles.setdefault(key, DamageLearningProfile())

    def save(self) -> None:
        with self._lock:
            self.PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                key: asdict(profile)
                for key, profile in self._profiles.items()
            }
            self.PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load(self) -> None:
        try:
            payload = json.loads(self.PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            if isinstance(value, dict):
                self._profiles[str(key)] = DamageLearningProfile.from_dict(value)
