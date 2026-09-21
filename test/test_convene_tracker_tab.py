import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from src.wuwa_calculator.app.convene_tracker_tab import ConveneTrackerTab
from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget


class ConveneTrackerTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_tab_consumes_tracker_state_history_and_refresh(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        tracker.state.total_registered = 4
        tracker.state.five_star_history = [3]
        tracker.state.recent_convene_details = ["Jingran (5★)"]
        tracker.state_changed.emit(tracker.state)
        tracker.history_records = [{
            "timestamp": "2026-09-20",
            "name": "Jingran",
            "rarity": 5,
            "pool": "resonator",
        }]
        tracker.history_changed.emit(tracker.history_records)
        tracker.request_sync = Mock()

        tab.refresh_button.click()

        self.assertIsNotNone(tab.findChild(QScrollArea, "conveneTrackerScrollArea"))
        self.assertEqual(tab.summary_values["total"].text(), "4")
        self.assertEqual(
            tab.last_five_label.text(),
            "Último 5★: Jingran · Resonator · 20/09/2026 00:00",
        )
        self.assertEqual(tab.history_table.rowCount(), 1)
        tracker.request_sync.assert_called_once_with()
        tracker.deleteLater()
        tab.deleteLater()

    def test_latest_five_uses_newest_rarity_five_record(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"rarity": 5, "name": "Old Five", "pool": "resonator", "date": "2026-09-19"},
            {"rarity": 4, "name": "Recent Four", "pool": "weapon", "date": "2026-09-20T10:00:00Z"},
            {"rarity": 5, "name": "Newest Five", "pool": "weapon", "date": "2026-09-20T11:00:00Z"},
            {"rarity": 3, "name": "Recent Three", "pool": "resonator", "date": "2026-09-20T12:00:00Z"},
        ]
        original_records = [dict(record) for record in records]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        self.assertEqual(
            tab.last_five_label.text(),
            "Último 5★: Newest Five · Weapon · 20/09/2026 11:00",
        )
        self.assertEqual(records, original_records)
        tracker.deleteLater()
        tab.deleteLater()

    def test_latest_five_supports_rarity_quality_and_rank_fallbacks(self) -> None:
        for rarity_field in ("rarity", "quality", "rank"):
            with self.subTest(rarity_field=rarity_field):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tracker.history_records = [{
                    rarity_field: 5,
                    "item": "Fallback Five",
                    "type": "weapon",
                    "time": "2026-09-20T13:00:00Z",
                }]

                tracker.history_changed.emit(tracker.history_records)

                self.assertEqual(
                    tab.last_five_label.text(),
                    "Último 5★: Fallback Five · Weapon · 20/09/2026 13:00",
                )
                tracker.deleteLater()
                tab.deleteLater()

    def test_latest_five_is_empty_when_history_has_no_five_star(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        tracker.history_records = [
            {"rarity": 4, "name": "Four", "date": "2026-09-20"},
            {"rarity": 3, "name": "Three", "date": "2026-09-20"},
        ]

        tracker.history_changed.emit(tracker.history_records)

        self.assertEqual(tab.last_five_label.text(), "Nenhum 5★ registrado")
        tracker.deleteLater()
        tab.deleteLater()

    def test_presentation_states_update_without_backend_changes(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)

        tracker.state.resonator = 70
        tracker.state.guaranteed = True
        tracker.state_changed.emit(tracker.state)
        tracker.tracker_status.message = "Falha ao localizar a URL"
        tracker.tracker_status.sync_status = "error"
        tracker.status_changed.emit(tracker.tracker_status)

        self.assertEqual(tab.pity_values["resonator"].text(), "70 / 80")
        self.assertEqual(tab.pity_bars["resonator"].value(), 70)
        self.assertEqual(tab.guarantee_label.text(), "Garantia: SIM")
        self.assertEqual(tab.status_message_label.text(), "Falha ao localizar a URL")

        tracker.state.guaranteed = None
        tracker.state.recent_convene_details = []
        tracker.state_changed.emit(tracker.state)
        tracker.history_changed.emit([])
        self.assertEqual(tab.guarantee_label.text(), "Garantia: --")
        self.assertEqual(tab.last_five_label.text(), "Nenhum 5★ registrado")
        self.assertEqual(tab.history_table.rowCount(), 0)
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_uses_safe_display_fallbacks_without_pity(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {
                "rarity": 5,
                "name": "Jinhsi",
                "pool": "resonator",
                "timestamp": "2026-09-20T22:31:00Z",
                "pity": 78,
            },
            {
                "quality": 4,
                "item": "Variation",
                "type": "weapon",
                "time": "2026-09-20T22:29:00Z",
            },
            {
                "rank": 3,
                "title": "Originite",
                "gacha_type": "standard_character",
                "date": "2026-09-20",
            },
            {"rarity": 5, "timestamp": "invalid"},
        ]

        tracker.history_changed.emit(records)

        self.assertEqual(tab.history_table.columnCount(), 4)
        self.assertEqual(tab.history_table.horizontalHeaderItem(0).text(), "Raridade")
        self.assertEqual(tab.history_table.item(0, 0).text(), "★★★★★")
        self.assertEqual(tab.history_table.item(0, 1).text(), "Jinhsi")
        self.assertEqual(tab.history_table.item(0, 2).text(), "Resonator")
        self.assertEqual(tab.history_table.item(0, 3).text(), "20/09/2026 22:31")
        self.assertEqual(tab.history_table.item(1, 0).text(), "★★★★")
        self.assertEqual(tab.history_table.item(1, 1).text(), "Variation")
        self.assertEqual(tab.history_table.item(1, 2).text(), "Weapon")
        self.assertEqual(tab.history_table.item(1, 3).text(), "20/09/2026 22:29")
        self.assertEqual(tab.history_table.item(2, 0).text(), "★★★")
        self.assertEqual(tab.history_table.item(2, 1).text(), "Originite")
        self.assertEqual(tab.history_table.item(2, 2).text(), "Standard Character")
        self.assertEqual(tab.history_table.item(2, 3).text(), "20/09/2026 00:00")
        self.assertEqual(tab.history_table.item(3, 1).text(), "Desconhecido")
        self.assertEqual(tab.history_table.item(3, 3).text(), "invalid")
        self.assertNotIn("Pity", [
            tab.history_table.horizontalHeaderItem(index).text()
            for index in range(tab.history_table.columnCount())
        ])
        tracker.history_changed.emit(["invalid", None])
        self.assertEqual(tab.history_table.rowCount(), 0)
        self.assertFalse(tab.history_empty_label.isHidden())
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_keeps_long_items_and_multiple_rows_without_mutation(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        long_name = "A" * 500
        records = [
            {"rarity": 5, "name": long_name, "pool": "resonator", "timestamp": "2026-09-20T22:31:00Z"},
            {"rarity": 4, "name": f"Item {index}", "pool": "weapon", "timestamp": f"2026-09-20T22:{index:02d}:00Z"}
            for index in range(1, 20)
        ]
        original_records = [dict(record) for record in records]

        tracker.history_changed.emit(records)

        self.assertEqual(tab.history_table.columnCount(), 4)
        self.assertEqual(tab.history_table.rowCount(), len(records))
        self.assertEqual(
            tab.history_table.item(tab.history_table.rowCount() - 1, 1).toolTip(),
            long_name,
        )
        self.assertEqual(records, original_records)
        tracker.deleteLater()
        tab.deleteLater()

    def test_empty_history_keeps_four_columns_and_message(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)

        tracker.history_changed.emit([])

        self.assertEqual(tab.history_table.columnCount(), 4)
        self.assertEqual(tab.history_table.rowCount(), 0)
        self.assertEqual(
            tab.history_empty_label.text(),
            "Nenhum registro de Convene disponível.",
        )
        self.assertFalse(tab.history_empty_label.isHidden())
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_summary_uses_existing_records_only(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"rarity": 5, "name": "Five", "pool": "resonator", "timestamp": "2026-09-19T10:00:00Z"},
            {"quality": 4, "item": "Four", "type": "weapon", "time": "2026-09-20T11:00:00Z"},
            {"rank": 3, "title": "Three", "gacha_type": "standard_character", "date": "2026-09-20"},
            {"rarity": 6, "name": "Unknown", "date": "invalid"},
        ]
        original_records = [dict(record) for record in records]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        summary = tab.history_summary_values
        self.assertEqual(summary["five"].text(), "★★★★★ 5★ — 1")
        self.assertEqual(summary["four"].text(), "★★★★ 4★ — 1")
        self.assertEqual(summary["three"].text(), "★★★ 3★ — 1")
        self.assertIn("Three", summary["latest"].text())
        self.assertIn("Standard Character", summary["latest"].text())
        self.assertIn("20/09/2026 00:00", summary["latest"].text())
        self.assertIn("19/09/2026 10:00", summary["period"].text())
        self.assertIn("20/09/2026 00:00", summary["period"].text())
        self.assertEqual(records, original_records)
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_summary_is_empty_without_valid_records_or_dates(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [{"rarity": "unknown", "name": "Item", "date": "invalid"}, "invalid"]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        summary = tab.history_summary_values
        self.assertEqual(summary["five"].text(), "★★★★★ 5★ — 0")
        self.assertEqual(summary["four"].text(), "★★★★ 4★ — 0")
        self.assertEqual(summary["three"].text(), "★★★ 3★ — 0")
        self.assertIn("Item", summary["latest"].text())
        self.assertEqual(summary["period"].text(), "Período indisponível")
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_period_uses_minimum_and_maximum_without_reordering_table(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"name": "20", "rarity": 3, "timestamp": "2026-09-20"},
            {"name": "18", "rarity": 3, "timestamp": "2026-09-18"},
            {"name": "19", "rarity": 3, "timestamp": "2026-09-19"},
        ]
        original_records = [dict(record) for record in records]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        self.assertIn("18/09/2026 00:00", tab.history_summary_values["period"].text())
        self.assertIn("20/09/2026 00:00", tab.history_summary_values["period"].text())
        self.assertEqual(tab.history_table.item(0, 1).text(), "19")
        self.assertEqual(tab.history_table.item(1, 1).text(), "18")
        self.assertEqual(tab.history_table.item(2, 1).text(), "20")
        self.assertEqual(records, original_records)
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_period_ignores_invalid_dates_and_supports_timestamp_formats(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"name": "Invalid", "timestamp": "invalid"},
            {"name": "Numeric", "timestamp": 0},
            {"name": "Numeric String", "timestamp": "86400"},
            {"name": "ISO Local", "timestamp": "2026-09-18T12:00:00"},
            {"name": "ISO Offset", "timestamp": "2026-09-20T12:00:00-03:00"},
        ]
        original_records = [dict(record) for record in records]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        self.assertIn("01/01/1970 00:00", tab.history_summary_values["period"].text())
        self.assertIn("20/09/2026 15:00", tab.history_summary_values["period"].text())
        self.assertEqual(records, original_records)
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_period_is_unavailable_when_all_dates_are_invalid(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"name": "A", "timestamp": "invalid"},
            {"name": "B", "time": None},
            {"name": "C", "date": "unknown"},
        ]
        tracker.history_records = records

        tracker.history_changed.emit(records)

        self.assertEqual(
            tab.history_summary_values["period"].text(),
            "Período indisponível",
        )
        tracker.deleteLater()
        tab.deleteLater()

    def test_tab_reuses_backend_without_owning_destruction(self) -> None:
        tracker = LegacyPityTrackerWidget()
        first_tab = ConveneTrackerTab(tracker)
        second_tab = ConveneTrackerTab(tracker)

        self.assertIs(first_tab.tracker, tracker)
        self.assertIs(second_tab.tracker, tracker)
        self.assertNotIn("closeEvent", ConveneTrackerTab.__dict__)
        first_tab.deleteLater()
        second_tab.deleteLater()
        tracker.deleteLater()

    def test_duplicate_request_does_not_start_second_import(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tracker._import_thread = Mock()
        tracker._import_thread.isRunning.return_value = True
        tracker._request_sync = Mock()

        tracker.request_sync()
        tracker.request_sync()

        tracker._request_sync.assert_not_called()
        tracker.deleteLater()

    def test_invalid_url_emits_status_changed(self) -> None:
        tracker = LegacyPityTrackerWidget()
        statuses: list[object] = []
        tracker.status_changed.connect(statuses.append)

        tracker._start_import(
            "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html"
        )

        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].log_status, "invalid_url")
        tracker.deleteLater()

    def test_initial_history_uses_existing_storage_loader(self) -> None:
        records = [{"timestamp": "2026-09-20", "name": "Jingran", "rarity": 5}]
        with patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load",
            return_value=records,
        ):
            tracker = LegacyPityTrackerWidget()

        self.assertEqual(tracker.history_records, records)
        tracker.deleteLater()


if __name__ == "__main__":
    unittest.main()
