from __future__ import annotations

import re
from typing import TYPE_CHECKING

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part

if TYPE_CHECKING:
    from eurorack_inventory.services.settings import ClassifierSettings

_IC_PATTERN = re.compile(
    r"\bics?\b|integrated circuit|op[\s\-]?amp|opamp|comparator|regulator|microcontroller|\bmcu\b",
    re.IGNORECASE,
)

_SMT_FOOTPRINT_PATTERN = re.compile(
    r"\bsoic\b|\bsop\b|\bqfp\b|\bssop\b|\btssop\b|\bsmd\b|\bsmt\b|\bbga\b|\bdfn\b|\bqfn\b",
    re.IGNORECASE,
)

_DIP_PATTERN = re.compile(
    r"\bdip\b|\bpdip\b|through[\s\-]?hole",
    re.IGNORECASE,
)

_LARGE_PART_PATTERN = re.compile(
    r"switch|potentiometer|\bpot\b|jack|socket|connector|encoder|relay|transformer|header",
    re.IGNORECASE,
)

_PASSIVE_PATTERN = re.compile(
    r"resistor|capacitor|\bcap\b|diode|trimmer|\bleds?\b",
    re.IGNORECASE,
)

_LONG_PART_PATTERN = re.compile(
    r"resistor|diode|\bleds?\b",
    re.IGNORECASE,
)

# SMT size codes in the name indicate surface-mount (small, not long)
_SMT_SIZE_PATTERN = re.compile(
    r"\b0201\b|\b0402\b|\b0603\b|\b0805\b|\b1206\b|\b1210\b|\b1812\b|\b2010\b|\b2512\b"
    r"|\bsmt\b|\bsmd\b|\bsurface[\s\-]?mount",
    re.IGNORECASE,
)

# Default quantity thresholds
DEFAULT_SMALL_COMPONENT_QTY_LIMIT = 100
DEFAULT_DIP_IC_QTY_LIMIT = 6
DEFAULT_THROUGH_HOLE_SMALL_QTY_LIMIT = 6


def _is_smt(part: Part) -> bool:
    """Check if a part is surface-mount based on name keywords."""
    return bool(_SMT_SIZE_PATTERN.search(part.name or ""))


def classify_part(
    part: Part,
    settings: ClassifierSettings | None = None,
) -> StorageClass:
    """Classify a part into a storage class based on its category, name, package, and qty.

    If *settings* is provided the user-configured thresholds are used,
    otherwise built-in defaults apply.
    """
    if settings is not None:
        small_component_qty_limit = settings.small_component_qty_limit
        dip_ic_qty_limit = settings.dip_ic_qty_limit
        through_hole_small_qty_limit = settings.through_hole_small_qty_limit
    else:
        small_component_qty_limit = DEFAULT_SMALL_COMPONENT_QTY_LIMIT
        dip_ic_qty_limit = DEFAULT_DIP_IC_QTY_LIMIT
        through_hole_small_qty_limit = DEFAULT_THROUGH_HOLE_SMALL_QTY_LIMIT

    text = f"{part.category or ''} {part.name or ''}"

    # Rule 1-3: ICs
    if _IC_PATTERN.search(text):
        if _SMT_FOOTPRINT_PATTERN.search(part.name or ""):
            return StorageClass.BINDER_CARD
        if _DIP_PATTERN.search(part.name or "") and part.qty < dip_ic_qty_limit:
            return StorageClass.SMALL_SHORT_CELL
        return StorageClass.BINDER_CARD

    # Rule 4: Large mechanical parts
    if _LARGE_PART_PATTERN.search(text):
        return StorageClass.LARGE_CELL

    # Rule 5: Through-hole resistors, diodes, LEDs → long cells
    # (SMT versions of these go to small cells below)
    if _LONG_PART_PATTERN.search(text) and not _is_smt(part):
        # Even through-hole: very small quantities can fit in a small cell
        if part.qty < through_hole_small_qty_limit:
            return StorageClass.SMALL_SHORT_CELL
        return StorageClass.LONG_CELL

    # Rule 6: Small passives (SMT resistors/diodes/LEDs, capacitors, trimmers)
    # Small qty → small cell; large qty → large cell (won't fit in a tiny compartment)
    if _PASSIVE_PATTERN.search(text):
        if part.qty >= small_component_qty_limit:
            return StorageClass.LARGE_CELL
        return StorageClass.SMALL_SHORT_CELL

    # Rule 7: Fallback
    return StorageClass.SMALL_SHORT_CELL
