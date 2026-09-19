"""Global visual system for the PySide6 application."""

from dataclasses import dataclass

# * EDITAVEL: altere cores globais e regras QSS aqui; o wallpaper gera uma paleta complementar.
# ! Nao use #RRGGBBAA no QColor: _with_alpha produz o formato Qt #AARRGGBB.

from PySide6.QtCore import QAbstractAnimation, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QWidget,
)

from src.wuwa_calculator.utils.paths import get_asset_path

BG = "#080B18"
CARD = "#0F1428"
BORDER = "#394071"
HEADER = "#161D39"
TEXT = "#F2F0FF"
MUTED = "#A8A8D5"
ACCENT = "#A855F7"
GOLD = "#FFD76A"
CURRENT_GLOW_COLOR = ACCENT
DEFAULT_WALLPAPER = f"url({get_asset_path('app_background_reference.png').as_posix()})"


@dataclass(frozen=True)
class ThemeConfig:
    """Resolved colors consumed by adaptive widgets such as import popups."""

    primary_neon_color: str
    secondary_neon_color: str
    panel_bg_color: str
    panel_bg_color_with_alpha: str
    button_gradient_start: str
    button_gradient_end: str
    text_color: str
    muted_text_color: str


def _blend(color: str, target: str, amount: float) -> str:
    source_rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    target_rgb = tuple(int(target[index:index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(round(source + (destination - source) * amount) for source, destination in zip(source_rgb, target_rgb))
    return "#%02X%02X%02X" % mixed


def _with_alpha(color: str, opacity: int) -> str:
    alpha = max(0, min(255, opacity))
    return f"#{alpha:02X}{color.lstrip('#')}"


def _rgba(color: str, opacity: int) -> str:
    """Represent a hex color as translucent Qt stylesheet color."""
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    alpha = max(0, min(255, opacity))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def apply_glow(widget: QWidget, blur: float = 24.0, opacity: int = 180) -> None:
    widget.setProperty("_glow_mode", "global")
    widget.setProperty("_glow_blur", blur)
    widget.setProperty("_glow_opacity", opacity)
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    effect.setColor(QColor(_with_alpha(CURRENT_GLOW_COLOR, opacity)))
    widget.setGraphicsEffect(effect)


ELEMENT_GLOW_COLORS = {
    "Aero": "#72E6C0",
    "Glacio": "#82D8FF",
    "Electro": "#B78CFF",
    "Fusion": "#FF8A65",
    "Havoc": "#E85D75",
    "Spectro": "#FFD76A",
}


def apply_element_glow(widget: QWidget, element: str, blur: float = 24.0, opacity: int = 180) -> None:
    widget.setProperty("_glow_mode", "element")
    widget.setProperty("_glow_element", element)
    widget.setProperty("_glow_blur", blur)
    widget.setProperty("_glow_opacity", opacity)
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    color = ELEMENT_GLOW_COLORS.get(element, ACCENT)
    effect.setColor(QColor(_with_alpha(color, opacity)))
    widget.setGraphicsEffect(effect)


def disable_visual_effects(root: QWidget) -> None:
    for widget in [root, *root.findChildren(QWidget)]:
        current_effect = widget.graphicsEffect()
        if current_effect is not None:
            widget.setGraphicsEffect(None)
        if isinstance(current_effect, QGraphicsOpacityEffect):
            current_effect.setOpacity(1.0)

    for animation in root.findChildren(QAbstractAnimation):
        if animation.state() != QAbstractAnimation.State.Stopped:
            animation.stop()


def refresh_glows(root: QWidget, performance_mode: bool = False) -> None:
    if performance_mode:
        disable_visual_effects(root)
        return

    for widget in [root, *root.findChildren(QWidget)]:
        mode = widget.property("_glow_mode")
        if mode == "global":
            apply_glow(widget, float(widget.property("_glow_blur")), int(widget.property("_glow_opacity")))
        elif mode == "element":
            apply_element_glow(
                widget,
                str(widget.property("_glow_element")),
                float(widget.property("_glow_blur")),
                int(widget.property("_glow_opacity")),
            )
        elif isinstance(widget, QAbstractButton):
            apply_glow(widget, blur=14.0, opacity=68)


def _wallpaper_palette(wallpaper: str) -> tuple[str, str, str, str, str]:
    source = QUrl(wallpaper).toLocalFile() if wallpaper.startswith("file:") else wallpaper
    image = QImage(source or str(get_asset_path("app_background_reference.png")))
    if image.isNull():
        return CARD, HEADER, BORDER, ACCENT, MUTED

    sample = image.scaled(32, 18).convertToFormat(QImage.Format.Format_RGB32)
    red = green = blue = 0
    for y in range(sample.height()):
        for x in range(sample.width()):
            color = sample.pixelColor(x, y)
            red += color.red()
            green += color.green()
            blue += color.blue()
    count = max(1, sample.width() * sample.height())
    average = QColor(red // count, green // count, blue // count)
    hue = average.hue() if average.hue() >= 0 else 195
    saturation = average.saturation()
    value = average.value()
    surface = QColor.fromHsv(
        hue,
        min(95, saturation),
        max(24, min(78, value // 3 + 12)),
    )
    panel = QColor.fromHsv(
        (hue + 8) % 360,
        min(105, saturation),
        max(32, min(96, value // 4 + 20)),
    )
    border = QColor.fromHsv(
        hue,
        min(135, saturation + 18),
        max(135, min(220, value + 55)),
    )
    accent = QColor.fromHsv(
        (hue + 24) % 360,
        min(180, max(45, saturation + 15)),
        max(190, min(245, value + 45)),
    )
    muted = QColor.fromHsv(
        hue,
        min(70, saturation // 2),
        210,
    )
    return surface.name(), panel.name(), border.name(), accent.name(), muted.name()


def wallpaper_palette(wallpaper: str = "") -> tuple[str, str, str, str, str]:
    """Return the colors derived from the active wallpaper."""
    return _wallpaper_palette(wallpaper)


def _accent_preset(name: str) -> str:
    return {
        "Auto Wallpaper": "#6FEAFF",
        "Ciano Tethys": "#6FEAFF",
        "Dourado Sol": "#C9952A",
        "Roxo Nécro": "#6B4AB6",
        "Vermelho Alerta": "#8F2D2D",
        "Verde Aurora": "#74F2B2",
        "Azul Abissal": "#73B7FF",
        "Rosa Prisma": "#FF8FC7",
        "Laranja Solar": "#BF5A1F",
        "Turquesa Maré": "#55E6D0",
        "Lima Resonância": "#D2F26B",
        "Gelo Lunar": "#B9E8FF",
        "Âmbar Nebulosa": "#A56B1A",
        "Coral Resonante": "#B55E43",
        "Índigo Profundo": "#4D4FAD",
        "Prata Sônica": "#D7E1EA",
        "Verde Vórtice": "#78E6A4",
    }.get(name, "#6FEAFF")


def accent_preset(name: str) -> str:
    """Return the configured interface accent color."""
    return _accent_preset(name)


class ThemeManager:
    """Separate neutral surfaces from wallpaper-derived accent colors."""

    DARK_NEUTRAL_BG = "rgba(18, 22, 26, 0.75)"
    LIGHT_NEUTRAL_BG = "rgba(255, 255, 255, 0.65)"
    DARK_TEXT = "#FFFFFF"
    LIGHT_TEXT = "#12161A"
    DARK_TEXT_SECONDARY = "#A0A5AB"
    LIGHT_TEXT_SECONDARY = "#4A5056"

    def __init__(self, accent_color: str = "#6FEAFF", is_dark: bool = True) -> None:
        self.accent_color = accent_color
        self.is_dark = is_dark

    def set_theme(self, is_dark: bool) -> None:
        self.is_dark = bool(is_dark)

    def neutral_background(self) -> str:
        return self.DARK_NEUTRAL_BG if self.is_dark else self.LIGHT_NEUTRAL_BG

    def text_primary(self) -> str:
        return self.DARK_TEXT if self.is_dark else self.LIGHT_TEXT

    def text_secondary(self) -> str:
        return self.DARK_TEXT_SECONDARY if self.is_dark else self.LIGHT_TEXT_SECONDARY

    def qss(self, *, wallpaper: str = "", show_background: bool = True, interface_opacity: int = 85) -> str:
        neutral_bg = self.neutral_background()
        text_main = self.text_primary()
        text_secondary = self.text_secondary()
        surface_color, panel_color, wallpaper_border, wallpaper_accent, wallpaper_muted = (
            _wallpaper_palette(wallpaper) if show_background else (BG, CARD, BORDER, ACCENT, MUTED)
        )
        selected_accent = self.accent_color or wallpaper_accent
        neon_border = _rgba(selected_accent, 185)
        neon_soft = _rgba(selected_accent, 75)
        panel_alpha = max(125, min(190, round(70 + interface_opacity * 0.95)))
        wallpaper_panel = neutral_bg
        wallpaper_surface = _rgba(surface_color, min(215, panel_alpha + 18))
        return f"""
        QMainWindow {{ background: {neutral_bg}; color: {text_main}; }}
        QWidget {{ background: transparent; color: {text_main}; font-family: "Bahnschrift", "Segoe UI"; font-size: 13px; }}
        QLabel {{ background: transparent; color: {text_main}; }}
        QLabel#muted, QLabel#eyebrow, QLabel#metricName, QLabel#optionLabel, QLabel#ocrStatusItem, QLabel#ocrStatusItem[active="true"], QLabel#ocrStatusItem[complete="true"] {{ color: {text_secondary}; }}
        QFrame#sidebar {{ background: {neutral_bg}; border-right: 1px solid {wallpaper_border}; }}
        QFrame#card, QFrame#appHeader, QFrame#upcomingBannersSection, QFrame#upcomingBannerCard, QFrame#upcomingBannerPastCard, QFrame#bannerTimeline, QFrame#bannerImageContainer, QFrame#bannerHud {{ background: {neutral_bg}; border-color: {wallpaper_border}; }}
        QFrame#card {{ border: 1px solid {wallpaper_border}; border-radius: 12px; }}
        QFrame#appHeader {{ border: 1px solid {wallpaper_border}; border-radius: 10px; }}
        QPushButton {{ background: {neutral_bg}; color: {text_main}; border: 1px solid {wallpaper_border}; }}
        QPushButton:hover {{ background: {wallpaper_surface}; border: 2px solid {selected_accent}; color: {text_main}; }}
        QPushButton:pressed {{ background: {selected_accent}; color: #FFFFFF; border: 2px solid {selected_accent}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{ background: {neutral_bg}; color: {text_main}; border: 1px solid {wallpaper_border}; }}
        QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTextEdit:hover, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{ background: {wallpaper_surface}; border: 2px solid {selected_accent}; }}
        QComboBox QAbstractItemView {{ background: {neutral_bg}; color: {text_main}; border: 1px solid {selected_accent}; selection-background-color: {wallpaper_surface}; selection-color: {text_main}; }}
        QCheckBox {{ color: {text_main}; spacing: 10px; font-weight: 700; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 2px solid {wallpaper_border}; background: rgba(255, 255, 255, 0.04); }}
        QCheckBox::indicator:hover {{ border: 2px solid {selected_accent}; background: rgba(255, 255, 255, 0.08); }}
        QCheckBox::indicator:checked {{ background: transparent; border: 2px solid {selected_accent}; }}
        QTabBar::tab {{ background: {neutral_bg}; color: {text_secondary}; border: 1px solid {wallpaper_border}; }}
        QTabBar::tab:selected {{ background: {wallpaper_surface}; color: {text_main}; border: 2px solid {selected_accent}; }}
        QSlider::groove:horizontal {{ background: {wallpaper_surface}; border: 1px solid {wallpaper_border}; }}
        QSlider::sub-page:horizontal {{ background: {selected_accent}; }}
        QSlider::handle:horizontal {{ background: {text_main}; border: 2px solid {selected_accent}; }}
        QScrollBar:vertical, QScrollBar:horizontal {{ background: {neutral_bg}; }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {selected_accent}; border: 1px solid {selected_accent}; border-radius: 5px; }}
        QFrame#card, QFrame#appHeader, QFrame#sidebar, QFrame#upcomingBannersSection {{ background-color: {neutral_bg}; }}
        QPushButton#primaryAction {{ background: {neutral_bg}; color: {text_main}; border: 1px solid {selected_accent}; }}
        QPushButton#primaryAction:hover {{ background: {wallpaper_surface}; border: 2px solid {selected_accent}; }}
        QFrame#historyTeamSummary, QFrame#historyQuickMetric, QFrame#historyStatCard, QFrame#damageFormulaBox, QFrame#damageInputGroup, QFrame#damageOutputCard {{ background: {neutral_bg}; border-color: {wallpaper_border}; }}
        QLabel#title, QLabel#bannerName, QLabel#skillTitle, QLabel#bannerSubtitle, QLabel#damageInputLabel, QLabel#damageFormula, QLabel#historyTeamMembers {{ color: {text_main}; }}
        QLabel#muted, QLabel#eyebrow {{ color: {text_secondary}; }}
        """


def theme_config(
    wallpaper: str = "",
    interface_opacity: int = 85,
    accent_theme: str = "Ciano Tethys",
) -> ThemeConfig:
    """Resolve the current Tethys palette for adaptive custom widgets."""
    if accent_theme in {"Modo claro", "Modo escuro"}:
        accent_theme = "Auto Wallpaper"
    _surface, panel, _wallpaper_border, wallpaper_accent, muted = _wallpaper_palette(wallpaper)
    if accent_theme == "Auto Wallpaper":
        primary = wallpaper_accent
        secondary = wallpaper_accent
        is_dark = True
        panel_color = panel
        panel_border = _wallpaper_border
    else:
        primary = _accent_preset(accent_theme)
        secondary = primary
        is_dark = True
        panel_color = _blend(primary, "#0B0F1A", 0.6)
        panel_border = _rgba(primary, 170)
    theme_manager = ThemeManager(accent_color=primary, is_dark=is_dark)
    panel_alpha = max(125, min(190, round(70 + interface_opacity * 0.95)))
    return ThemeConfig(
        primary_neon_color=primary,
        secondary_neon_color=secondary,
        panel_bg_color=panel_color,
        panel_bg_color_with_alpha=_rgba(panel_color, panel_alpha),
        button_gradient_start=_blend(primary, "#FFFFFF", 0.18),
        button_gradient_end=_blend(secondary, panel_color, 0.45),
        text_color=theme_manager.text_primary(),
        muted_text_color=theme_manager.text_secondary(),
    )


def application_qss(
    show_background: bool = True,
    wallpaper: str = "",
    interface_opacity: int = 85,
    accent_theme: str = "Ciano Tethys",
) -> str:
    global CURRENT_GLOW_COLOR

    if accent_theme in {"Modo claro", "Modo escuro"}:
        accent_theme = "Auto Wallpaper"

    if show_background:
        surface_color, panel_color, wallpaper_border, wallpaper_accent, wallpaper_muted = _wallpaper_palette(wallpaper)
    else:
        surface_color, panel_color, wallpaper_border, wallpaper_accent, wallpaper_muted = (BG, CARD, BORDER, ACCENT, MUTED)

    if accent_theme == "Auto Wallpaper":
        selected_accent = wallpaper_accent
        theme_manager = ThemeManager(accent_color=selected_accent, is_dark=True)
        background_rule = f"background-color: {BG};"
        text_color = theme_manager.text_primary()
    else:
        selected_accent = _accent_preset(accent_theme)
        surface_color = _blend(selected_accent, "#0B0F1A", 0.5)
        panel_color = _blend(selected_accent, "#111827", 0.72)
        wallpaper_border = _rgba(selected_accent, 180)
        wallpaper_accent = selected_accent
        wallpaper_muted = _blend(selected_accent, "#EAF4FF", 0.35)
        theme_manager = ThemeManager(accent_color=selected_accent, is_dark=True)
        background_rule = f"background-color: {BG};"
        text_color = theme_manager.text_primary()

    CURRENT_GLOW_COLOR = selected_accent
    neon_border = _rgba(selected_accent, 185)
    neon_soft = _rgba(selected_accent, 75)
    panel_alpha = max(110, min(215, round(55 + interface_opacity * 1.25)))
    wallpaper_panel = _rgba(panel_color, panel_alpha)
    wallpaper_surface = _rgba(surface_color, min(235, panel_alpha + 22))
    accent_soft = _rgba(selected_accent, max(55, min(180, panel_alpha - 25)))
    text_primary = theme_manager.text_primary()
    text_secondary = theme_manager.text_secondary()
    return f"""
    QMainWindow {{
        {background_rule}
        color: {text_color};
    }}
    QWidget {{ background: transparent; color: {text_color}; font-family: "Bahnschrift", "Segoe UI"; font-size: 13px; }}
    QLabel {{ background: transparent; color: {text_color}; }}
    QWidget#appShell {{ background: transparent; }}
    QFrame#sidebar {{ background: {wallpaper_panel}; border-right: 1px solid {wallpaper_border}; }}
    QFrame#card, QFrame#appHeader {{ background: {wallpaper_panel}; border: 1px solid {wallpaper_border}; border-radius: 12px; }}
    QFrame#appHeader {{ border-radius: 10px; }}
    QTabWidget#mainTabs {{ background: transparent; border: 0; }}
    QTabWidget#mainTabs::pane {{ border: 0; background: transparent; }}
    QPushButton#nav, QPushButton#navActive {{ text-align: left; border: 0; padding: 10px; border-radius: 7px; }}
    QPushButton#nav {{ background: {wallpaper_surface}; color: {text_color}; border: 1px solid {wallpaper_border}; }}
    QPushButton#nav:hover {{ background: {accent_soft}; border: 1px solid {selected_accent}; }}
    QPushButton#navActive {{ background: {selected_accent}; color: #FFFFFF; font-weight: 800; }}
    QPushButton#nav[element="Aero"], QPushButton#navActive[element="Aero"] {{ background: {selected_accent}; border: 1px solid #72E6C0; color: #E8FFF8; }}
    QPushButton#nav[element="Glacio"], QPushButton#navActive[element="Glacio"] {{ background: {selected_accent}; border: 1px solid #82D8FF; color: #E4F8FF; }}
    QPushButton#nav[element="Electro"], QPushButton#navActive[element="Electro"] {{ background: #49356F; border: 1px solid #B78CFF; color: #F0E8FF; }}
    QPushButton#nav[element="Fusion"], QPushButton#navActive[element="Fusion"] {{ background: #713D2C; border: 1px solid #FF8A65; color: #FFF0E8; }}
    QPushButton#nav[element="Havoc"], QPushButton#navActive[element="Havoc"] {{ background: #642C43; border: 1px solid #E85D75; color: #FFE8EE; }}
    QPushButton#nav[element="Spectro"], QPushButton#navActive[element="Spectro"] {{ background: #665522; border: 1px solid #FFD76A; color: #FFF8D6; }}
    QPushButton#nav[element="Aero"]:hover, QPushButton#navActive[element="Aero"]:hover {{ background: #1E8068; }}
    QPushButton#nav[element="Glacio"]:hover, QPushButton#navActive[element="Glacio"]:hover {{ background: #397A9D; }}
    QPushButton#nav[element="Electro"]:hover, QPushButton#navActive[element="Electro"]:hover {{ background: #644B91; }}
    QPushButton#nav[element="Fusion"]:hover, QPushButton#navActive[element="Fusion"]:hover {{ background: #975039; }}
    QPushButton#nav[element="Havoc"]:hover, QPushButton#navActive[element="Havoc"]:hover {{ background: #873B58; }}
    QPushButton#nav[element="Spectro"]:hover, QPushButton#navActive[element="Spectro"]:hover {{ background: #87702D; }}
    QFrame#card {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 12px;
    }}
    QFrame#appHeader {{ background: {wallpaper_panel}; border: 1px solid {wallpaper_border}; border-radius: 10px; }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background: transparent; border: 0; }}
    QFrame#videoSurface {{ background: rgba(11, 13, 18, 235); border: 1px solid rgba(0, 217, 255, 70); border-radius: 8px; }}
    QFrame#mediaToolbar {{ background: rgba(8, 14, 27, 235); border: 1px solid rgba(0, 217, 255, 90); border-radius: 7px; }}
    QFrame#mediaSupportPanel {{ background: rgba(7, 15, 28, 185); border: 1px solid rgba(0, 217, 255, 70); border-radius: 8px; }}
    QFrame#mediaSupportPanel QFrame#card {{ background: transparent; border: 0; border-radius: 0; }}
    QLabel#videoHud {{ color: #8FF6FF; background: rgba(5, 12, 22, 205); border: 1px solid rgba(0, 217, 255, 100); border-radius: 5px; padding: 4px 9px; font-size: 10px; font-weight: 800; }}
    QPushButton#mediaControlButton, QPushButton#mediaBrowseButton, QPushButton#mediaPlayButton, QPushButton#mediaStopButton {{ background: rgba(20, 35, 55, 230); color: #DDFBFF; border: 1px solid rgba(0, 217, 255, 85); border-radius: 5px; min-height: 26px; font-weight: 800; }}
    QPushButton#mediaControlButton:hover, QPushButton#mediaBrowseButton:hover, QPushButton#mediaPlayButton:hover, QPushButton#mediaStopButton:hover {{ background: rgba(0, 110, 145, 220); border-color: #6FEAFF; }}
    QLabel#mediaTimeLabel, QLabel#mediaControlLabel {{ color: #B7DCE5; font-size: 10px; font-weight: 700; }}
    QSlider#playerProgress {{ min-height: 14px; }}
    QFrame#frequencyProtocolBar {{ background: rgba(11, 13, 18, 220); border: 1px solid rgba(0, 217, 255, 70); border-radius: 7px; }}
    QDialog#ocrImportDialog {{ background: rgba(5, 7, 13, 238); border: 1px solid rgba(255, 215, 106, 150); color: #F2F0FF; }}
    QLabel#ocrDialogTitle {{ color: #FFD76A; font-size: 18px; font-weight: 900; letter-spacing: 2px; }}
    QLabel#ocrDialogProtocol {{ color: #6FEAFF; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 10px; font-weight: 800; }}
    QFrame#ocrScanPanel, QFrame#ocrStatusPanel {{ background: rgba(8, 14, 27, 190); border: 1px solid rgba(0, 217, 255, 80); border-radius: 10px; }}
    QFrame#ocrGrid {{ background-color: rgba(7, 17, 32, 220); border: 1px solid rgba(111, 234, 255, 110); border-radius: 7px; background-image: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 transparent, stop: 0.49 transparent, stop: 0.5 rgba(111, 234, 255, 35), stop: 0.51 transparent, stop: 1 transparent); }}
    QFrame#ocrGrid {{ background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 rgba(11, 34, 58, 225), stop: 0.5 rgba(5, 15, 29, 225), stop: 1 rgba(11, 34, 58, 225)); }}
    QFrame#ocrScanLine {{ background: #6FEAFF; border: 0; min-height: 2px; max-height: 2px; }}
    QLabel#ocrSectionLabel {{ color: #6FEAFF; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 10px; font-weight: 900; letter-spacing: 1px; }}
    QLabel#ocrGridHint {{ color: #7895AA; font-size: 11px; line-height: 1.4; }}
    QPushButton#ocrSelectButton, QPushButton#ocrConfirmButton {{ background: rgba(51, 40, 85, 225); color: #FFF8D6; border: 1px solid #FFD76A; border-radius: 6px; padding: 10px 16px; font-weight: 900; }}
    QPushButton#ocrSelectButton:hover, QPushButton#ocrConfirmButton:hover {{ background: rgba(91, 66, 132, 235); border-color: #FFFFFF; color: #FFFFFF; }}
    QPushButton#ocrSelectButton:disabled {{ color: #718091; border-color: #394458; background: rgba(21, 28, 42, 220); }}
    QPushButton#ocrCancelButton {{ background: rgba(18, 25, 39, 220); color: #B7C6D6; border: 1px solid rgba(111, 234, 255, 100); border-radius: 6px; padding: 10px 16px; font-weight: 800; }}
    QPushButton#ocrCancelButton:hover {{ color: #FFFFFF; border-color: #6FEAFF; background: rgba(24, 61, 78, 230); }}
    QFrame#ocrCharacterCard {{ background: rgba(23, 29, 49, 220); border: 1px solid rgba(255, 215, 106, 120); border-radius: 7px; }}
    QLabel#ocrCharacterPreview {{ background: rgba(5, 10, 19, 180); border: 1px solid rgba(111, 234, 255, 100); border-radius: 5px; color: #6FEAFF; font-size: 28px; }}
    QLabel#ocrCharacterName {{ color: #FFFFFF; font-size: 16px; font-weight: 900; }}
    QLabel#ocrCharacterMeta {{ color: #FFD76A; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9px; font-weight: 800; }}
    QLabel#ocrStatusRing {{ color: #6FEAFF; font-size: 46px; font-weight: 300; min-height: 64px; }}
    QLabel#ocrStatusLabel {{ color: #DCEEFF; font-size: 12px; font-weight: 800; }}
    QFrame#ocrPreviewPanel {{ background: rgba(13, 17, 29, 210); border: 1px solid rgba(255, 215, 106, 105); border-radius: 8px; }}
    QLabel#ocrPreviewText {{ color: #FFD76A; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; font-weight: 800; padding: 4px; }}
    QLabel#frequencyProtocolTitle {{ color: #6FEAFF; font-size: 12px; font-weight: 800; letter-spacing: 1px; }}
    QLabel#frequencyProtocolSubtitle {{ color: #8A99AD; font-size: 9px; margin-top: 4px; }}
    QLabel#frequencyProtocolBadge {{ color: #00D9FF; font-family: "Bahnschrift", "Segoe UI", sans-serif; font-size: 11px; border: 1px solid rgba(0, 217, 255, 76); border-radius: 5px; padding: 4px 10px; min-height: 28px; white-space: nowrap; }}
    QLabel#mediaSectionTitle {{ color: #F2F0FF; font-size: 13px; font-weight: 800; }}
    QLabel#mediaPanelDuration {{ color: #67D9FF; font-size: 12px; font-weight: 800; }}
    QFrame#eventRow {{ background: rgba(11, 13, 18, 190); border: 1px solid rgba(0, 217, 255, 50); border-radius: 7px; }}
    QFrame#eventRow[category="Skill"] {{ border-left: 3px solid #6FEAFF; }}
    QFrame#eventRow[category="Ultimate"] {{ border-left: 3px solid #C084FC; }}
    QFrame#eventRow[category="Buff"] {{ border-left: 3px solid #FFD76A; }}
    QFrame#eventRow[stripe="even"] {{ background: rgba(20, 29, 45, 205); }}
    QFrame#eventRow[active="true"] {{ background: rgba(72, 32, 154, 215); border-color: #B77CFF; }}
    QLabel#eventTimestamp {{ color: #C7C8EA; font-size: 11px; font-weight: 800; }}
    QLabel#eventIcon {{ color: #B77CFF; background: rgba(35, 38, 65, 210); border: 1px solid #6547A8; border-radius: 12px; font-size: 13px; }}
    QLabel#eventTitle {{ color: #F2F0FF; font-size: 11px; font-weight: 800; min-height: 13px; }}
    QLabel#eventDescription {{ color: #A8A8D5; font-size: 9px; min-height: 12px; }}
    QLabel#eventCategory {{ color: #6FEAFF; font-size: 8px; font-weight: 900; }}
    QFrame#eventRow[category="Ultimate"] QLabel#eventCategory {{ color: #C084FC; }}
    QFrame#eventRow[category="Buff"] QLabel#eventCategory {{ color: #FFD76A; }}
    QFrame#eventRow[active="true"] QLabel#eventTitle, QFrame#eventRow[active="true"] QLabel#eventDescription, QFrame#eventRow[active="true"] QLabel#eventTimestamp {{ color: #FFFFFF; }}
    QLabel#metricName, QLabel#optionLabel {{ color: {MUTED}; font-size: 9px; text-transform: uppercase; }}
    QLabel#metricValue {{ color: #F2F0FF; font-size: 13px; font-weight: 900; }}
    QComboBox#mediaOptionCombo {{ min-width: 104px; padding: 6px 8px; font-size: 11px; background: rgba(11, 16, 34, 210); border-color: rgba(103, 112, 168, 180); }}
    QLabel#dpsMetric {{ color: #8FF6FF; background: rgba(10, 28, 43, 225); border: 1px solid rgba(0, 217, 255, 105); border-radius: 6px; padding: 7px 9px; font-size: 10px; font-weight: 900; }}
    QPushButton#dpsAnalyzeButton {{ color: #06141C; background: #6FEAFF; border: 1px solid #B8F8FF; border-radius: 6px; padding: 7px 12px; font-weight: 900; }}
    QPushButton#dpsAnalyzeButton:hover {{ background: #B8F8FF; border-color: #FFFFFF; }}
    QPushButton#mediaQuickAction {{ background: rgba(11, 13, 18, 225); color: {TEXT}; border: 1px solid rgba(212, 175, 55, 150); border-radius: 6px; padding: 8px 7px; font-size: 11px; font-weight: 700; }}
    QPushButton#mediaQuickAction:hover {{ background: rgba(31, 35, 42, 235); border-color: #D4AF37; }}
    QFrame#currentBannerCard {{ background: transparent; border: 0; border-radius: 0; }}
    QFrame#bannerTimeline {{
        background: rgba(20, 19, 31, 188);
        border: 1px solid rgba(150, 180, 205, 95);
        border-radius: 10px;
    }}
    QLabel#bannerTimelineTitle {{ color: #F7D878; font-size: 18px; font-weight: 800; }}
    QLabel#bannerCurrentHighlight {{
        color: #FFFFFF;
        background: rgba(12, 16, 30, 225);
        border: 1px solid rgba(212, 175, 55, 165);
        border-radius: 6px;
        padding: 6px 12px;
        font-family: "Bahnschrift", "Segoe UI";
        font-size: 18px;
        font-weight: 800;
    }}
    QLabel#bannerTimelineSection {{ color: #D6D5E8; font-size: 11px; font-weight: 800; text-transform: uppercase; }}
    QFrame#bannerTimelinePast {{
        background: rgba(12, 12, 22, 150);
        border-right: 1px solid rgba(133, 143, 180, 100);
        border-radius: 6px;
        min-width: 332px;
    }}
    QFrame#bannerTimelineFuture {{ background: transparent; border: 0; }}
    QScrollArea#bannerTimelineScroll {{ background: transparent; border: 0; }}
    QFrame#bannerTimelineCard {{
        background: rgba(31, 30, 48, 225);
        border: 1px solid rgba(133, 143, 180, 125);
        border-radius: 7px;
    }}
    QFrame#bannerTimelineCard:hover {{
        border: 1px solid rgba(103, 232, 212, 190);
        background: rgba(40, 39, 62, 235);
    }}
    QFrame#bannerTimelinePastCard {{
        background: rgba(31, 30, 48, 190);
        border: 1px solid rgba(133, 143, 180, 105);
        border-radius: 6px;
    }}
    QFrame#bannerTimelinePastCard:hover {{
        border: 1px solid rgba(103, 232, 212, 170);
    }}
    QLabel#bannerTimelineThumb {{
        background: #0D0D15;
        color: #67E8D4;
        border: 1px solid rgba(212, 175, 55, 100);
        border-radius: 5px;
    }}
    QLabel#bannerTimelineName {{ color: #F3F1FF; font-size: 12px; font-weight: 800; }}
    QLabel#bannerTimelineTBA {{
        color: #8FF6FF;
        background: rgba(25, 34, 62, 215);
        border: 1px solid rgba(180, 119, 255, 190);
        border-radius: 5px;
        padding: 5px 8px;
        font-family: "Bahnschrift", "Segoe UI";
        font-size: 14px;
        font-weight: 900;
    }}
    QLabel#bannerTimelineRarity {{ color: #FFD76A; font-size: 12px; font-weight: 800; }}
    QLabel#bannerTimelineDate {{
        color: #7DEBFF;
        font-family: "Bahnschrift", "Segoe UI";
        font-size: 11px;
        font-weight: 800;
        background: rgba(22, 42, 62, 205);
        border: 1px solid rgba(103, 232, 212, 145);
        border-radius: 4px;
        padding: 3px 6px;
        text-shadow: 0 0 8px #35D9FF;
    }}
    QLabel#bannerTimelineTag {{ color: #67E8D4; font-size: 9px; font-weight: 800; }}
    QLabel#bannerTimelineEmpty {{ color: #A8A8D5; padding: 14px; }}
    QPushButton#bannerTimelineArrow {{
        background: rgba(52, 49, 76, 220);
        color: #F7D878;
        border: 1px solid rgba(103, 232, 212, 120);
        border-radius: 5px;
        font-size: 16px;
        font-weight: 800;
        padding: 0;
    }}
    QPushButton#bannerTimelineArrow:hover {{ background: #3F5270; color: #FFFFFF; }}
    QFrame#upcomingBannersSection {{
        background: rgba(12, 11, 16, 218);
        border: 1px solid rgba(255, 255, 255, 28);
        border-radius: 12px;
    }}
    QLabel#upcomingBannersTitle {{ color: #F5F5F5; font-size: 15px; font-weight: 900; }}
    QLabel#upcomingBannersSubtitle {{ color: #9DA3B4; font-size: 9px; }}
    QPushButton#upcomingBannersTrackerButton {{
        background: rgba(20, 35, 65, 220);
        color: #8FEFFF;
        border: 1px solid rgba(0, 217, 255, 120);
        border-radius: 7px;
        padding: 8px 12px;
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#upcomingBannersTrackerButton:hover {{ background: #173B5B; border: 1px solid #00D9FF; }}
    QFrame#upcomingBannerCard {{
        background: rgba(12, 16, 30, 235);
        border: 1px solid rgba(0, 217, 255, 150);
        border-radius: 16px;
    }}
    QFrame#upcomingBannerCard:hover {{ border: 1px solid #6FEAFF; background: rgba(25, 27, 45, 248); }}
    QFrame#upcomingBannerPastCard {{
        background: rgba(12, 16, 30, 235);
        border: 1px solid rgba(0, 217, 255, 150);
        border-radius: 16px;
    }}
    QFrame#upcomingBannerPastCard[hovered="true"] {{
        border: 0;
        background: rgba(25, 27, 45, 248);
    }}
    QLabel#upcomingBannerImage {{
        background: transparent;
        color: #9DA3B4;
        border: 0;
        border-radius: 16px;
    }}
    QFrame#upcomingBannerOverlay {{
        background: rgba(0, 0, 0, 155);
        border: 1px solid rgba(0, 217, 255, 95);
        border-radius: 6px;
    }}
    QLabel#upcomingBannerBadge {{
        color: #0C0B10;
        background: #00D9FF;
        border-radius: 5px;
        padding: 3px 7px;
        font-size: 9px;
        font-weight: 900;
    }}
    QLabel#upcomingBannerName {{ color: #F5F5F5; font-size: 13px; font-weight: 900; }}
    QLabel#upcomingBannerDetails {{ color: #D5D9E4; font-size: 10px; font-weight: 700; }}
    QFrame#bannerImageContainer {{ background: #14131F; border: 2px solid rgba(212, 175, 55, 90); border-radius: 16px; }}
    QFrame#bannerDimOverlay {{ background: rgba(0, 0, 0, 105); border: 0; border-radius: 0; }}
    QFrame#bannerOverlay {{ background: transparent; border: 0; border-radius: 12px; }}
    QFrame#bannerHud {{ background: rgba(12, 11, 16, 242); border: 1px solid rgba(212, 175, 55, 100); border-radius: 8px; min-height: 56px; }}
    QLabel#bannerCharacterName {{ color: #FFF4D0; background: transparent; border: 0; border-radius: 0; font-family: "Bahnschrift", "Segoe UI"; font-size: 16px; font-weight: 800; padding: 8px 12px; }}
    QLabel#currentBannerImage {{ background: #0D0D15; color: #AAA3B7; border: 0; border-radius: 8px; padding: 0px; }}
    QLabel#bannerCountdown {{ color: #00FFCC; background: transparent; font-family: "Bahnschrift", "Segoe UI"; font-size: 15px; font-weight: 800; padding: 8px 12px; }}
    QFrame#topBanner {{ background: transparent; border: 1px solid {wallpaper_accent}; border-radius: 10px; }}
    QPushButton#resonatorTabButton {{
        background: {wallpaper_panel};
        color: {TEXT};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
        padding: 8px 10px;
        min-height: 30px;
    }}
    QPushButton#resonatorTabButton:hover {{
        background: {wallpaper_surface};
        border: 2px solid {wallpaper_accent};
        color: {TEXT};
    }}
    QPushButton#resonatorTabButton[active="true"] {{
        background: {wallpaper_surface};
        color: {TEXT};
        border: 2px solid {wallpaper_accent};
        font-weight: 800;
    }}
    QFrame#skillCard {{ background: #171E38; border: 1px solid #323D70; border-radius: 8px; }}
    QLabel#skillIcon {{ background: #242A5A; color: #FFFFFF; border: 1px solid #5D5CE8; border-radius: 7px; padding: 8px; min-width: 28px; font-size: 20px; }}
    QLabel#skillTitle {{ color: #DDBBFF; font-weight: 800; font-size: 14px; }}
    QLabel#skillNumber {{ background: #3D477A; color: #FFFFFF; border-radius: 5px; padding: 7px; min-width: 16px; font-size: 14px; font-weight: 800; }}
    QFrame#weaponInfoCard {{
        background: rgba(17, 22, 38, 210);
        border: 1px solid rgba(108, 151, 255, 180);
        border-radius: 10px;
        padding: 2px;
    }}
    QLabel#weaponInfoTitle {{
        color: #F0F6FF;
        font-family: "Cinzel", "Bahnschrift", "Segoe UI";
        font-size: 18px;
        font-weight: 800;
        margin: 0 0 2px 0;
    }}
    QLabel#weaponInfoText {{
        color: #DDE9FF;
        background: rgba(12, 16, 29, 120);
        border: 1px solid rgba(110, 234, 255, 90);
        border-radius: 8px;
        padding: 12px 14px 12px 14px;
        line-height: 1.6;
        margin-top: 8px;
    }}
    QLabel#bannerPortrait {{ background: transparent; border: 0; }}
    QLabel#bannerName {{ color: #FFFFFF; font-family: "Cinzel", "Bahnschrift", "Segoe UI"; font-size: 30px; font-weight: 800; }}
    QLabel#bannerSubtitle {{ color: {MUTED}; font-size: 14px; }}
    QLabel#bannerBadge {{ color: {ACCENT}; background: rgba(62, 39, 92, 180); border: 1px solid rgba(217, 70, 239, 150); border-radius: 12px; padding: 4px 10px; }}
    QLabel#bannerBadge[element="Aero"] {{ color: #E8FFF8; background: #145A4A; border: 1px solid #72E6C0; }}
    QLabel#bannerBadge[element="Glacio"] {{ color: #E4F8FF; background: #285A78; border: 1px solid #82D8FF; }}
    QLabel#bannerBadge[element="Electro"] {{ color: #F0E8FF; background: #49356F; border: 1px solid #B78CFF; }}
    QLabel#bannerBadge[element="Fusion"] {{ color: #FFF0E8; background: #713D2C; border: 1px solid #FF8A65; }}
    QLabel#bannerBadge[element="Havoc"] {{ color: #FFE8EE; background: #642C43; border: 1px solid #E85D75; }}
    QLabel#bannerBadge[element="Spectro"] {{ color: #FFF8D6; background: #665522; border: 1px solid #FFD76A; }}
    QLabel#bannerRarity {{ color: {GOLD}; font-size: 18px; letter-spacing: 2px; }}
    QLabel#bannerQuote {{ color: #E9D5FF; font-family: "Cinzel", "Bahnschrift", "Segoe UI"; font-size: 12px; font-style: italic; padding: 6px; }}
    QLabel#title {{ color: {GOLD}; font-family: "Cinzel", "Bahnschrift", "Segoe UI"; font-size: 18px; font-weight: 700; }}
    QLabel#muted, QLabel#eyebrow {{ color: {MUTED}; }}
    QLabel#metricValue {{ color: {ACCENT}; font-family: "Bahnschrift", "Segoe UI"; font-size: 22px; font-weight: 700; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: rgba(11, 9, 20, 205);
        color: {TEXT};
        border: 1px solid rgba(124, 58, 237, 105);
        border-radius: 8px;
        padding: 8px;
        selection-background-color: {BORDER};
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border: 1px solid rgba(217, 70, 239, 180); }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {selected_accent}; background: rgba(26, 21, 46, 235); }}
    QCheckBox {{
        color: {TEXT};
        spacing: 10px;
        font-weight: 600;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 2px solid {wallpaper_accent};
        background: {wallpaper_panel};
    }}
    QCheckBox::indicator:hover {{
        border: 2px solid {selected_accent};
        background: {wallpaper_surface};
    }}
    QCheckBox::indicator:checked {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 {selected_accent}, stop: 1 {wallpaper_accent});
        border: 2px solid {selected_accent};
    }}
    QCheckBox::indicator:checked:hover {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 {selected_accent}, stop: 1 {ACCENT});
        border: 2px solid #FFFFFF;
    }}
    QComboBox QAbstractItemView {{ background: {wallpaper_panel}; color: {TEXT}; border: 1px solid {wallpaper_border}; selection-background-color: {wallpaper_surface}; }}
    QPushButton {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #3A2861, stop: 1 {HEADER});
        color: {TEXT};
        border: 1px solid rgba(217, 70, 239, 170);
        border-radius: 8px;
        padding: 9px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: #4B3278; color: #FFFFFF; border: 1px solid {ACCENT}; }}
    QPushButton:pressed {{ background: #24163D; border: 1px solid {GOLD}; }}
    QPushButton#primaryAction {{ background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 {neon_soft}, stop: 1 {wallpaper_panel}); border: 1px solid {neon_border}; color: #FFFFFF; }}
    QPushButton#primaryAction:hover {{ background: {neon_soft}; border: 2px solid {selected_accent}; }}
    QPushButton:disabled {{ color: {MUTED}; background: {BG}; }}
    QPushButton#playerButton {{
        background-color: {HEADER};
        color: {TEXT};
        border: 1px solid rgba(217, 70, 239, 170);
        border-radius: 6px;
        padding: 6px 12px;
        font-weight: 700;
    }}
    QPushButton#playerButton:hover {{
        background-color: {BORDER};
        border: 1px solid {ACCENT};
    }}
    QPushButton#playerButton:pressed {{
        background-color: #2E1F42;
        border: 1px solid {GOLD};
        padding: 8px 12px 4px 12px;
    }}
    QPushButton#playerButton:disabled {{
        background-color: {BG};
        color: {MUTED};
        border: 1px solid rgba(217, 70, 239, 170);
    }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{ background: rgba(19, 16, 30, 220); color: {MUTED}; border: 1px solid rgba(124, 58, 237, 110); padding: 10px 18px; margin-right: 4px; border-radius: 8px; }}
    QTabBar::tab:selected {{ background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #59317D, stop: 1 {HEADER}); color: #FFFFFF; border: 1px solid {ACCENT}; }}
    QTabBar::tab:hover {{ background: #30204E; color: {ACCENT}; border: 1px solid rgba(217, 70, 239, 190); }}
    QTableWidget {{ background: rgba(11, 9, 20, 210); alternate-background-color: {CARD}; color: {TEXT}; border: 1px solid rgba(124, 58, 237, 110); border-radius: 8px; gridline-color: {BORDER}; selection-background-color: {BORDER}; selection-color: {TEXT}; }}
    QHeaderView::section {{ background: {HEADER}; color: {TEXT}; border: 0; border-right: 1px solid {BORDER}; padding: 9px 8px; font-weight: 700; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: rgba(11, 9, 20, 180); border: 0; margin: 2px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {HEADER}; border: 1px solid {ACCENT}; border-radius: 5px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {BORDER}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background: transparent; border: 0; }}
    QSlider::groove:horizontal {{ height: 6px; background: {BG}; border: 1px solid {BORDER}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {HEADER}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; background: {TEXT}; border: 2px solid {BORDER}; border-radius: 8px; }}
    QSplitter::handle {{ background: {BORDER}; width: 1px; }}
    QFrame#card {{ background: {wallpaper_panel}; border-color: {neon_soft}; }}
    QFrame#appHeader {{ border-color: {neon_border}; }}
    QPushButton {{ border-color: {wallpaper_border}; }}
    QPushButton:hover {{ border-color: {wallpaper_accent}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ border-color: {wallpaper_border}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {neon_border}; }}
    QLabel#metricValue {{ color: {wallpaper_accent}; }}
    QFrame#card, QFrame#appHeader, QFrame#sidebar, QFrame#upcomingBannersSection {{
        background-color: {wallpaper_panel};
    }}
    QPushButton#primaryAction, QPushButton#damageCalculateButton {{ border-color: {selected_accent}; color: {selected_accent}; }}
    QPushButton#primaryAction:hover, QPushButton#damageCalculateButton:hover {{ border-color: {selected_accent}; }}
    QLabel#metricValue, QLabel#damageOutputValue, QLabel#historyMetricValue {{ color: {selected_accent}; }}
    QFrame#damageFormulaBox {{
        background: {wallpaper_surface};
        border: 1px solid {wallpaper_border};
        border-left: 3px solid {wallpaper_accent};
        border-radius: 7px;
    }}
    QLabel#damageFormula {{ color: {wallpaper_muted}; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; }}
    QFrame#damageInputGroup {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
    }}
    QLabel#damageGroupTitle {{ color: {wallpaper_accent}; font-size: 10px; font-weight: 900; letter-spacing: 1px; }}
    QLabel#damageInputLabel {{ color: {TEXT}; font-size: 10px; font-weight: 700; }}
    QAbstractSpinBox#damageInput {{ background: {wallpaper_surface}; color: {TEXT}; border: 1px solid {wallpaper_border}; border-radius: 5px; padding: 4px 6px; min-width: 86px; }}
    QAbstractSpinBox#damageInput:focus {{ border-color: {wallpaper_accent}; }}
    QPushButton#damageCalculateButton {{
        background: {wallpaper_panel};
        color: {wallpaper_accent};
        border: 1px solid {wallpaper_accent};
        border-radius: 7px;
        padding: 10px;
        font-size: 12px;
        font-weight: 900;
    }}
    QPushButton#damageCalculateButton:hover {{ background: {wallpaper_surface}; border: 2px solid {wallpaper_accent}; }}
    QFrame#damageOutputCard {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
    }}
    QLabel#damageOutputTitle {{ color: {wallpaper_muted}; font-size: 9px; font-weight: 900; letter-spacing: 1px; }}
    QLabel#damageOutputValue {{ color: {wallpaper_accent}; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 20px; font-weight: 900; }}
    QFrame#historyTeamSummary {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 10px;
    }}
    QLabel#historyTeamMembers {{
        color: {TEXT};
        background: {wallpaper_surface};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
        padding: 14px 10px;
        font-size: 13px;
        font-weight: 700;
    }}
    QFrame#historyQuickMetric {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
    }}
    QLabel#historyMetricCaption {{ color: {wallpaper_muted}; font-size: 9px; font-weight: 900; letter-spacing: 1px; }}
    QLabel#historyMetricValue {{ color: {wallpaper_accent}; font-size: 22px; font-weight: 900; }}
    QFrame#historyStatCard {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 9px;
    }}
    QFrame#historyStatCard:hover {{ border-color: {wallpaper_accent}; background: {wallpaper_surface}; }}
    QFrame#historyStatCard QLabel#metricValue {{ color: {wallpaper_accent}; font-size: 20px; font-weight: 900; }}
    QTableWidget#historyAuditTable, QTableWidget#historySavedTable {{
        background: {wallpaper_surface};
        alternate-background-color: {wallpaper_panel};
        color: {TEXT};
        border: 1px solid {wallpaper_border};
        gridline-color: {wallpaper_border};
        selection-background-color: {wallpaper_border};
        selection-color: {TEXT};
    }}
    QTableWidget#historyAuditTable::item:hover, QTableWidget#historySavedTable::item:hover {{
        background: {wallpaper_surface};
    }}
    QMainWindow {{ background-color: {wallpaper_surface}; }}
    QWidget#appShell {{ background: transparent; color: {text_primary}; }}
    QFrame#sidebar {{ background-color: {wallpaper_panel}; border-right-color: {wallpaper_border}; }}
    QFrame#card, QFrame#appHeader {{ background-color: {wallpaper_panel}; border-color: {neon_soft}; }}
    QFrame#upcomingBannersSection, QFrame#upcomingBannerCard, QFrame#upcomingBannerPastCard {{ background-color: {wallpaper_panel}; border-color: {wallpaper_border}; }}
    QFrame#bannerTimeline, QFrame#bannerImageContainer, QFrame#bannerHud {{ background-color: {wallpaper_panel}; border-color: {wallpaper_border}; }}
    QPushButton#nav, QPushButton#navActive {{ background-color: {wallpaper_panel}; color: {TEXT}; border: 1px solid {wallpaper_border}; }}
    QPushButton#nav:hover {{ background-color: {wallpaper_surface}; color: {TEXT}; border: 2px solid {selected_accent}; }}
    QPushButton#navActive {{ background-color: {neon_soft}; color: {TEXT}; border: 1px solid {selected_accent}; font-weight: 800; }}
    QPushButton#navActive:hover {{ background-color: {neon_border}; color: #FFFFFF; border: 2px solid {selected_accent}; }}
    QPushButton#nav[sidebarCharacter="true"], QPushButton#navActive[sidebarCharacter="true"] {{ padding-right: 32px; }}
    QToolButton#tabClose {{ color: {wallpaper_muted}; background: transparent; border: 1px solid transparent; border-radius: 4px; }}
    QToolButton#tabClose:hover {{ color: {TEXT}; background: {neon_soft}; border: 2px solid {selected_accent}; }}
    QTabWidget#mainTabs, QTabWidget#mainTabs::pane {{ background: transparent; }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{ background-color: {wallpaper_panel}; color: {TEXT}; border-color: {wallpaper_border}; }}
    QPushButton#primaryAction {{ background: {wallpaper_panel}; color: {TEXT}; border-color: {neon_border}; }}
    QPushButton#primaryAction:hover {{ background: {neon_soft}; color: {TEXT}; border: 2px solid {selected_accent}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ background-color: {wallpaper_surface}; border-color: {neon_border}; }}
    QLineEdit:hover {{ background-color: {wallpaper_surface}; border: 2px solid {neon_border}; }}
    QTableWidget {{ background-color: {wallpaper_panel}; alternate-background-color: {wallpaper_surface}; border-color: {wallpaper_border}; }}
    QHeaderView::section {{ background-color: {wallpaper_surface}; color: {TEXT}; border-color: {wallpaper_border}; }}
    QTabBar::tab {{ background-color: {wallpaper_panel}; color: {wallpaper_muted}; border-color: {wallpaper_border}; }}
    QTabBar::tab:selected {{ background-color: {wallpaper_surface}; border-color: {wallpaper_accent}; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background-color: {wallpaper_surface}; }}
    QSlider::groove:horizontal {{ background-color: {wallpaper_surface}; border-color: {wallpaper_border}; }}
    QLabel#title, QLabel#bannerName, QLabel#bannerQuote, QLabel#bannerSubtitle,
    QLabel#damageInputLabel, QLabel#damageFormula, QLabel#muted, QLabel#eyebrow,
    QLabel#skillTitle, QLabel#skillNumber, QLabel#historyTeamMembers {{
        background: transparent;
        opacity: 1.0;
    }}
    QLabel#title {{ color: {GOLD}; }}
    QLabel#bannerName, QLabel#skillTitle {{ color: {text_primary}; }}
    QLabel#bannerQuote {{ color: {text_secondary}; }}
    QLabel#bannerSubtitle, QLabel#muted, QLabel#eyebrow {{ color: {text_secondary}; }}
    QLabel#damageInputLabel, QLabel#damageFormula, QLabel#historyTeamMembers {{ color: {text_primary}; }}
    QTabWidget#mainTabs QLabel {{
        color: {text_primary};
        background: transparent;
    }}
    QFrame#topBanner QLabel {{
        color: {text_primary};
        background: transparent;
    }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Aero"] {{ color: #E8FFF8; }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Glacio"] {{ color: #E4F8FF; }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Electro"] {{ color: #F0E8FF; }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Fusion"] {{ color: #FFF0E8; }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Havoc"] {{ color: #FFE8EE; }}
    QTabWidget#mainTabs QLabel#bannerBadge[element="Spectro"] {{ color: #FFF8D6; }}
    QFrame#card, QFrame#appHeader, QFrame#sidebar, QFrame#upcomingBannersSection {{
        background-color: {wallpaper_panel};
    }}
    /* Final adaptive layer: surfaces and interaction states follow the wallpaper. */
    QPushButton {{
        background: {wallpaper_panel};
        color: {text_primary};
        border: 1px solid {wallpaper_border};
    }}
    QPushButton:hover {{
        background: {wallpaper_surface};
        color: {text_primary};
        border: 2px solid {wallpaper_accent};
    }}
    QPushButton:pressed {{
        background: {wallpaper_accent};
        color: #FFFFFF;
        border: 2px solid {wallpaper_accent};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
        background: {wallpaper_panel};
        color: {text_primary};
        border: 1px solid {wallpaper_border};
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTextEdit:hover,
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{
        background: {wallpaper_surface};
        border: 2px solid {wallpaper_accent};
    }}
    QCheckBox {{
        color: {text_primary};
        spacing: 10px;
        font-weight: 700;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 2px solid {wallpaper_border};
        background: rgba(255, 255, 255, 0.04);
    }}
    QCheckBox::indicator:hover {{
        border: 2px solid {wallpaper_accent};
        background: rgba(255, 255, 255, 0.08);
    }}
    QCheckBox::indicator:checked {{
        background: transparent;
        border: 2px solid {selected_accent};
        image: url("{get_asset_path('checkmark.svg').as_posix()}");
        image-position: center;
        qproperty-icon: none;
    }}
    QCheckBox::indicator:checked:hover {{
        border: 2px solid {wallpaper_accent};
    }}
    QComboBox QAbstractItemView {{
        background: {wallpaper_panel};
        color: {TEXT};
        border: 1px solid {wallpaper_accent};
        selection-background-color: {wallpaper_surface};
        selection-color: {TEXT};
    }}
    QTabBar::tab:hover, QTabBar::tab:selected {{
        background: {wallpaper_surface};
        color: {TEXT};
        border: 2px solid {wallpaper_accent};
    }}
    QSlider::groove:horizontal {{
        background: {wallpaper_surface};
        border: 1px solid {wallpaper_border};
    }}
    QSlider::sub-page:horizontal {{ background: {wallpaper_accent}; }}
    QSlider::handle:horizontal {{ background: {TEXT}; border: 2px solid {wallpaper_accent}; }}
    QTableWidget, QTreeWidget, QListWidget {{
        background: {wallpaper_panel};
        alternate-background-color: {wallpaper_surface};
        color: {TEXT};
        border: 1px solid {wallpaper_border};
        gridline-color: {wallpaper_border};
    }}
    QWidget#historyPage {{ background: transparent; }}
    QLabel#historyPageIcon {{ color: {selected_accent}; font-size: 30px; font-weight: 900; }}
    QLabel#historyPageTitle {{ color: #F4F7FF; font-size: 20px; font-weight: 900; }}
    QLabel#historyPageSubtitle {{ color: #9BAAC0; font-size: 10px; }}
    QFrame#historyTeamSummary, QFrame#historyQuickMetrics,
    QFrame#historyAnalysisPanel, QFrame#historyAuditPanel, QFrame#historySavedPanel,
    QFrame#historyQuickMetric, QFrame#historyStatCard,
    QFrame#historyAuditTable, QFrame#historySavedTable {{
        background-color: rgba(14, 18, 27, 218);
        border: 1px solid rgba(255, 255, 255, 20);
        border-radius: 12px;
    }}
    QFrame#historyTeamSummary, QFrame#historyAnalysisPanel,
    QFrame#historyAuditPanel, QFrame#historySavedPanel, QFrame#historyQuickMetric,
    QFrame#historyStatCard {{ border-color: rgba(90, 150, 235, 58); }}
    QPushButton#historyEditButton, QPushButton#historyViewButton,
    QPushButton#historyViewActive {{
        color: #D8E7FF;
        background: rgba(16, 28, 48, 180);
        border: 1px solid rgba(95, 157, 235, 90);
        border-radius: 13px;
        padding: 3px 10px;
        font-size: 9px;
        font-weight: 800;
    }}
    QPushButton#historyViewActive {{
        color: #FFFFFF;
        background: {selected_accent};
        border-color: {selected_accent};
    }}
    QPushButton#historyEditButton:hover, QPushButton#historyViewButton:hover {{
        border-color: {selected_accent}; color: #FFFFFF;
    }}
    QLabel#historyBannerPreview {{
        background: rgba(11, 22, 37, 145);
        border: 1px solid rgba(100, 170, 240, 82);
        border-radius: 12px;
        padding: 0;
    }}
    QLabel#historyEmptyState {{
        color: #9BAAC0;
        background: rgba(7, 15, 26, 145);
        border: 1px solid rgba(90, 150, 235, 45);
        border-radius: 10px;
        font-size: 10px;
        padding: 18px;
    }}
    QLabel#echoPreview {{
        color: {wallpaper_accent};
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
        font-size: 34px;
    }}
    QLabel#echoSectionHeading {{
        color: {TEXT};
        font-size: 13px;
        font-weight: 800;
        padding: 4px 8px;
    }}
    QScrollArea#echoScrollArea {{
        background: transparent;
        border: 0;
    }}
    QScrollArea#echoScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollArea#echoScrollArea QScrollBar:vertical {{
        background: rgba(10, 16, 28, 120);
        border: 0;
        width: 8px;
        margin: 2px 0;
    }}
    QScrollArea#echoScrollArea QScrollBar::handle:vertical {{
        background: rgba(120, 150, 230, 150);
        border: 1px solid rgba(180, 200, 255, 110);
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollArea#echoScrollArea QScrollBar::handle:vertical:hover {{
        background: {wallpaper_accent};
    }}
    QScrollArea#echoScrollArea QScrollBar::add-line:vertical,
    QScrollArea#echoScrollArea QScrollBar::sub-line:vertical {{
        height: 0;
        background: transparent;
        border: 0;
    }}
    QFrame#echoPreviewFrame {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
        padding: 6px 10px;
        margin: 2px;
        min-height: 198px;
    }}
    QLabel#echoPreviewMeta {{
        color: #FFFFFF;
        font-size: 13px;
        font-weight: 800;
        background: transparent;
    }}
    QLabel#echoPreviewDetails {{
        color: #D1D5DB;
        font-size: 11px;
        line-height: 1.3;
        background: transparent;
    }}
    QFrame#echoSummaryFrame {{
        background: {wallpaper_panel};
        border: 1px solid {wallpaper_border};
        border-radius: 8px;
    }}
    QLabel#echoSummaryText {{
        color: #D1D5DB;
        font-size: 13px;
        font-weight: 800;
        background: transparent;
    }}
    QLineEdit#historySearch {{
        color: #DCEBFF;
        background: rgba(7, 15, 28, 175);
        border: 1px solid rgba(90, 150, 235, 90);
        border-radius: 12px;
        padding: 5px 10px;
        font-size: 9px;
    }}
    QLineEdit#historySearch:focus {{ border-color: {selected_accent}; }}
    QTableWidget#historyAuditTable, QTableWidget#historySavedTable {{
        background: rgba(7, 15, 26, 150);
        alternate-background-color: rgba(16, 30, 48, 150);
        border: 1px solid rgba(90, 150, 235, 70);
        border-radius: 9px;
        gridline-color: rgba(100, 150, 210, 40);
        selection-background-color: rgba(110, 75, 230, 130);
        selection-color: #F4F7FF;
    }}
    QTableWidget#historyAuditTable::item:selected,
    QTableWidget#historySavedTable::item:selected,
    QTableWidget#historyAuditTable::item:selected:hover,
    QTableWidget#historySavedTable::item:selected:hover {{
        background: rgba(110, 75, 230, 180);
        color: #F4F7FF;
    }}
    QTableWidget#historyAuditTable QHeaderView::section,
    QTableWidget#historySavedTable QHeaderView::section {{
        color: #C8D8ED;
        background: rgba(15, 28, 46, 210);
        border: 0;
        border-right: 1px solid rgba(100, 150, 210, 42);
        padding: 7px;
        font-size: 9px;
        font-weight: 800;
    }}
    """