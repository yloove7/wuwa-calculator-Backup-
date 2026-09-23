from dataclasses import dataclass, field
<<<<<<< HEAD

from src.wuwa_calculator.utils.convene_datetime import parse_convene_datetime
=======
from datetime import datetime
>>>>>>> ca9337b6812adf36dd7ff2e1304ae5b2512f43f3


@dataclass
class PityState:
    resonator: int | None = None
    weapon: int | None = None
    standard_character: int | None = None
    standard_weapon: int | None = None
    guaranteed: bool | None = None
    five_star_history: list[int] = field(default_factory=list)
    recent_convene_details: list[str] = field(default_factory=list)
    total_registered: int = 0
    four_star_total: int = 0


def extract_records(data: object) -> list[dict[str, object]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if any(key in data for key in ("name", "item", "quality", "rarity", "rank", "time")):
            return [data]
        for key in ("list", "records", "history", "items", "rows", "pulls", "result", "data"):
            records = extract_records(data.get(key))
            if records:
                return records
    return []


def record_sort_key(record: dict[str, object]) -> tuple[int, float]:
    value = record.get("timestamp", record.get("time", record.get("date")))
<<<<<<< HEAD
    parsed = parse_convene_datetime(value)
    if parsed is None:
        return (1, 0.0)
    return (0, parsed.timestamp())
=======
    try:
        if isinstance(value, (int, float)):
            return (0, float(value))
        text = str(value or "").strip().replace("Z", "+00:00")
        return (0, datetime.fromisoformat(text).timestamp())
    except (TypeError, ValueError, OverflowError):
        return (1, 0.0)
>>>>>>> ca9337b6812adf36dd7ff2e1304ae5b2512f43f3


def format_recent_record(record: object) -> str:
    if not isinstance(record, dict):
        return str(record)
    name = record.get("name", record.get("item", record.get("title", "Convene")))
    rarity = record.get("quality", record.get("rarity", record.get("rank", "?")))
    return f"{name} ({rarity}★)"


def record_pool(record: dict[str, object]) -> str:
    metadata = " ".join(
        str(record.get(key, ""))
        for key in ("type", "pool", "banner", "gacha_type", "resource", "name")
    ).casefold()
    is_weapon = "weapon" in metadata or "arma" in metadata
    is_standard = any(value in metadata for value in ("standard", "permanent", "novice", "常驻"))
    if is_standard and is_weapon:
        return "standard_weapon"
    if is_standard:
        return "standard_character"
    if is_weapon:
        return "weapon"
    return "resonator"


def calculate_pity_state(records: list[object]) -> PityState:
    ordered_records = sorted(
        (record for record in records if isinstance(record, dict)),
        key=record_sort_key,
    )
    pity_by_pool = {
        "resonator": 0,
        "weapon": 0,
        "standard_character": 0,
        "standard_weapon": 0,
    }
    five_stars: list[int] = []
    four_stars = 0
    for record in ordered_records:
        pool = record_pool(record)
        pity_by_pool[pool] += 1
        rarity = record.get("quality", record.get("rarity", record.get("rank", 0)))
        try:
            rarity_value = int(rarity)
        except (TypeError, ValueError):
            continue
        if rarity_value >= 5:
            five_stars.append(pity_by_pool[pool])
            pity_by_pool[pool] = 0
        elif rarity_value >= 4:
            four_stars += 1

    return PityState(
        resonator=pity_by_pool["resonator"],
        weapon=pity_by_pool["weapon"],
        standard_character=pity_by_pool["standard_character"],
        standard_weapon=pity_by_pool["standard_weapon"],
        five_star_history=five_stars,
        recent_convene_details=[
            format_recent_record(record) for record in ordered_records[-5:]
        ],
        total_registered=len(ordered_records),
        four_star_total=four_stars,
    )
