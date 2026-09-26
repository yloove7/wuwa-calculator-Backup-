import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QPixmap

from src.wuwa_calculator.app.components import circular_pixmap
from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget

_APPLICATION = QApplication.instance() or QApplication([])


def test_circular_pixmap_has_expected_size_and_round_transparency() -> None:
    source = QPixmap(20, 20)
    source.fill(QColor("red"))

    result = circular_pixmap(source, 12, 12)

    assert result.size().width() == 12
    assert result.size().height() == 12
    assert result.toImage().pixelColor(0, 0).alpha() == 0
    assert result.toImage().pixelColor(6, 6).alpha() == 255


def test_circular_pixmap_preserves_null_pixmap_dimensions() -> None:
    result = circular_pixmap(QPixmap(), 12, 12)

    assert result.size().width() == 12
    assert result.size().height() == 12
    assert result.toImage().pixelColor(6, 6).alpha() == 0


def test_legacy_circular_pixmap_wrapper_delegates_to_helper() -> None:
    source = QPixmap(20, 20)
    source.fill(QColor("blue"))

    expected = circular_pixmap(source, 12, 12)
    actual = LegacyPityTrackerWidget._circular_pixmap(source, 12, 12)

    assert actual.toImage() == expected.toImage()
