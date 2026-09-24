"""Pure formatting helpers for Echo import previews."""


def format_echo_preview_data(echo: dict[str, object]) -> tuple[str, str]:
    """Return the card name and details text for one imported Echo."""
    name = str(echo.get("name", "Echo"))
    attributes = echo.get("attributes", [])
    attribute_lines = [str(value) for value in attributes] if isinstance(attributes, list) else []
    main_stat = str(echo.get("main_stat", attribute_lines[0] if attribute_lines else "--"))
    sub_stats = echo.get("sub_stats", attribute_lines[1:])
    sub_stat_lines = [str(value) for value in sub_stats] if isinstance(sub_stats, list) else []
    cost = echo.get("cost", "--")
    set_bonus = str(echo.get("set_bonus", "--"))
    details = (
        f"Cost: {cost or '--'}\n"
        f"Set: {set_bonus}\n"
        f"Main: {main_stat}\n"
        "Sub-stats: " + ("; ".join(sub_stat_lines) or "--")
    )
    return name, details
