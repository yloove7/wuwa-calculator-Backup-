"""Optional native acceleration with a transparent Python fallback."""

from importlib import import_module
from typing import Callable, cast

Component = tuple[int, int, int, int, float]
DamageEvent = tuple[int, int, int]
ComponentGrouper = Callable[[list[Component], int, int], list[DamageEvent]]

group_damage_components: ComponentGrouper | None = None
for _module_name in (
    "src.wuwa_calculator.native._tethys_native",
    "src.wuwa_calculator.native.Release._tethys_native",
):
    try:
        _native_module = import_module(_module_name)
    except ImportError:
        continue
    candidate = getattr(_native_module, "group_damage_components", None)
    if callable(candidate):
        group_damage_components = cast(ComponentGrouper, candidate)
        break

__all__ = ["group_damage_components"]
