"""Small presentation helpers shared by the Convene views."""

from PySide6.QtWidgets import QProgressBar


def pity_progress_bar(height: int) -> QProgressBar:
    """Create a compact progress bar for a pity value from zero to eighty."""
    progress = QProgressBar()
    progress.setRange(0, 80)
    progress.setValue(0)
    progress.setTextVisible(False)
    progress.setFixedHeight(height)
    return progress
