"""Small policy boundary for temporary development-only feature access."""


def frequencies_should_be_blocked(
    dev_mode: bool,
    unlock_frequencies: bool,
) -> bool:
    """DEV alone controls access to Frequencies; Light Mode is independent."""
    return not (dev_mode and unlock_frequencies)
