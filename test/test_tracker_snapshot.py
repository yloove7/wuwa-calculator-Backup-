import sys
import unittest
from datetime import datetime, timezone

from src.wuwa_calculator.app.tracker_snapshot import (
    BannerRecord,
    CurrentBanner,
    NoticeRecord,
    PitySnapshot,
    PoolStatus,
    PullRecord,
    TrackerSnapshot,
    TrackerStatusSnapshot,
)


class TrackerSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamp = datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)
        self.pool = PoolStatus("ready", True, 3, None)
        self.status = TrackerStatusSnapshot(
            "available",
            "available",
            "ready",
            "synced",
            self.timestamp,
            self.timestamp,
            0.0,
            False,
            False,
            "test",
            "ok",
            1,
            {"resonator": self.pool},
        )

    def test_current_banner(self) -> None:
        banner = CurrentBanner("Aalto", "/aalto.png", b"image", self.timestamp, None, 5, "aero", "catalog")
        self.assertEqual(banner.name, "Aalto")
        self.assertEqual(banner.image_bytes, b"image")

    def test_banner_record(self) -> None:
        banner = BannerRecord("Aalto", "past", self.timestamp, None, None, b"image", 5, "catalog", False)
        self.assertEqual(banner.kind, "past")

    def test_pull_record(self) -> None:
        pull = PullRecord(self.timestamp, "resonator", "Aalto", 5, "id-1", "log", "id:id-1")
        self.assertEqual(pull.official_id, "id-1")

    def test_pity_snapshot(self) -> None:
        pity = PitySnapshot(10, 20, 30, 40, [80, 90], ["Aalto"], 100, 12)
        self.assertEqual(pity.five_star_history, (80, 90))
        self.assertEqual(pity.recent_convene_details, ("Aalto",))

    def test_pool_status(self) -> None:
        self.assertEqual(self.pool.record_count, 3)

    def test_tracker_status_snapshot(self) -> None:
        self.assertEqual(self.status.pool_status["resonator"], self.pool)

    def test_notice_record(self) -> None:
        notice = NoticeRecord("event", "new", "Title", "active", "Summary", "Rewards", None, "gold", None, None, None)
        self.assertEqual(notice.title, "Title")

    def test_tracker_snapshot(self) -> None:
        snapshot = TrackerSnapshot(None, [], [], PitySnapshot(None, None, None, None, (), (), 0, 0), self.status, [])
        self.assertEqual(snapshot.banners, ())
        self.assertEqual(snapshot.notices, ())

    def test_dataclasses_are_immutable(self) -> None:
        with self.assertRaises((AttributeError, TypeError)):
            self.pool.status = "changed"

    def test_tuples_cannot_be_changed(self) -> None:
        snapshot = TrackerSnapshot(None, [], [], PitySnapshot(None, None, None, None, [], [], 0, 0), self.status, [])
        with self.assertRaises(AttributeError):
            snapshot.banners.append(None)  # type: ignore[attr-defined]

    def test_pool_status_cannot_be_mutated_externally(self) -> None:
        pool_status = {"resonator": self.pool}
        status = TrackerStatusSnapshot("a", "b", "c", "d", None, None, None, None, None, "e", "f", 0, pool_status)
        pool_status.clear()
        self.assertIn("resonator", status.pool_status)
        with self.assertRaises(TypeError):
            status.pool_status["weapon"] = self.pool  # type: ignore[index]

    def test_module_does_not_import_pyside6(self) -> None:
        self.assertNotIn("PySide6", sys.modules)


if __name__ == "__main__":
    unittest.main()