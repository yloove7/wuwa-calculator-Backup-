"""Single source of truth for the Tethys application version."""

APP_VERSION = "1.4.0"


def get_app_version() -> str:
    """Return the current Tethys version string."""
    return APP_VERSION
