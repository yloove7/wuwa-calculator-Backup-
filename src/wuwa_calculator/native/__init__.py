"""Optional native acceleration with a transparent Python fallback."""

try:
    from ._tethys_native import group_damage_components
except ImportError:
    try:
        from .Release._tethys_native import group_damage_components
    except ImportError:
        group_damage_components = None

__all__ = ["group_damage_components"]