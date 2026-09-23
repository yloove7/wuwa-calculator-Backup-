"""Datetime parsing rules for Kuro Convene records."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

KURO_TIMEZONE = timezone(timedelta(hours=-5), name="UTC-05:00")
_UNIX_TIMESTAMP_RE = re.compile(r"^\d+(?:\.\d+)?$")


def parse_convene_datetime(value: object) -> datetime | None:
    """Parse a Convene timestamp and return an aware datetime in Kuro America time."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), KURO_TIMEZONE)
        except (OverflowError, OSError, TypeError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if _UNIX_TIMESTAMP_RE.fullmatch(text):
        try:
            return datetime.fromtimestamp(float(text), KURO_TIMEZONE)
        except (OverflowError, OSError, TypeError, ValueError):
            return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KURO_TIMEZONE)
    return parsed.astimezone(KURO_TIMEZONE)
