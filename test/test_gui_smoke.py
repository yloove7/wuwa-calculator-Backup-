import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QLabel
    from src.wuwa_calculator.app.components import WuWaKuroBannerCard
    from src.wuwa_calculator.app.capture.worker import WorkerCapturaNativa
    from src.wuwa_calculator.app.dps_simulation_panel import (
        CombatFrameGate,
        CombatStateMachine,
        DamageDetectionTracker,
        DpsSimulationPanel,
        LiveDamageAnalysisWorker,
    )
    from src.wuwa_calculator.app.history_video_player import HistoryVideoPlayer
except (ImportError, ModuleNotFoundError):
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 indisponivel")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_banner_card_renders_local_bytes(self) -> None:
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        image.fill(0x224466)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")

        card = WuWaKuroBannerCard(
            character_name="Qingxiao",
            image_bytes=bytes(buffer.data()),
            end_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(card.height(), 440)
        self.assertEqual(card.width(), card.img_label.width())
        self.assertGreater(card.width(), 0)
        self.assertEqual(card.img_label.height(), 440)
        self.assertFalse(card.img_label.pixmap().isNull())
        card.deleteLater()

    def test_video_player_builds_without_media_backend(self) -> None:
        player = HistoryVideoPlayer()

        self.assertEqual(player.progress_slider.minimum(), 0)
        self.assertEqual(player.progress_slider.maximum(), 0)
        self.assertFalse(player.play_button.isEnabled())
        player.close()

    def test_video_player_renders_live_preview_page(self) -> None:
        player = HistoryVideoPlayer()
        image = QImage(64, 36, QImage.Format.Format_RGB888)
        image.fill(0x336699)

        player.set_live_capture_mode(True)
        player.set_live_preview(image)

        self.assertIs(player.video_stack.currentWidget(), player.live_preview)
        self.assertFalse(player.live_preview.pixmap().isNull())
        player.set_live_capture_mode(False)
        self.assertIs(player.video_stack.currentWidget(), player.video_surface)
        player.close()

    def test_history_tab_has_no_central_banner_image(self) -> None:
        from src.wuwa_calculator.app.history_tab import HistoryTab

        tab = HistoryTab()
        banner = tab.findChild(QLabel, "historyBannerPreview")
        self.assertIsNotNone(banner)
        self.assertTrue(banner.pixmap() is None or banner.pixmap().isNull())
        tab.deleteLater()

    def test_analysis_toggle_tracks_live_source_state(self) -> None:
        player = HistoryVideoPlayer()
        panel = DpsSimulationPanel(player)
        self.assertEqual(panel.modo_analise, "VIDEO")
        self.assertEqual(panel.analysis_source.count(), 3)
        self.assertEqual(panel.analysis_source.itemText(0), "Vídeo Local (MP4)")
        self.assertEqual(panel.analysis_source.itemText(1), "Ao Vivo (Captura nativa por HWND)")
        self.assertEqual(panel.analysis_source.itemText(2), "Teste: qualquer jogo em foco (League of Legends™ Client)")
        self.assertEqual(panel.analysis_source.currentIndex(), 0)

        panel._toggle_live_analysis()

        self.assertEqual(panel.modo_analise, "LIVE")
        self.assertTrue(player.media_toolbar.isHidden())
        self.assertTrue(panel.skip_intro_time.isHidden())

        panel._switch_to_video_mode()

        self.assertFalse(player.media_toolbar.isHidden())
        self.assertFalse(panel.skip_intro_time.isHidden())
        panel.deleteLater()
        player.close()

    def test_damage_tracker_rejects_persistent_hud_coordinates(self) -> None:
        tracker = DamageDetectionTracker()

        self.assertTrue(tracker.accept(400, 300, 20, 20, 0.0))
        self.assertFalse(tracker.accept(400, 300, 20, 20, 0.4))
        self.assertFalse(tracker.accept(400, 300, 20, 20, 1.1))

        tracker.expire(2.0)
        self.assertTrue(tracker.accept(400, 300, 20, 20, 2.0))

    def test_damage_event_tracker_confirms_and_deduplicates_hits(self) -> None:
        from src.wuwa_calculator.app.capture.damage_events import DamageEventTracker

        tracker = DamageEventTracker()
        candidate = (1520, 640, 360, 42, 18, 0.22, 0.76)
        self.assertEqual(tracker.update([candidate], 0.0), [])
        self.assertEqual(tracker.update([candidate], 0.08), [candidate])
        self.assertEqual(tracker.update([candidate], 0.16), [])

    def test_damage_event_tracker_keeps_close_different_values_separate(self) -> None:
        from src.wuwa_calculator.app.capture.damage_events import DamageEventTracker

        tracker = DamageEventTracker()
        first = (1200, 600, 360, 32, 16, 0.30, 0.94)
        second = (850, 628, 362, 30, 16, 0.30, 0.94)
        self.assertEqual(tracker.update([first, second], 0.0), [first, second])

    def test_combat_gate_blocks_black_and_static_frames(self) -> None:
        import numpy as np

        self.assertEqual(LiveDamageAnalysisWorker._combat_roi(1000, 1000), (150, 900, 30, 970))
        gate = CombatFrameGate()
        black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(gate.allow(black_frame, 0.0))

    def test_combat_state_pauses_after_three_seconds_without_damage(self) -> None:
        state = CombatStateMachine()

        self.assertEqual(state.update(0.0, True), ("EM_COMBATE", True))
        self.assertEqual(state.update(3.1, False), ("FORA_DE_COMBATE", True))
        self.assertAlmostEqual(state.active_seconds(3.1), 0.0)
        self.assertEqual(state.update(8.0, True), ("EM_COMBATE", True))
        self.assertAlmostEqual(state.active_seconds(9.0), 1.0)

    def test_combat_state_suspends_while_map_is_open(self) -> None:
        state = CombatStateMachine()

        state.update(0.0, True)
        self.assertEqual(state.set_map_open(True), ("MAPA_ABERTO", True))
        self.assertEqual(state.update(4.0, True), ("MAPA_ABERTO", False))
        self.assertEqual(state.set_map_open(False), ("EXPLORACAO", True))
        self.assertEqual(state.update(5.0, True), ("EM_COMBATE", True))

    def test_ui_anchors_classify_result_and_pre_combat_screens(self) -> None:
        import numpy as np

        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)

        def completion_ocr(_frame):
            return [([], "Desafio Concluído", 0.95)], None

        def pre_combat_ocr(_frame):
            return [([], "Relatório ambiental", 0.95)], None

        self.assertEqual(
            WorkerCapturaNativa._read_ui_anchors(frame, completion_ocr)[:2],
            (True, False),
        )
        self.assertEqual(
            WorkerCapturaNativa._read_ui_anchors(frame, pre_combat_ocr)[:2],
            (False, True),
        )

        def reward_ocr(_frame):
            return [([], "Recompensas Obtidas", 0.95)], None

        self.assertEqual(
            WorkerCapturaNativa._read_ui_anchors(frame, reward_ocr)[:3],
            (False, False, True),
        )

        def login_ocr(_frame):
            return [([], "Iniciar Jogo Servidor América", 0.95)], None

        def loading_ocr(_frame):
            return [([], "Carregando 75%", 0.95)], None

        def shader_ocr(_frame):
            return [([], "Compiling Shaders", 0.95)], None

        def update_ocr(_frame):
            return [([], "Checking Updates 12 MB/s", 0.95)], None

        self.assertTrue(WorkerCapturaNativa._read_ui_anchors(frame, login_ocr)[3])
        self.assertTrue(WorkerCapturaNativa._read_ui_anchors(frame, loading_ocr)[4])
        self.assertTrue(WorkerCapturaNativa._read_ui_anchors(frame, shader_ocr)[4])
        self.assertTrue(WorkerCapturaNativa._read_ui_anchors(frame, update_ocr)[4])

    def test_map_ocr_rejects_hardware_overlay_terms(self) -> None:
        import numpy as np

        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)

        def map_ocr(_frame):
            return [([], "Penitent's End", 0.95)], None

        def overlay_ocr(_frame):
            return [([], "CPU 65% FPS 120", 0.95)], None

        self.assertEqual(
            WorkerCapturaNativa._read_map_name(frame, map_ocr),
            "Penitent's End",
        )
        self.assertEqual(WorkerCapturaNativa._read_map_name(frame, overlay_ocr), "")

    def test_reward_state_restarts_as_a_clean_battle(self) -> None:
        state = CombatStateMachine()

        state.update(0.0, True)
        self.assertEqual(state.set_reward_screen(), ("TELA_DE_RECOMPENSA", True))
        self.assertEqual(state.resume_new_battle(), ("EXPLORACAO", True))
        self.assertEqual(state.update(1.0, True), ("EM_COMBATE", True))

    def test_game_window_guard_only_allows_foreground_game(self) -> None:
        import sys
        import types

        from src.wuwa_calculator.app.dps_simulation_panel import GameWindowGuard

        fake_win32gui = types.SimpleNamespace(
            IsWindowVisible=lambda hwnd: True,
            GetWindowText=lambda hwnd: {
                101: "Wuthering Waves",
                202: "Discord",
            }[hwnd],
            GetClassName=lambda hwnd: {
                101: "UnrealWindow",
                202: "Chrome_WidgetWin_1",
            }[hwnd],
            GetWindowRect=lambda hwnd: {
                101: (0, 0, 1280, 720),
                202: (0, 0, 1920, 1080),
            }[hwnd],
            EnumWindows=lambda callback, _extra: [
                callback(101, _extra),
                callback(202, _extra),
            ],
            GetForegroundWindow=lambda: 202,
        )

        original = sys.modules.get("win32gui")
        sys.modules["win32gui"] = fake_win32gui
        try:
            self.assertIsNone(GameWindowGuard().locate())
        finally:
            if original is None:
                sys.modules.pop("win32gui", None)
            else:
                sys.modules["win32gui"] = original

    def test_game_window_guard_recognizes_league_game_and_client_titles(self) -> None:
        from src.wuwa_calculator.app.dps_simulation_panel import GameWindowGuard

        guard = GameWindowGuard()

        self.assertTrue(guard._is_game_window("League of Legends", "RiotWindow"))
        self.assertTrue(
            guard._is_game_window("League of Legends™ Client", "RiotWindow")
        )
        self.assertTrue(
            guard._is_game_window("League of Legends TM Client", "RiotWindow")
        )
        self.assertTrue(guard._is_league_window("League of Legends"))
        self.assertTrue(guard._is_league_window("League of Legends (TM) Client"))

    def test_capture_debug_log_is_available_in_all_modes(self) -> None:
        import io
        from contextlib import redirect_stdout

        from src.wuwa_calculator.app.dps_simulation_panel import WorkerCapturaNativa

        worker_debug = WorkerCapturaNativa(capture_mode="GENERIC_WINDOW")
        worker_standard = WorkerCapturaNativa(capture_mode="WUTHERING_WAVES")

        debug_buffer = io.StringIO()
        standard_buffer = io.StringIO()

        with redirect_stdout(debug_buffer):
            worker_debug._debug_log("janela ativa detectada")
        with redirect_stdout(standard_buffer):
            worker_standard._debug_log("janela ativa detectada")

        self.assertIn("janela ativa detectada", debug_buffer.getvalue())
        self.assertIn("janela ativa detectada", standard_buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
