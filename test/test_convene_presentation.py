import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.convene.convene_tracker_tab import ConveneTrackerTab
from src.wuwa_calculator.app.convene.presentation import pity_progress_bar
from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget

_APPLICATION = QApplication.instance() or QApplication([])


def test_pity_progress_bar_preserves_configurable_convene_heights() -> None:
    legacy_bar = pity_progress_bar(5)
    tab_bar = pity_progress_bar(6)

    for progress, expected_height in ((legacy_bar, 5), (tab_bar, 6)):
        assert progress.minimum() == 0
        assert progress.maximum() == 80
        assert progress.value() == 0
        assert not progress.isTextVisible()
        assert progress.height() == expected_height


def test_convene_views_use_the_shared_pity_progress_builder() -> None:
    tracker = LegacyPityTrackerWidget()
    tab = ConveneTrackerTab(tracker)
    legacy_bar = tracker._make_progress()

    assert legacy_bar.minimum() == 0
    assert legacy_bar.maximum() == 80
    assert legacy_bar.value() == 0
    assert not legacy_bar.isTextVisible()
    assert legacy_bar.height() == 5
    assert len(tab.pity_bars) == 4
    assert all(progress.height() == 6 for progress in tab.pity_bars.values())

    tab.close()
    tracker.shutdown_workers()
    tracker.close()
