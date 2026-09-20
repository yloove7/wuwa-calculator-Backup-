from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Mapping


@dataclass(frozen=True, slots=True)
class CurrentBanner:
    name: str
    image_url: str | None
    image_bytes: bytes | None
    starts_at: datetime | None
    ends_at: datetime | None
    rarity: int | str | None
    element: str | None
    source: str | None


@dataclass(frozen=True, slots=True)
class BannerRecord:
    name: str
    kind: Literal["current", "past", "future"]
    starts_at: datetime | None
    ends_at: datetime | None
    image_url: str | None
    image_bytes: bytes | None
    rarity: int | str | None
    source: str | None
    is_speculated: bool | None


@dataclass(frozen=True, slots=True)
class PullRecord:
    timestamp: datetime | None
    pool: str | None
    name: str | None
    rarity: int | str | None
    official_id: str | int | None
    source: str | None
    dedup_key: str | None


@dataclass(frozen=True, slots=True)
class PitySnapshot:
    resonator: int | None
    weapon: int | None
    standard_character: int | None
    standard_weapon: int | None
    five_star_history: tuple[int, ...]
    recent_convene_details: tuple[str, ...]
    total_registered: int
    four_star_total: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "five_star_history", tuple(self.five_star_history))
        object.__setattr__(self, "recent_convene_details", tuple(self.recent_convene_details))


@dataclass(frozen=True, slots=True)
class PoolStatus:
    status: str
    completed: bool
    record_count: int
    message: str | None


@dataclass(frozen=True, slots=True)
class TrackerStatusSnapshot:
    log_status: str
    api_status: str
    history_status: str
    sync_status: str
    last_sync_at: datetime | None
    last_success_at: datetime | None
    history_age: float | None
    is_partial: bool | None
    is_stale: bool | None
    source: str
    message: str
    new_records_count: int
    pool_status: Mapping[str, PoolStatus]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool_status", MappingProxyType(dict(self.pool_status)))


@dataclass(frozen=True, slots=True)
class NoticeRecord:
    category: str
    tag: str
    title: str
    status: str
    summary: str
    rewards: str
    image_url: str | None
    accent: str | None
    date: str | None
    end_at: str | None
    content_url: str | None


@dataclass(frozen=True, slots=True)
class TrackerSnapshot:
    current_banner: CurrentBanner | None
    banners: tuple[BannerRecord, ...]
    pulls: tuple[PullRecord, ...]
    pity: PitySnapshot
    status: TrackerStatusSnapshot
    notices: tuple[NoticeRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "banners", tuple(self.banners))
        object.__setattr__(self, "pulls", tuple(self.pulls))
        object.__setattr__(self, "notices", tuple(self.notices))