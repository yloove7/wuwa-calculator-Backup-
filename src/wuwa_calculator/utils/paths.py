"""Canonical project paths for bundled assets and user-generated data."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
ASSETS_ROOT = PROJECT_ROOT / "Assets"
USER_DATA_ROOT = PACKAGE_ROOT / "storage" / "user_data"


def get_asset_path(relative_path: str | Path) -> Path:
    """Return an absolute path for an asset stored at the project root."""
    return ASSETS_ROOT / Path(relative_path)


def get_user_data_path(filename: str | Path) -> Path:
    """Return an absolute path for a generated user-data file."""
    return USER_DATA_ROOT / Path(filename)
