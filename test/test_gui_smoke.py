import os
import sys
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QEvent, QIODevice, Qt
from PySide6.QtGui import QImage, QImageWriter, QKeyEvent, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtTest import QTest
from src.wuwa_calculator.app.components import WuWaKuroBannerCard
from src.wuwa_calculator.app.capture.worker import WorkerCapturaNativa
from src.wuwa_calculator.app.multimedia.dps_simulation_panel import (
    CombatFrameGate,
    CombatStateMachine,
    DamageDetectionTracker,
    DpsSimulationPanel,
    LiveDamageAnalysisWorker,
)
from src.wuwa_calculator.app.multimedia.history_video_player import HistoryVideoPlayer


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_banner_card_renders_local_bytes(self) -> None:
        image = QImage(1920, 1080, QImage.Format.Format_RGB32)
        image.fill(0x224466)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        QImageWriter(buffer, b"PNG").write(image)

        card = WuWaKuroBannerCard(
            character_name="Qingxiao",
            image_bytes=bytes(buffer.data().data()),
            end_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(card.height(), 440)
        self.assertEqual(card.width(), card.img_label.width())
        self.assertGreater(card.width(), 0)
        self.assertEqual(card.img_label.height(), 440)
        pixmap = card.img_label.pixmap()
        self.assertIsNotNone(pixmap)
        if pixmap is None:
            self.fail("banner label has no pixmap")
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.height(), 440)
        self.assertLessEqual(pixmap.width(), 960)
        hologram_timer = card.hologram_timer
        countdown_timer = card.timer
        card.hologram_phase = 0.47
        card.hologram_overlay.setPixmap(QPixmap(8, 8))
        base_pixmap = card.img_label.pixmap()
        card.set_performance_mode(True)
        self.assertFalse(hologram_timer.isActive())
        self.assertTrue(countdown_timer.isActive())
        self.assertEqual(card.hologram_phase, 0.0)
        self.assertTrue(card.hologram_overlay.isHidden())
        overlay_pixmap = card.hologram_overlay.pixmap()
        self.assertTrue(overlay_pixmap is None or overlay_pixmap.isNull())
        self.assertEqual(card.img_label.pixmap().cacheKey(), base_pixmap.cacheKey())
        card.set_performance_mode(False)
        self.assertTrue(hologram_timer.isActive())
        self.assertTrue(countdown_timer.isActive())
        self.assertFalse(card.hologram_overlay.isHidden())
        self.assertNotEqual(card.hologram_phase, 0.47)
        self.assertIs(card.hologram_timer, hologram_timer)
        self.assertIs(card.timer, countdown_timer)
        card.deleteLater()

    def test_video_player_builds_without_video_surface(self) -> None:
        player = HistoryVideoPlayer()

        self.assertIsNone(player._video_widget)
        self.assertEqual(player.progress_slider.minimum(), 0)
        self.assertEqual(player.progress_slider.maximum(), 0)
        self.assertFalse(player.play_button.isEnabled())
        player.close()

    def _show_fullscreen_player(self, player: HistoryVideoPlayer):
        player.show()
        self.application.processEvents()
        surface = player.video_surface
        player.enter_fullscreen()
        self.application.processEvents()
        self.assertTrue(surface.isFullScreen())
        return surface

    @staticmethod
    def _send_space(widget: QWidget) -> QKeyEvent:
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Space,
            Qt.KeyboardModifier.NoModifier,
        )
        event.ignore()
        QApplication.sendEvent(widget, event)
        return event

    def test_video_surface_is_created_once_on_explicit_use(self) -> None:
        player = HistoryVideoPlayer()

        self.assertIsNone(player._video_widget)
        surface = player.video_surface

        self.assertIs(player._video_widget, surface)
        self.assertIs(player.video_surface, surface)
        self.assertIs(player.media_player.videoOutput(), surface)
        player.close()

    def test_fullscreen_state_tracks_qt_surface_transitions(self) -> None:
        player = HistoryVideoPlayer()
        surface = player.video_surface

        self.assertFalse(surface.isFullScreen())
        self.assertFalse(player._is_fullscreen)

        for _ in range(2):
            player.enter_fullscreen()
            self.application.processEvents()
            self.assertTrue(surface.isFullScreen())
            self.assertTrue(player._is_fullscreen)
            self.assertEqual(player.video_stack.indexOf(surface), -1)

            player.exit_fullscreen()
            self.application.processEvents()
            self.assertFalse(surface.isFullScreen())
            self.assertFalse(player._is_fullscreen)
            self.assertGreaterEqual(player.video_stack.indexOf(surface), 0)

        self.assertIs(player.video_surface, surface)
        player.close()

    def test_fullscreen_request_without_qt_confirmation_keeps_normal_state(self) -> None:
        player = HistoryVideoPlayer()
        surface = player.video_surface

        with patch.object(QVideoWidget, "setFullScreen", autospec=True):
            player.enter_fullscreen()

        self.assertFalse(surface.isFullScreen())
        self.assertFalse(player._is_fullscreen)
        self.assertGreaterEqual(player.video_stack.indexOf(surface), 0)
        player.close()

    def test_fullscreen_signal_does_not_override_qt_widget_state(self) -> None:
        player = HistoryVideoPlayer()
        surface = player.video_surface

        player._on_video_fullscreen_changed(True)

        self.assertFalse(surface.isFullScreen())
        self.assertFalse(player._is_fullscreen)
        player.close()

    def test_enter_fullscreen_does_not_create_lazy_surface_for_state_check(self) -> None:
        player = HistoryVideoPlayer()

        player.enter_fullscreen()

        self.assertIsNone(player._video_widget)
        self.assertFalse(player._is_fullscreen)
        player.close()

    def test_normal_seek_bar_click_updates_position(self) -> None:
        player = HistoryVideoPlayer()
        player.duration_ms = 10_000
        player.video_path = "diagnostic.mp4"
        slider = player.progress_slider
        slider.setRange(0, player.duration_ms)
        slider.resize(500, 36)
        slider.show()
        self.application.processEvents()
        click_point = slider.rect().center()

        with patch.object(QMediaPlayer, "setPosition", autospec=True) as set_position:
            QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=click_point)

        self.assertGreater(slider.value(), 0)
        set_position.assert_called_once_with(slider.value())
        self.assertFalse(player._is_seeking)
        player.close()

    def test_fullscreen_space_toggles_pause_and_resume(self) -> None:
        player = HistoryVideoPlayer()
        surface = self._show_fullscreen_player(player)
        player.video_path = "diagnostic.mp4"
        with (
            patch.object(
                QMediaPlayer,
                "playbackState",
                autospec=True,
                return_value=QMediaPlayer.PlaybackState.PlayingState,
            ),
            patch.object(QMediaPlayer, "pause", autospec=True) as pause,
            patch.object(player, "_ensure_audio_output"),
        ):
            event = self._send_space(surface)
            self.assertTrue(event.isAccepted())
            pause.assert_called_once_with()

        with (
            patch.object(
                QMediaPlayer,
                "playbackState",
                autospec=True,
                return_value=QMediaPlayer.PlaybackState.PausedState,
            ),
            patch.object(QMediaPlayer, "play", autospec=True) as play,
            patch.object(player, "_ensure_audio_output"),
        ):
            event = self._send_space(surface)
            self.assertTrue(event.isAccepted())
            play.assert_called_once_with()
        player.close()

    def test_fullscreen_space_does_not_seek_or_change_position(self) -> None:
        player = HistoryVideoPlayer()
        surface = self._show_fullscreen_player(player)
        player.video_path = "diagnostic.mp4"

        with (
            patch.object(
                QMediaPlayer,
                "playbackState",
                autospec=True,
                return_value=QMediaPlayer.PlaybackState.PlayingState,
            ),
            patch.object(QMediaPlayer, "position", autospec=True, return_value=4321),
            patch.object(QMediaPlayer, "setPosition", autospec=True) as set_position,
            patch.object(QMediaPlayer, "pause", autospec=True) as pause,
        ):
            event = self._send_space(surface)

            self.assertTrue(event.isAccepted())
            pause.assert_called_once_with()
            set_position.assert_not_called()
            self.assertEqual(player.media_player.position(), 4321)
        player.close()

    def test_fullscreen_contains_no_custom_controls(self) -> None:
        player = HistoryVideoPlayer()
        surface = self._show_fullscreen_player(player)

        self.assertIsNone(player.findChild(QWidget, "fullscreenOverlay"))
        for attribute in (
            "fullscreen_overlay",
            "fullscreen_progress",
            "fullscreen_play_button",
            "fullscreen_time_label",
            "fullscreen_volume",
            "fullscreen_exit_button",
            "_fullscreen_hide_timer",
            "_fullscreen_overlay_animation",
        ):
            self.assertFalse(hasattr(player, attribute), attribute)
        self.assertIs(player.media_player.videoOutput(), surface)
        player.close()

    def test_escape_exits_fullscreen_and_restores_video_to_stack(self) -> None:
        player = HistoryVideoPlayer()
        surface = self._show_fullscreen_player(player)
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )

        QApplication.sendEvent(surface, event)
        self.application.processEvents()

        self.assertTrue(event.isAccepted())
        self.assertFalse(surface.isFullScreen())
        self.assertGreaterEqual(player.video_stack.indexOf(surface), 0)
        player.close()

    def test_repeated_fullscreen_transitions_reuse_the_video_widget(self) -> None:
        player = HistoryVideoPlayer()
        surface = player.video_surface
        player.video_path = "diagnostic.mp4"
        original_stack_count = player.video_stack.count()

        with (
            patch.object(QMediaPlayer, "playbackState", autospec=True,
                         return_value=QMediaPlayer.PlaybackState.PausedState),
            patch.object(QMediaPlayer, "play", autospec=True) as play,
            patch.object(QMediaPlayer, "pause", autospec=True) as pause,
        ):
            for _ in range(3):
                player.enter_fullscreen()
                self.application.processEvents()
                self.assertTrue(surface.isFullScreen())
                self.assertIs(player.media_player.videoOutput(), surface)
                self.assertEqual(player.video_stack.indexOf(surface), -1)

                player.exit_fullscreen()
                self.application.processEvents()
                self.assertFalse(surface.isFullScreen())
                self.assertIs(player.media_player.videoOutput(), surface)
                self.assertGreaterEqual(player.video_stack.indexOf(surface), 0)
                self.assertEqual(player.video_stack.count(), original_stack_count)

        self.assertIs(player.video_surface, surface)
        play.assert_not_called()
        pause.assert_not_called()
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
        self.assertIs(player.video_stack.currentWidget(), player._video_placeholder)
        player.close()

    def test_history_tab_has_no_central_banner_image(self) -> None:
        from src.wuwa_calculator.app.history_tab import HistoryTab

        tab = HistoryTab()
        banner = tab.findChild(QLabel, "historyBannerPreview")
        self.assertIsNotNone(banner)
        if banner is None:
            self.fail("history banner preview label was not created")
        pixmap = banner.pixmap()
        self.assertTrue(pixmap is None or pixmap.isNull())
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

    def test_performance_mode_suppresses_automatic_dps_but_keeps_explicit_analysis(
        self,
    ) -> None:
        player = HistoryVideoPlayer()
        panel = DpsSimulationPanel(player)
        started: list[str] = []
        stopped: list[bool] = []
        worker = LiveDamageAnalysisWorker("recording.mp4", 0.0)
        with patch.object(
            panel,
            "_start_live_analysis",
            side_effect=lambda video_path: started.append(video_path),
        ), patch.object(
            panel,
            "_stop_live_analysis",
            side_effect=lambda: stopped.append(True) or True,
        ):
            panel.set_performance_mode(True)
            panel._on_video_loaded("recording.mp4")
            self.assertEqual(started, [])

            # Selecting the video analysis source is an explicit user action.
            player.video_path = "recording.mp4"
            panel._switch_to_video_mode()
            self.assertEqual(started, ["recording.mp4"])

            panel.set_performance_mode(False)
            panel.live_worker = worker
            panel.set_performance_mode(True)
            self.assertEqual(stopped, [True, True])
            panel.set_performance_mode(False)
            self.assertEqual(started, ["recording.mp4"])
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

    def test_learning_rules_start_with_blocked_screen_knowledge(self) -> None:
        from src.wuwa_calculator.app.capture.learning import classify_screen_text

        self.assertTrue(classify_screen_text("Carregando 75%")['loading'])
        self.assertTrue(classify_screen_text("Recompensas Obtidas")['reward_screen'])
        self.assertTrue(classify_screen_text("Desafio Concluído")['completion'])

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
        from src.wuwa_calculator.app.multimedia.dps_simulation_panel import GameWindowGuard

        fake_win32gui = types.ModuleType("win32gui")
        fake_win32gui.__dict__.update({
            "IsWindowVisible": lambda hwnd: True,
            "GetWindowText": lambda hwnd: {
                101: "Wuthering Waves",
                202: "Discord",
            }[hwnd],
            "GetClassName": lambda hwnd: {
                101: "UnrealWindow",
                202: "Chrome_WidgetWin_1",
            }[hwnd],
            "GetWindowRect": lambda hwnd: {
                101: (0, 0, 1280, 720),
                202: (0, 0, 1920, 1080),
            }[hwnd],
            "EnumWindows": lambda callback, _extra: [
                callback(101, _extra),
                callback(202, _extra),
            ],
            "GetForegroundWindow": lambda: 202,
        })

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
        from src.wuwa_calculator.app.multimedia.dps_simulation_panel import GameWindowGuard

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

        from src.wuwa_calculator.app.multimedia.dps_simulation_panel import WorkerCapturaNativa

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
