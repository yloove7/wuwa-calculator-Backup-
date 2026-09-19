import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QLabel
    from src.wuwa_calculator.app.components import WuWaKuroBannerCard
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

    def test_history_tab_has_no_central_banner_image(self) -> None:
        from src.wuwa_calculator.app.history_tab import HistoryTab

        tab = HistoryTab()
        banner = tab.findChild(QLabel, "historyBannerPreview")
        self.assertIsNotNone(banner)
        self.assertTrue(banner.pixmap() is None or banner.pixmap().isNull())
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
