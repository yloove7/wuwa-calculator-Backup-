import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.wuwa_calculator.app.home_tab import HomeTab


class HomeTrackerSnapshotTests(unittest.TestCase):
    def make_home(self, *, banner_data=None, catalog=(), history=(), state=None, status=None, notices=()):
        home = HomeTab.__new__(HomeTab)
        home.banner_data = banner_data
        home._catalog_snapshot_source = tuple(catalog)
        home.pity_tracker = SimpleNamespace(
            state=state or SimpleNamespace(
                resonator=7,
                weapon=8,
                standard_character=9,
                standard_weapon=10,
                guaranteed=True,
                five_star_history=[3, 5],
                recent_convene_details=["Qingxiao (5★)"],
                total_registered=20,
                four_star_total=4,
            ),
            tracker_status=status or SimpleNamespace(
                log_status="valid",
                api_status="success",
                history_status="updated",
                sync_status="success",
                last_sync_at="2026-09-20T12:00:00+00:00",
                last_success_at="2026-09-20T12:01:00Z",
                history_age=12.5,
                is_partial=False,
                is_stale=False,
                source="api",
                message="ok",
                new_records_count=2,
                pool_status={"resonator": {"status": "success", "completed": True, "record_count": 2}},
            ),
            notices=list(notices),
        )
        return home, history

    def build(self, **kwargs):
        home, history = self.make_home(**kwargs)
        with patch("src.wuwa_calculator.app.home_tab.ConveneStorageManager") as storage_class:
            storage_class.return_value.load.return_value = list(history)
            return home._build_tracker_snapshot()

    def test_current_banner_is_projected(self):
        snapshot = self.build(banner_data={
            "name": "Qingxiao",
            "image_url": "https://example/banner.png",
            "image_bytes": b"image",
            "starts_at": "2026-09-10T00:00:00Z",
            "ends_at": "2026-10-01T00:00:00+00:00",
            "rarity": 5,
            "element": "aero",
            "source": "test",
        })
        self.assertEqual(snapshot.current_banner.name, "Qingxiao")
        self.assertEqual(snapshot.current_banner.ends_at.tzinfo, timezone.utc)
        self.assertEqual(snapshot.current_banner.image_bytes, b"image")

    def test_missing_current_banner_is_allowed(self):
        self.assertIsNone(self.build(banner_data=None).current_banner)

    def test_catalog_preserves_existing_kind(self):
        snapshot = self.build(catalog=(
            {"name": "Past", "kind": "past", "ends_at": "2026-09-01T00:00:00Z"},
            {"name": "Future", "kind": "future", "starts_at": "2026-09-25T00:00:00Z"},
        ))
        self.assertEqual([record.kind for record in snapshot.banners], ["past", "future"])

    def test_history_generates_pull_records(self):
        snapshot = self.build(history=(
            {"timestamp": "2026-09-20T12:00:00Z", "pool": "weapon", "name": "Sword", "rarity": 4,
             "official_id": "id-1", "source": "storage", "dedup_key": "id:id-1", "raw": {"extra": True}},
        ))
        pull = snapshot.pulls[0]
        self.assertEqual(pull.name, "Sword")
        self.assertEqual(pull.official_id, "id-1")
        self.assertIsInstance(pull.timestamp, datetime)

    def test_timestamp_conversion_supports_iso_unix_and_invalid(self):
        snapshot = self.build(history=(
            {"timestamp": "2026-09-20T12:00:00+00:00"},
            {"timestamp": 0},
            {"timestamp": 1.5},
            {"timestamp": "invalid"},
        ))
        self.assertEqual(len(snapshot.pulls), 4)
        self.assertEqual(snapshot.pulls[0].timestamp.year, 2026)
        self.assertEqual(snapshot.pulls[1].timestamp, datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(snapshot.pulls[2].timestamp, datetime(1970, 1, 1, 0, 0, 1, 500000, tzinfo=timezone.utc))
        self.assertIsNone(snapshot.pulls[3].timestamp)

    def test_pity_is_projected_without_guaranteed(self):
        snapshot = self.build()
        self.assertEqual(snapshot.pity.five_star_history, (3, 5))
        self.assertEqual(snapshot.pity.recent_convene_details, ("Qingxiao (5★)",))
        self.assertFalse(hasattr(snapshot.pity, "guaranteed"))

    def test_tracker_status_and_pool_status_are_projected(self):
        snapshot = self.build()
        self.assertEqual(snapshot.status.last_success_at.minute, 1)
        self.assertEqual(snapshot.status.pool_status["resonator"].record_count, 2)
        with self.assertRaises(TypeError):
            snapshot.status.pool_status["weapon"] = snapshot.status.pool_status["resonator"]

    def test_notices_preserve_string_fields(self):
        snapshot = self.build(notices=(
            {"category": "Avisos", "tag": "Aviso", "title": "Patch", "status": "Atualizado",
             "summary": "Resumo", "rewards": "Astrites", "image_url": "https://example/image.png",
             "accent": "#fff", "date": "09-09", "end_at": "2026-10-01", "content_url": "https://example/news"},
        ))
        notice = snapshot.notices[0]
        self.assertEqual(notice.date, "09-09")
        self.assertEqual(notice.end_at, "2026-10-01")
        self.assertEqual(notice.content_url, "https://example/news")

    def test_partial_state_does_not_raise(self):
        home, history = self.make_home(banner_data=None, catalog=(), history=(), state=SimpleNamespace(), status=SimpleNamespace(), notices=())
        with patch("src.wuwa_calculator.app.home_tab.ConveneStorageManager") as storage_class:
            storage_class.return_value.load.return_value = list(history)
            snapshot = home._build_tracker_snapshot()
        self.assertEqual(snapshot.banners, ())
        self.assertEqual(snapshot.pulls, ())
        self.assertEqual(snapshot.notices, ())
        self.assertEqual(snapshot.pity.total_registered, 0)


if __name__ == "__main__":
    unittest.main()
