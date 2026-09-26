import os
import json
import tempfile
import unittest
from pathlib import Path
from typing import TypeVar
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from src.wuwa_calculator.app.convene.convene_tracker_tab import ConveneTrackerTab
from src.wuwa_calculator.app import pity_tracker
from src.wuwa_calculator.app.pity_tracker import (
    ConveneCaptureContext,
    LegacyPityTrackerWidget,
    TrackerStatus,
)
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager

T = TypeVar("T")


def _required(value: T | None) -> T:
    if value is None:
        raise AssertionError("Expected Qt table item to exist")
    return value


class ConveneTrackerTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_last_sync_timestamp_is_presented_in_kuro_timezone(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        values = (
            "2026-09-23T02:56:22.460553+00:00",
            "2026-09-23T02:56:22Z",
            "2026-09-23T04:56:22+02:00",
        )

        for value in values:
            with self.subTest(value=value):
                tracker.status_changed.emit(TrackerStatus(last_sync_at=value))
                self.assertEqual(
                    tab.status_label.text(),
                    "Última sincronização: 22/09/2026 21:56",
                )

        for value in ("invalid", None):
            with self.subTest(value=value):
                tracker.status_changed.emit(TrackerStatus(last_sync_at=value))
                self.assertEqual(
                    tab.status_label.text(),
                    "Última sincronização: --",
                )

        tracker.deleteLater()
        tab.deleteLater()

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
            "Último 5★: Newest Five · Weapon · 20/09/2026 06:00",
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
                    "Último 5★: Fallback Five · Weapon · 20/09/2026 08:00",
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
        self.assertEqual(tab.guarantee_label.text(), "Sim")
        self.assertEqual(tab.status_message_label.text(), "✕ Não foi possível sincronizar o histórico.")

        tracker.state.guaranteed = None
        tracker.state.recent_convene_details = []
        tracker.state_changed.emit(tracker.state)
        tracker.history_records = []
        tracker.history_changed.emit([])
        self.assertEqual(tab.guarantee_label.text(), "--")
        self.assertEqual(tab.last_five_label.text(), "Nenhum 5★ registrado")
        self.assertEqual(tab.history_table.rowCount(), 0)
        tracker.deleteLater()
        tab.deleteLater()

    def test_history_uses_safe_display_fallbacks_without_pity(self) -> None:
        tracker = LegacyPityTrackerWidget()
        tab = ConveneTrackerTab(tracker)
        records = [
            {"rarity": 5, "timestamp": "invalid"},
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
        self.assertEqual(_required(tab.history_table.horizontalHeaderItem(0)).text(), "Raridade")
        self.assertEqual(_required(tab.history_table.item(0, 0)).text(), "★★★★★")
        self.assertEqual(_required(tab.history_table.item(0, 1)).text(), "Desconhecido")
        self.assertEqual(_required(tab.history_table.item(0, 2)).text(), "--")
        self.assertEqual(_required(tab.history_table.item(0, 3)).text(), "invalid")
        self.assertEqual(_required(tab.history_table.item(1, 0)).text(), "★★★")
        self.assertEqual(_required(tab.history_table.item(1, 1)).text(), "Originite")
        self.assertEqual(_required(tab.history_table.item(1, 2)).text(), "Standard Character")
        self.assertEqual(_required(tab.history_table.item(1, 3)).text(), "20/09/2026 00:00")
        self.assertEqual(_required(tab.history_table.item(2, 0)).text(), "★★★★")
        self.assertEqual(_required(tab.history_table.item(2, 1)).text(), "Variation")
        self.assertEqual(_required(tab.history_table.item(2, 2)).text(), "Weapon")
        self.assertEqual(_required(tab.history_table.item(2, 3)).text(), "20/09/2026 17:29")
        self.assertEqual(_required(tab.history_table.item(3, 1)).text(), "Jinhsi")
        self.assertEqual(_required(tab.history_table.item(3, 3)).text(), "20/09/2026 17:31")
        self.assertNotIn("Pity", [
            _required(tab.history_table.horizontalHeaderItem(index)).text()
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
        ] + [
            {"rarity": 4, "name": f"Item {index}", "pool": "weapon", "timestamp": f"2026-09-20T22:{index:02d}:00Z"}
            for index in range(1, 20)
        ]
        original_records = [dict(record) for record in records]

        tracker.history_changed.emit(records)

        self.assertEqual(tab.history_table.columnCount(), 4)
        self.assertEqual(tab.history_table.rowCount(), len(records))
        self.assertEqual(
            _required(tab.history_table.item(tab.history_table.rowCount() - 1, 1)).toolTip(),
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
            {"quality": 4, "item": "Four", "type": "weapon", "time": "2026-09-19T11:00:00Z"},
            {"rarity": 6, "name": "Unknown", "date": "invalid"},
            {"rank": 3, "title": "Three", "gacha_type": "standard_character", "date": "2026-09-20"},
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
        self.assertIn("19/09/2026 05:00", summary["period"].text())
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
        self.assertEqual(_required(tab.history_table.item(0, 1)).text(), "19")
        self.assertEqual(_required(tab.history_table.item(1, 1)).text(), "18")
        self.assertEqual(_required(tab.history_table.item(2, 1)).text(), "20")
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

        self.assertIn("31/12/1969 19:00", tab.history_summary_values["period"].text())
        self.assertIn("20/09/2026 10:00", tab.history_summary_values["period"].text())
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

        with patch("src.wuwa_calculator.app.pity_tracker.subprocess.Popen") as popen:
            tracker.request_sync()
            tracker.request_sync()

        popen.assert_not_called()
        tracker.deleteLater()

    def test_request_sync_always_launches_powershell_for_a_new_capture(self) -> None:
        existing_capture = ConveneCaptureContext(
            source_url=(
                "https://aki-gm-resources.example/record?player_id=player-a&"
                "record_id=old&svr_id=server&resources_id=pool&lang=en"
            ),
            player_id="player-a",
            record_id="old",
            svr_id="server",
            resources_id="pool",
            lang="en",
            log_path=None,
            log_mtime=None,
            discovered_at="2026-09-24T00:00:00Z",
            discovery_source="client_log",
        )
        existing_log_states = (
            ("valid URL", existing_capture),
            ("expired URL", existing_capture),
            ("invalid URL", ValueError("invalid URL")),
            ("missing URL", FileNotFoundError("missing URL")),
        )
        expected_command = (
            'iwr -UseBasicParsing -Headers @{"User-Agent"="Mozilla/5.0"} '
            "https://raw.githubusercontent.com/wuwatracker/wuwatracker/"
            "747a48b1b994baa9c372a4fb933ea7588428bd4b/import.ps1 | iex"
        )

        for label, log_result in existing_log_states:
            with self.subTest(log_state=label):
                tracker = LegacyPityTrackerWidget()
                process = Mock()
                process.poll.return_value = None
                clipboard = Mock()
                clipboard.text.return_value = "old clipboard URL"
                log_reader_patch = (
                    patch(
                        "src.wuwa_calculator.app.pity_tracker.ClientLogReader.get_capture_context",
                        side_effect=log_result,
                    )
                    if isinstance(log_result, Exception)
                    else patch(
                        "src.wuwa_calculator.app.pity_tracker.ClientLogReader.get_capture_context",
                        return_value=log_result,
                    )
                )
                with (
                    log_reader_patch as read_log,
                    patch(
                        "src.wuwa_calculator.app.pity_tracker.QApplication.clipboard",
                        return_value=clipboard,
                    ),
                    patch(
                        "src.wuwa_calculator.app.pity_tracker.subprocess.Popen",
                        return_value=process,
                    ) as popen,
                ):
                    tracker.request_sync()

                read_log.assert_not_called()
                popen.assert_called_once_with(
                    ["powershell.exe", "-NoExit", "-Command", expected_command],
                    creationflags=pity_tracker.subprocess.CREATE_NEW_CONSOLE,
                )
                self.assertEqual(tracker._clipboard_before_external, "old clipboard URL")
                self.assertIs(tracker._pwsh_process, process)
                tracker._pwsh_poll_timer.stop()
                tracker._pwsh_process = None
                tracker.deleteLater()

    def test_request_sync_launches_with_empty_clipboard(self) -> None:
        tracker = LegacyPityTrackerWidget()
        process = Mock()
        clipboard = Mock()
        clipboard.text.return_value = ""

        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.QApplication.clipboard",
                return_value=clipboard,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.subprocess.Popen",
                return_value=process,
            ) as popen,
        ):
            tracker.request_sync()

        popen.assert_called_once()
        self.assertEqual(tracker._clipboard_before_external, "")
        tracker._pwsh_poll_timer.stop()
        tracker._pwsh_process = None
        tracker.deleteLater()

    def test_new_clipboard_capture_replaces_context_and_keeps_url_literal(self) -> None:
        previous_capture = ConveneCaptureContext(
            source_url="old-url",
            player_id="player-old",
            record_id="old-record",
            svr_id="old-server",
            resources_id="old-pool",
            lang="en",
            log_path=None,
            log_mtime=None,
            discovered_at="2026-09-23T00:00:00Z",
            discovery_source="client_log",
        )
        captured_url = (
            "https://aki-gm-resources.example/record?player_id=504413756&"
            "record_id=newrecord&svr_id=newserver&resources_id=newpool&lang=pt-BR&"
            "trace=a%2Fb"
        )
        tracker = LegacyPityTrackerWidget()
        tracker.last_capture_context = previous_capture
        tracker._clipboard_before_external = "old clipboard URL"
        process = Mock()
        process.poll.return_value = None
        clipboard = Mock()
        clipboard.text.return_value = captured_url
        thread = Mock()
        worker = Mock()

        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.QApplication.clipboard",
                return_value=clipboard,
            ),
            patch("src.wuwa_calculator.app.pity_tracker.QThread", return_value=thread),
            patch(
                "src.wuwa_calculator.app.pity_tracker.PityHistoryImportWorker",
                return_value=worker,
            ) as worker_factory,
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
                return_value=[],
            ),
        ):
            tracker._pwsh_process = process
            tracker._await_wuwatracker_import()

        capture = tracker.last_capture_context
        self.assertIsNotNone(capture)
        assert capture is not None
        self.assertIsNot(capture, previous_capture)
        self.assertEqual(capture.source_url, captured_url)
        self.assertEqual(capture.player_id, "504413756")
        self.assertEqual(capture.record_id, "newrecord")
        self.assertEqual(capture.discovery_source, "external_clipboard")
        self.assertTrue(capture.is_new_capture)
        self.assertEqual(tracker.active_player_id, "504413756")
        worker_factory.assert_called_once_with(captured_url)
        self.assertIsNone(tracker._pwsh_process)
        thread.start.assert_called_once_with()
        tracker._import_thread = None
        tracker._import_worker = None
        tracker.deleteLater()

    def test_current_log_capture_wins_over_restored_player_and_brave(self) -> None:
        context_a = {
            "player_id": "player-a",
            "record_id": "record-a",
            "server_id": "server-a",
            "card_pool_id": "pool-a",
            "language_code": "en",
        }
        current_url = (
            "https://aki-gm-resources.example/record?player_id=playerB&record_id=recordB&"
            "svr_id=serverB&resources_id=poolB&lang=en"
        )
        capture_b = ConveneCaptureContext(
            source_url=current_url,
            player_id="playerB",
            record_id="recordB",
            svr_id="serverB",
            resources_id="poolB",
            lang="en",
            log_path=None,
            log_mtime=None,
            discovered_at="2026-09-24T00:00:00Z",
            discovery_source="client_log",
        )
        thread = Mock()
        worker = Mock()
        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_context",
                return_value=context_a,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
                return_value=[],
            ),
        ):
            tracker = LegacyPityTrackerWidget()
        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ClientLogReader.get_capture_context",
                return_value=capture_b,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.get_brave_cdp_convene_url",
                return_value="stale-player-c-url",
            ) as brave,
            patch("src.wuwa_calculator.app.pity_tracker.QThread", return_value=thread),
            patch(
                "src.wuwa_calculator.app.pity_tracker.PityHistoryImportWorker",
                return_value=worker,
            ) as worker_factory,
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
                return_value=[],
            ),
            patch("src.wuwa_calculator.app.pity_tracker.subprocess.Popen") as popen,
        ):
            tracker._start_saved_log_import()

        self.assertEqual(tracker.active_player_id, "playerB")
        current_capture = tracker.last_capture_context
        self.assertIsNotNone(current_capture)
        assert current_capture is not None
        self.assertEqual(current_capture.source_url, current_url)
        self.assertEqual(tracker.tracker_status.capture_source, "client_log")
        self.assertTrue(tracker.tracker_status.is_new_capture)
        worker_factory.assert_called_once_with(current_url)
        brave.assert_not_called()
        popen.assert_not_called()
        thread.start.assert_called_once_with()
        tracker._import_thread = None
        tracker._import_worker = None
        tracker.deleteLater()

    def test_capture_sequence_a_b_a_marks_returned_a_as_new(self) -> None:
        tracker = LegacyPityTrackerWidget()
        contexts = [
            ConveneCaptureContext(
                source_url=f"url-{player}",
                player_id=player,
                record_id=f"record-{player}",
                svr_id="server",
                resources_id="pool",
                lang="en",
                log_path=None,
                log_mtime=None,
                discovered_at="2026-09-24T00:00:00Z",
                discovery_source="client_log",
            )
            for player in ("A", "B", "A")
        ]

        prepared = [tracker._prepare_capture_context(context) for context in contexts]

        self.assertEqual([capture.player_id for capture in prepared], ["A", "B", "A"])
        self.assertEqual([capture.is_new_capture for capture in prepared], [True, True, True])
        tracker.deleteLater()

    def test_duplicate_capture_remains_an_idempotent_sync_candidate(self) -> None:
        tracker = LegacyPityTrackerWidget()
        capture = ConveneCaptureContext(
            source_url="url-a",
            player_id="A",
            record_id="record-a",
            svr_id="server",
            resources_id="pool",
            lang="en",
            log_path=None,
            log_mtime=1.0,
            discovered_at="2026-09-24T00:00:00Z",
            discovery_source="client_log",
        )
        tracker.last_capture_context = capture
        repeated = tracker._prepare_capture_context(capture)

        self.assertFalse(repeated.is_new_capture)
        tracker.deleteLater()

    def test_missing_native_url_does_not_reuse_restored_context(self) -> None:
        context_a = {
            "player_id": "player-a",
            "record_id": "record-a",
            "server_id": "server-a",
            "card_pool_id": "pool-a",
            "language_code": "en",
        }
        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_context",
                return_value=context_a,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
                return_value=[],
            ),
        ):
            tracker = LegacyPityTrackerWidget()
        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ClientLogReader.get_capture_context",
                side_effect=FileNotFoundError("no current capture"),
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.get_brave_cdp_convene_url",
                return_value="stale-brave-url",
            ) as brave,
            patch("src.wuwa_calculator.app.pity_tracker.subprocess.Popen") as popen,
        ):
            tracker._start_saved_log_import()

        self.assertEqual(tracker.active_player_id, "player-a")
        self.assertIsNone(tracker.last_capture_context)
        self.assertEqual(tracker.tracker_status.log_status, "no_convene_url")
        brave.assert_not_called()
        popen.assert_not_called()
        tracker.deleteLater()

    def test_external_fallback_is_explicit_and_snapshots_clipboard_before_launch(self) -> None:
        old_clipboard = "old clipboard contents"
        clipboard = Mock()
        clipboard.text.return_value = old_clipboard
        with patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_context",
            return_value=None,
        ), patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
            return_value=[],
        ):
            tracker = LegacyPityTrackerWidget()
        process = Mock()

        def launch(*_args, **_kwargs):
            self.assertEqual(tracker._clipboard_before_external, old_clipboard)
            return process

        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ClientLogReader.get_capture_context",
                side_effect=FileNotFoundError("no current capture"),
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.QApplication.clipboard",
                return_value=clipboard,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.subprocess.Popen",
                side_effect=launch,
            ) as popen,
        ):
            tracker._start_saved_log_import()

        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[:3], ["powershell.exe", "-NoExit", "-Command"])
        self.assertEqual(
            command[3],
            'iwr -UseBasicParsing -Headers @{"User-Agent"="Mozilla/5.0"} '
            "https://raw.githubusercontent.com/wuwatracker/wuwatracker/"
            "747a48b1b994baa9c372a4fb933ea7588428bd4b/import.ps1 | iex",
        )
        self.assertNotIn("exit", command[3].casefold())
        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            pity_tracker.subprocess.CREATE_NEW_CONSOLE,
        )
        self.assertIs(tracker._pwsh_process, process)
        self.assertEqual(tracker._clipboard_before_external, old_clipboard)
        tracker._pwsh_poll_timer.stop()
        tracker._pwsh_process = None
        tracker.deleteLater()

    def test_invalid_url_emits_status_changed(self) -> None:
        tracker = LegacyPityTrackerWidget()
        statuses: list[TrackerStatus] = []
        tracker.status_changed.connect(statuses.append)

        tracker._start_import(
            "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html"
        )

        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].log_status, "invalid_url")
        tracker.deleteLater()

    def test_import_rejects_capture_context_from_a_different_url(self) -> None:
        url_a = (
            "https://aki-gm-resources.example/record?player_id=A&record_id=record-A&"
            "svr_id=server&resources_id=pool&lang=en"
        )
        url_b = (
            "https://aki-gm-resources.example/record?player_id=B&record_id=record-B&"
            "svr_id=server&resources_id=pool&lang=en"
        )
        capture_a = ConveneCaptureContext(
            source_url=url_a,
            player_id="A",
            record_id="record-A",
            svr_id="server",
            resources_id="pool",
            lang="en",
            log_path=None,
            log_mtime=None,
            discovered_at="2026-09-24T00:00:00Z",
            discovery_source="client_log",
        )
        with (
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_context",
                return_value=None,
            ),
            patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_for_player",
                return_value=[],
            ),
        ):
            tracker = LegacyPityTrackerWidget()
        statuses: list[TrackerStatus] = []
        tracker.status_changed.connect(statuses.append)

        with patch(
            "src.wuwa_calculator.app.pity_tracker.PityHistoryImportWorker"
        ) as worker_factory:
            tracker._start_import(url_b, capture_context=capture_a)

        worker_factory.assert_not_called()
        self.assertIsNone(tracker.active_player_id)
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].log_status, "invalid_url")
        tracker.deleteLater()

    def test_initial_history_is_empty_without_valid_player_context(self) -> None:
        with patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load",
            side_effect=AssertionError("global history must not feed active tracker"),
        ), patch(
            "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager.load_context",
            return_value=None,
        ):
            tracker = LegacyPityTrackerWidget()
            tab = ConveneTrackerTab(tracker)

        self.assertIsNone(tracker.active_player_id)
        self.assertEqual(tracker.history_records, [])
        self.assertEqual(tracker.state.total_registered, 0)
        self.assertEqual(tab.history_table.rowCount(), 0)
        tab.close()
        tracker.deleteLater()

    def test_invalid_context_and_global_history_never_become_active(self) -> None:
        pulls = [
            {"player_id": "A", "timestamp": "2026-09-01", "pool": "resonator", "name": "A1", "rarity": 5},
            {"player_id": "B", "timestamp": "2026-09-02", "pool": "resonator", "name": "B1", "rarity": 5},
            {"timestamp": "2026-09-03", "pool": "resonator", "name": "legacy", "rarity": 5},
        ]
        invalid_contexts: tuple[object, ...] = (
            None,
            {},
            {"player_id": "", "record_id": "r", "server_id": "s", "card_pool_id": "c", "language_code": "en"},
            {"player_id": True, "record_id": "r", "server_id": "s", "card_pool_id": "c", "language_code": "en"},
            {"player_id": 1.5, "record_id": "r", "server_id": "s", "card_pool_id": "c", "language_code": "en"},
            {"player_id": "bad id", "record_id": "r", "server_id": "s", "card_pool_id": "c", "language_code": "en"},
            {"player_id": "A", "record_id": "r", "server_id": "s", "card_pool_id": "c"},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            for context in invalid_contexts:
                with self.subTest(context=context):
                    payload: dict[str, object] = {"pulls": pulls}
                    if context is not None:
                        payload["convene_context"] = context
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    storage = ConveneStorageManager(path)
                    with patch(
                        "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                        return_value=storage,
                    ):
                        tracker = LegacyPityTrackerWidget()
                        tab = ConveneTrackerTab(tracker)
                    self.assertIsNone(tracker.active_player_id)
                    self.assertEqual(tracker.history_records, [])
                    self.assertEqual(tracker.state.total_registered, 0)
                    self.assertEqual(tab.history_table.rowCount(), 0)
                    self.assertEqual(len(storage.load()), 3)
                    tab.close()
                    tracker.close()

    def test_valid_context_without_owned_pulls_keeps_identity_but_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            storage = ConveneStorageManager(path)
            storage.save_context({
                "player_id": "B",
                "record_id": "record-B",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            })
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "A pull",
                "rarity": 5,
            }], "A")
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ):
                tracker = LegacyPityTrackerWidget()
            self.assertEqual(tracker.active_player_id, "B")
            self.assertEqual(tracker.history_records, [])
            self.assertEqual(tracker.state.total_registered, 0)
            tracker.close()

    def test_missing_context_after_player_switch_reopens_empty_and_preserves_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            storage = ConveneStorageManager(path)
            for player_id, names in (("A", ("A1", "A2")), ("B", ("B1", "B2", "B3"))):
                storage.merge_active_player_with_metadata([
                    {"timestamp": f"2026-09-0{index}T10:00:00Z", "pool": "resonator", "name": name, "rarity": 5}
                    for index, name in enumerate(names, start=1)
                ], player_id)
            storage.merge([{
                "timestamp": "2026-09-05T10:00:00Z",
                "pool": "resonator",
                "name": "legacy",
                "rarity": 5,
            }])
            context = {"player_id": "A", "record_id": "rA", "server_id": "s", "card_pool_id": "c", "language_code": "en"}
            storage.save_context(context)
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ):
                tracker_a = LegacyPityTrackerWidget()
                self.assertEqual([row["name"] for row in tracker_a.history_records], ["A1", "A2"])
                self.assertEqual(tracker_a.state.total_registered, 2)
                tracker_a._activate_player_history("B")
                self.assertEqual([row["name"] for row in tracker_a.history_records], ["B1", "B2", "B3"])
                self.assertEqual(tracker_a.state.total_registered, 3)
                tracker_a.close()

                document = json.loads(path.read_text(encoding="utf-8"))
                document.pop("convene_context", None)
                path.write_text(json.dumps(document), encoding="utf-8")
                reopened = LegacyPityTrackerWidget()
                self.assertIsNone(reopened.active_player_id)
                self.assertEqual(reopened.history_records, [])
                self.assertEqual(reopened.state.total_registered, 0)
                self.assertEqual({row["name"] for row in storage.load()}, {"A1", "A2", "B1", "B2", "B3", "legacy"})
                reopened._activate_player_history("B")
                self.assertEqual({row["name"] for row in reopened.history_records}, {"B1", "B2", "B3"})
                self.assertEqual(reopened.state.total_registered, 3)
                reopened._activate_player_history("A")
                self.assertEqual({row["name"] for row in reopened.history_records}, {"A1", "A2"})
                self.assertEqual(reopened.state.total_registered, 2)
                reopened.close()

    def test_generic_import_without_active_player_keeps_ui_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            source = root / "generic.json"
            source.write_text(json.dumps({"pulls": [{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Orphan import",
                "rarity": 5,
            }]}), encoding="utf-8")
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                return_value=(str(source), "JSON (*.json)"),
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.information",
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._import_json_history()
            self.assertIsNone(tracker.active_player_id)
            self.assertEqual(tracker.history_records, [])
            self.assertEqual(tracker.state.total_registered, 0)
            self.assertEqual(tab.history_table.rowCount(), 0)
            self.assertEqual([row["name"] for row in storage.load()], ["Orphan import"])
            tab.close()
            tracker.close()

    def test_wuwa_import_without_active_player_activates_only_file_player(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            source = root / "wuwa.json"
            source.write_text(json.dumps({
                "playerId": "B",
                "pulls": [{
                    "cardPoolType": 1,
                    "resourceId": 123,
                    "qualityLevel": 5,
                    "name": "B pull",
                    "time": "2026-09-01T10:00:00Z",
                }],
            }), encoding="utf-8")
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                return_value=(str(source), "JSON (*.json)"),
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.information",
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._import_json_history()
            self.assertEqual(tracker.active_player_id, "B")
            self.assertEqual([row["name"] for row in tracker.history_records], ["B pull"])
            self.assertEqual(tracker.state.total_registered, 1)
            self.assertEqual(tab.history_table.rowCount(), 1)
            tab.close()
            tracker.close()

    def test_wuwa_import_without_context_cannot_display_mixed_existing_players(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z", "pool": "resonator",
                "name": "A pull", "rarity": 5,
            }], "A")
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-02T10:00:00Z", "pool": "resonator",
                "name": "B pull", "rarity": 5,
            }], "B")
            storage.merge([{
                "timestamp": "2026-09-03T10:00:00Z", "pool": "resonator",
                "name": "legacy", "rarity": 5,
            }])
            source = root / "wuwa.json"
            source.write_text(json.dumps({
                "playerId": "B",
                "pulls": [{
                    "cardPoolType": 1,
                    "resourceId": 124,
                    "qualityLevel": 5,
                    "name": "Imported B",
                    "time": "2026-09-04T10:00:00Z",
                }],
            }), encoding="utf-8")
            before = storage.path.read_bytes()
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                return_value=(str(source), "JSON (*.json)"),
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.warning",
            ) as warning:
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._import_json_history()
            warning.assert_called_once()
            self.assertIsNone(tracker.active_player_id)
            self.assertEqual(tracker.history_records, [])
            self.assertEqual(tracker.state.total_registered, 0)
            self.assertEqual(tab.history_table.rowCount(), 0)
            self.assertEqual(storage.path.read_bytes(), before)
            tab.close()
            tracker.close()

    def test_tethys_import_keeps_legacy_pull_unowned_and_reports_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            storage.save_context({
                "player_id": "A",
                "record_id": "record-A",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            })
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "Owned A pull",
                "rarity": 5,
            }], "A")
            source = root / "tethys.json"
            source.write_text(json.dumps({
                "format": "tethys_convene_history",
                "version": 1,
                "pulls": [{
                    "timestamp": "2026-09-02T10:00:00Z",
                    "pool": "resonator",
                    "name": "Legacy import",
                    "rarity": 4,
                }],
            }), encoding="utf-8")
            with (
                patch(
                    "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                    return_value=storage,
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                    return_value=(str(source), "JSON (*.json)"),
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.information",
                ) as information,
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._import_json_history()

            self.assertEqual(tracker.active_player_id, "A")
            self.assertEqual([row["name"] for row in tracker.history_records], ["Owned A pull"])
            self.assertEqual(
                {row.get("player_id") for row in storage.load()},
                {"A", None},
            )
            information.assert_called_once()
            self.assertIn("tethys_convene_history", information.call_args.args[2])
            self.assertIn("Novos registros: 1", information.call_args.args[2])
            tab.close()
            tracker.close()

    def test_active_player_export_uses_backend_and_preserves_player_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "A pull",
                "rarity": 5,
            }], "A")
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-02T10:00:00Z",
                "pool": "weapon",
                "name": "B pull",
                "rarity": 5,
            }], "B")
            storage.save_context({
                "player_id": "A",
                "record_id": "record-A",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            })
            destination = root / "export.json"
            with (
                patch(
                    "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                    return_value=storage,
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getSaveFileName",
                    return_value=(str(destination), "JSON (*.json)"),
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.information",
                ) as information,
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._export_json_history()

            exported = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(tracker.active_player_id, "A")
            self.assertEqual(exported["playerId"], "A")
            self.assertEqual([pull["name"] for pull in exported["pulls"]], ["A pull"])
            information.assert_called_once()
            tab.close()
            tracker.close()

    def test_import_and_export_dialog_cancellation_does_not_call_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = ConveneStorageManager(Path(directory) / "history.json")
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ):
                tracker = LegacyPityTrackerWidget()
            tracker.active_player_id = "A"
            tab = ConveneTrackerTab(tracker)
            with (
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                    return_value=("", ""),
                ),
                patch.object(tracker, "import_history_json") as import_history,
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getSaveFileName",
                    return_value=("", ""),
                ),
                patch.object(tracker, "export_history_json") as export_history,
            ):
                tab._import_json_history()
                tab._export_json_history()

            import_history.assert_not_called()
            export_history.assert_not_called()
            tab.close()
            tracker.close()

    def test_import_error_is_reported_without_refreshing_backend_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = ConveneStorageManager(root / "history.json")
            source = root / "invalid.json"
            source.write_text("{ invalid", encoding="utf-8")
            with (
                patch(
                    "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                    return_value=storage,
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getOpenFileName",
                    return_value=(str(source), "JSON (*.json)"),
                ),
                patch(
                    "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.warning",
                ) as warning,
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                original_records = tracker.history_records
                tab._import_json_history()

            warning.assert_called_once()
            self.assertIs(tracker.history_records, original_records)
            self.assertEqual(storage.load(), [])
            tab.close()
            tracker.close()

    def test_export_without_active_player_does_not_use_saved_context_or_global_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.json"
            payload = {
                "convene_context": {"player_id": "bad id", "record_id": "r", "server_id": "s", "card_pool_id": "c", "language_code": "en"},
                "pulls": [
                    {"player_id": "A", "timestamp": "2026-09-01T10:00:00Z", "pool": "resonator", "name": "A1", "rarity": 5},
                    {"player_id": "B", "timestamp": "2026-09-02T10:00:00Z", "pool": "resonator", "name": "B1", "rarity": 5},
                    {"timestamp": "2026-09-03T10:00:00Z", "pool": "resonator", "name": "legacy", "rarity": 5},
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            storage = ConveneStorageManager(path)
            destination = root / "export.json"
            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QFileDialog.getSaveFileName",
                return_value=(str(destination), "JSON (*.json)"),
            ), patch(
                "src.wuwa_calculator.app.convene.convene_tracker_tab.QMessageBox.warning",
            ) as warning:
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                tab._export_json_history()
            self.assertIsNone(tracker.active_player_id)
            self.assertEqual(tracker.history_records, [])
            warning.assert_called_once()
            self.assertFalse(destination.exists())
            self.assertEqual(len(storage.load()), 3)
            tab.close()
            tracker.close()

    def test_tracker_and_table_follow_active_player_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = ConveneStorageManager(Path(directory) / "history.json")
            context = {
                "player_id": "A",
                "record_id": "record-A",
                "server_id": "server",
                "card_pool_id": "pool",
                "language_code": "en",
            }
            storage.save_context(context)
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-01T10:00:00Z",
                "pool": "resonator",
                "name": "A pull",
                "rarity": 3,
            }], "A")
            storage.save_context({**context, "player_id": "B", "record_id": "record-B"})
            storage.merge_active_player_with_metadata([{
                "timestamp": "2026-09-02T10:00:00Z",
                "pool": "resonator",
                "name": "B pull",
                "rarity": 3,
            }], "B")

            with patch(
                "src.wuwa_calculator.app.pity_tracker.ConveneStorageManager",
                return_value=storage,
            ):
                tracker = LegacyPityTrackerWidget()
                tab = ConveneTrackerTab(tracker)
                self.assertEqual(tracker.active_player_id, "B")
                self.assertEqual([row["name"] for row in tracker.history_records], ["B pull"])
                self.assertEqual(tracker.state.total_registered, 1)
                self.assertEqual(tab.history_table.rowCount(), 1)

                tracker._activate_player_history("A")
                self.assertEqual([row["name"] for row in tracker.history_records], ["A pull"])
                self.assertEqual(tracker.state.total_registered, 1)
                self.assertEqual(tab.history_table.rowCount(), 1)

                tab.close()
                tracker.close()


if __name__ == "__main__":
    unittest.main()
