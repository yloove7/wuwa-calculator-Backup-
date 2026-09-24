import unittest

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect

from src.wuwa_calculator.app.image_import.image_preview_widget import ImagePreviewWidget
from src.wuwa_calculator.app.styles import theme_config


class ImagePreviewWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.theme = theme_config("", 85, "Auto Wallpaper")

    def setUp(self) -> None:
        self.widget = ImagePreviewWidget(self.theme)
        self.widget.resize(820, 680)
        self.widget.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def test_preview_image_and_null_image_preserve_hint_behavior(self) -> None:
        self.assertFalse(self.widget.grid_hint.isHidden())
        image = QImage(120, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        self.widget.set_preview_image(image)
        self.assertFalse(self.widget._source_pixmap.isNull())
        self.assertTrue(self.widget.grid_hint.isHidden())
        self.assertIsNotNone(self.widget.image_preview.pixmap())

        empty_image = QImage()
        current_pixmap_key = self.widget.image_preview.pixmap().cacheKey()
        self.widget.set_preview_image(empty_image)
        self.assertTrue(self.widget._source_pixmap.isNull())
        self.assertTrue(self.widget.grid_hint.isHidden())
        self.assertEqual(self.widget.image_preview.pixmap().cacheKey(), current_pixmap_key)

    def test_scanning_starts_and_stops_animation(self) -> None:
        self.widget.set_scanning(True)
        self.assertEqual(
            self.widget.scan_animation.state(), QAbstractAnimation.State.Running
        )
        self.widget.set_scanning(False)
        self.assertEqual(
            self.widget.scan_animation.state(), QAbstractAnimation.State.Stopped
        )

    def test_theme_updates_grid_and_scan_line_glow(self) -> None:
        theme = theme_config("", 85, "Ciano Tethys")
        self.widget.set_theme(theme)
        self.assertIs(self.widget.scan_grid._theme, theme)
        effect = self.widget.scan_line.graphicsEffect()
        self.assertIsInstance(effect, QGraphicsDropShadowEffect)
        if not isinstance(effect, QGraphicsDropShadowEffect):
            self.fail("scan line has no drop shadow effect")
        self.assertEqual(effect.color().name(), QColor(theme.primary_neon_color).name())


if __name__ == "__main__":
    unittest.main()
