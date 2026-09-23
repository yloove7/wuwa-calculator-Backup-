import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.convene_tracker_tab import ConveneTrackerTab
from src.wuwa_calculator.app.pity_tracker import (
    KURO_TIMEZONE,
    LegacyPityTrackerWidget,
    PityHistoryImportWorker,
)
from src.wuwa_calculator.domain.pity import record_sort_key
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager
from src.wuwa_calculator.utils.convene_datetime import parse_convene_datetime


class ConveneDateTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_parser_supports_convene_timestamp_formats(self) -> None:
        expected = datetime(2026, 9, 22, 20, 56, 51, tzinfo=KURO_TIMEZONE)
        unix_seconds = datetime(2026, 9, 23, 1, 56, 51, tzinfo=timezone.utc).timestamp()
        values = (
            "2026-09-22 20:56:51",
            "2026-09-23T01:56:51Z",
            "2026-09-22T22:56:51-03:00",
            unix_seconds,
            str(int(unix_seconds)),
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(parse_convene_datetime(value), expected)
        self.assertIsNone(parse_convene_datetime(None))
        self.assertIsNone(parse_convene_datetime("not a timestamp"))

    def test_hiyuki_displays_server_clock_without_conversion(self) -> None:
        self.assertEqual(
            ConveneTrackerTab._format_timestamp("2026-09-22 20:56:51"),
            "22/09/2026 20:56",
        )

    def test_storage_and_pity_sort_use_kuro_chronology(self) -> None:
        earlier = {"timestamp": "2026-09-22 14:26:22"}
        later = {"timestamp": "2026-09-22 20:56:51"}
        self.assertLess(record_sort_key(earlier), record_sort_key(later))
        self.assertEqual(
            ConveneStorageManager._sort_records([later, earlier]),
            [earlier, later],
        )

    @unittest.skipUnless(hasattr(time, "tzset"), "time.tzset is unavailable on this platform")
    def test_parser_is_independent_of_process_timezone(self) -> None:
        previous_tz = os.environ.get("TZ")
        try:
            values = []
            for zone in ("UTC0", "EST5", "NZST-12"):
                os.environ["TZ"] = zone
                time.tzset()
                values.append(parse_convene_datetime("2026-09-22 20:56:51"))
            self.assertEqual(values[0], values[1])
            self.assertEqual(values[1], values[2])
            self.assertEqual(values[0].utcoffset().total_seconds(), -5 * 60 * 60)
        finally:
            if previous_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_tz
            time.tzset()

    def _run_import(self, manager, records, now):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

        worker = PityHistoryImportWorker("https://example.invalid/record")
        imported = []
        worker.imported.connect(imported.append)
        with patch("src.wuwa_calculator.app.pity_tracker.fetch_convene_records", return_value=records), \
                patch("src.wuwa_calculator.app.pity_tracker.ConveneStorageManager", return_value=manager), \
                patch("src.wuwa_calculator.app.pity_tracker.datetime", FrozenDateTime):
            worker.run()
        return imported[0]

    def test_month_filter_uses_kuro_boundaries(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ConveneStorageManager(Path(directory) / "history.json")
            records = [
                {"timestamp": "2026-09-30 23:59:59", "name": "September", "rarity": 3, "pool": "resonator"},
                {"timestamp": "2026-10-01 00:00:00", "name": "October", "rarity": 3, "pool": "resonator"},
            ]
            imported = self._run_import(
                manager,
                records,
                datetime(2026, 9, 30, 23, 45, tzinfo=KURO_TIMEZONE),
            )
            self.assertEqual([record["name"] for record in imported], ["September"])

    def test_old_history_and_pity_survive_empty_current_month_import(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ConveneStorageManager(Path(directory) / "history.json")
            manager.merge([
                {"timestamp": "2026-06-10 10:00:00", "name": "Old five", "rarity": 5, "pool": "resonator"},
                {"timestamp": "2026-08-15 10:00:00", "name": "Old three", "rarity": 3, "pool": "resonator"},
            ])
            tracker = LegacyPityTrackerWidget()
            tracker.history_records = []
            imported_records = self._run_import(
                manager,
                [{"timestamp": "2026-08-20 10:00:00", "name": "Outside month", "rarity": 3, "pool": "resonator"}],
                datetime(2026, 9, 22, 12, 0, tzinfo=KURO_TIMEZONE),
            )
            tracker._apply_imported_records(imported_records)
            tab = ConveneTrackerTab(tracker)
            self.assertEqual(len(manager.load()), 2)
            self.assertEqual(len(tracker.history_records), 2)
            self.assertEqual(tracker.state.total_registered, 2)
            self.assertEqual(tracker.state.resonator, 1)
            self.assertEqual(tab.pity_values["resonator"].text(), "1 / 80")
            tab.close()
            tracker.close()

    def test_pity_receives_existing_history_plus_current_month_import(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ConveneStorageManager(Path(directory) / "history.json")
            manager.merge([
                {"timestamp": "2026-08-15 10:00:00", "name": "Old three", "rarity": 3, "pool": "resonator"},
            ])
            tracker = LegacyPityTrackerWidget()
            tracker.history_records = []
            imported_records = self._run_import(
                manager,
                [{"timestamp": "2026-09-22 20:56:51", "name": "Hiyuki", "rarity": 5, "pool": "resonator"}],
                datetime(2026, 9, 22, 23, 0, tzinfo=KURO_TIMEZONE),
            )
            tracker._apply_imported_records(imported_records)
            self.assertEqual(len(manager.load()), 2)
            self.assertEqual(tracker.state.total_registered, 2)
            self.assertEqual(tracker.state.five_star_history, [2])
            tracker.close()

    def test_merge_keeps_original_timestamp_string(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ConveneStorageManager(Path(directory) / "history.json")
            record = {
                "timestamp": "2026-09-22 20:56:51",
                "name": "Hiyuki",
                "rarity": 5,
                "pool": "resonator",
                "raw": {"time": "2026-09-22 20:56:51"},
            }
            manager.merge([record])
            stored = manager.load()[0]
            self.assertEqual(stored["timestamp"], "2026-09-22 20:56:51")
            self.assertEqual(stored["raw"]["time"], "2026-09-22 20:56:51")


if __name__ == "__main__":
    unittest.main()
