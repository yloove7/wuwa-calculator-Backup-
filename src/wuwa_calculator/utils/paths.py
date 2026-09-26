"""Canonical project paths for bundled assets and user-generated data."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
ASSETS_ROOT = PROJECT_ROOT / "Assets"
LEGACY_USER_DATA_ROOT = PACKAGE_ROOT / "storage" / "user_data"
LEGACY_DATA_ROOT = PACKAGE_ROOT / "data"
LEGACY_STORAGE_ROOT = PACKAGE_ROOT / "storage"


def get_user_data_root() -> Path:
    """Return the per-user application data directory for this platform."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "Tethys"
        return Path.home() / "AppData" / "Local" / "Tethys"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Tethys"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "tethys"
USER_DATA_ROOT = get_user_data_root()


def get_asset_path(relative_path: str | Path) -> Path:
    """Return an absolute path for an asset stored at the project root."""
    return ASSETS_ROOT / Path(relative_path)


def get_user_data_path(filename: str | Path) -> Path:
    """Return an absolute path for a generated user-data file."""
    return USER_DATA_ROOT / Path(filename)


def get_legacy_user_data_path(filename: str | Path) -> Path:
    """Return the old in-package location for data not migrated yet."""
    return LEGACY_USER_DATA_ROOT / Path(filename)


def copy_legacy_user_data_file(source: Path, destination: Path) -> bool:
    """Copy a legacy user-data file without changing either existing copy.

    The destination is installed atomically when possible and is never
    overwritten. A failed copy leaves the legacy source untouched.
    """
    if destination.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".migration",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with source.open("rb") as source_file:
                while chunk := source_file.read(1024 * 1024):
                    temporary_file.write(chunk)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            return False
        except OSError:
            # Exclusive creation is a portable no-overwrite fallback for
            # filesystems that do not support hard links.
            created_destination = False
            try:
                with destination.open("xb") as destination_file:
                    created_destination = True
                    with temporary_path.open("rb") as temporary_file:
                        while chunk := temporary_file.read(1024 * 1024):
                            destination_file.write(chunk)
                    destination_file.flush()
                    os.fsync(destination_file.fileno())
            except FileExistsError:
                return False
            except OSError:
                if created_destination:
                    destination.unlink(missing_ok=True)
                raise
        return True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def get_legacy_data_path(filename: str | Path) -> Path:
    """Return the old data path used before user data was centralized."""
    return LEGACY_DATA_ROOT / Path(filename)


def get_legacy_storage_path(filename: str | Path) -> Path:
    """Return an old storage path kept as a migration source."""
    return LEGACY_STORAGE_ROOT / Path(filename)
