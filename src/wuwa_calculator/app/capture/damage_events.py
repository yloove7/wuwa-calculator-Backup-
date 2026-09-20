"""Temporal validation and de-duplication for floating damage numbers."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable


DamageCandidate = tuple[int, int, int, int, int, float, float]


@dataclass
class _Observation:
    candidate: DamageCandidate
    first_seen: float
    last_seen: float
    sightings: int = 1
    emitted: bool = False


class DamageEventTracker:
    """Turn OCR candidates into confirmed, non-duplicated damage events."""

    def __init__(self) -> None:
        self._observations: list[_Observation] = []

    def reset(self) -> None:
        self._observations.clear()

    def expire(self, timestamp: float) -> None:
        self._observations = [
            observation
            for observation in self._observations
            if timestamp - observation.last_seen <= 0.45
        ]

    def update(
        self,
        candidates: Iterable[DamageCandidate],
        timestamp: float,
    ) -> list[DamageCandidate]:
        self.expire(timestamp)
        emitted: list[DamageCandidate] = []
        matched: set[int] = set()
        for candidate in candidates:
            match_index = self._find_match(candidate, timestamp, matched)
            if match_index is None:
                observation = _Observation(candidate, timestamp, timestamp)
                if candidate[6] >= 0.90:
                    observation.emitted = True
                    emitted.append(candidate)
                self._observations.append(observation)
                continue
            matched.add(match_index)
            observation = self._observations[match_index]
            observation.candidate = candidate
            observation.last_seen = timestamp
            observation.sightings += 1
            confidence = candidate[6]
            confirmed = observation.sightings >= 2 or confidence >= 0.90
            if confirmed and not observation.emitted:
                observation.emitted = True
                emitted.append(candidate)
        return emitted

    def _find_match(
        self,
        candidate: DamageCandidate,
        timestamp: float,
        matched: set[int],
    ) -> int | None:
        value, center_x, center_y, width, height, _color_score, _confidence = candidate
        best_index = None
        best_distance = float("inf")
        for index, observation in enumerate(self._observations):
            if index in matched or timestamp - observation.last_seen > 0.30:
                continue
            previous = observation.candidate
            if previous[0] != value:
                continue
            distance = hypot(center_x - previous[1], center_y - previous[2])
            tolerance = max(24.0, (width + previous[3]) * 0.75, (height + previous[4]) * 1.5)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index
