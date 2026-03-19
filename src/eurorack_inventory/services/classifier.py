from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part

if TYPE_CHECKING:
    from eurorack_inventory.services.settings import ClassifierSettings


@dataclass(frozen=True, slots=True)
class PartCompatibility:
    """Ranked list of storage classes a part can use, with penalties."""

    preferred: StorageClass  # penalty = 0
    acceptable: tuple[tuple[StorageClass, float], ...]  # (class, penalty)
    forbidden: frozenset[StorageClass]  # never place here

    def penalty_for(self, sc: StorageClass) -> float | None:
        """Return penalty (0.0 preferred, >0 acceptable, None forbidden)."""
        if sc == self.preferred:
            return 0.0
        for cls, pen in self.acceptable:
            if cls == sc:
                return pen
        return None

    def compatible_classes(self) -> list[StorageClass]:
        """All classes this part can use, preferred first."""
        result = [self.preferred]
        result.extend(cls for cls, _ in self.acceptable)
        return result


_COMPAT_MATRIX: dict[StorageClass, PartCompatibility] = {
    # Small parts: fit anywhere
    StorageClass.SMALL_SHORT_CELL: PartCompatibility(
        preferred=StorageClass.SMALL_SHORT_CELL,
        acceptable=(
            (StorageClass.LARGE_CELL, 0.3),
            (StorageClass.LONG_CELL, 0.5),
            (StorageClass.BINDER_CARD, 0.8),
        ),
        forbidden=frozenset(),
    ),
    # Large parts: large or long cells (long is large by definition), or binders.
    # Cannot fit in small cells.
    StorageClass.LARGE_CELL: PartCompatibility(
        preferred=StorageClass.LARGE_CELL,
        acceptable=(
            (StorageClass.LONG_CELL, 0.3),
            (StorageClass.BINDER_CARD, 0.8),
        ),
        forbidden=frozenset({StorageClass.SMALL_SHORT_CELL}),
    ),
    # Long parts: only long cells or binders.
    # Cannot fit in small cells or large-only cells (not long enough).
    StorageClass.LONG_CELL: PartCompatibility(
        preferred=StorageClass.LONG_CELL,
        acceptable=(
            (StorageClass.BINDER_CARD, 0.8),
        ),
        forbidden=frozenset({StorageClass.SMALL_SHORT_CELL, StorageClass.LARGE_CELL}),
    ),
    # Binder parts: binders preferred, but no restriction on where they can go
    StorageClass.BINDER_CARD: PartCompatibility(
        preferred=StorageClass.BINDER_CARD,
        acceptable=(
            (StorageClass.SMALL_SHORT_CELL, 0.6),
            (StorageClass.LARGE_CELL, 0.8),
            (StorageClass.LONG_CELL, 0.9),
        ),
        forbidden=frozenset(),
    ),
}

_IC_PATTERN = re.compile(
    r"\bics?\b|integrated circuit|op[\s\-]?amp|opamp|comparator|regulator|microcontroller|\bmcu\b"
    r"|\bdac\b|\badc\b|\bfpga\b|\btimer\b|\b555\b|shift\s*register"
    r"|\bbuffer\b|\bdriver\b|\bmultiplexer\b|\bmux\b|\boscillator\b|\bcpld\b",
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

_TRANSISTOR_PATTERN = re.compile(
    r"transistor|\bmosfet\b|\bjfet\b|\bbjt\b|\b2n\d{3,4}\b|\bbc\d{3}\b|\birf\d+\b|\bbs170\b",
    re.IGNORECASE,
)

_THROUGH_HOLE_PACKAGE_PATTERN = re.compile(
    r"\bto[\-\s]?92\b|\bto[\-\s]?220\b|\bto[\-\s]?247\b|\bto[\-\s]?3\b",
    re.IGNORECASE,
)

_LARGE_PART_PATTERN = re.compile(
    r"switch|potentiometer|\bpot\b|jack|socket|connector|encoder|relay|transformer|header"
    r"|standoff|spacer|\bknob\b|fuse|terminal|mounting|bracket|heat\s*sink"
    r"|\bdisplay\b|\blcd\b|\boled\b",
    re.IGNORECASE,
)

_PASSIVE_PATTERN = re.compile(
    r"resistor|capacitor|\bcap\b|diode|trimmer|\bleds?\b",
    re.IGNORECASE,
)

_LONG_PART_PATTERN = re.compile(
    r"resistor|diode|\bleds?\b|electrolytic|film\s*cap|\bradial\b|\baxial\b",
    re.IGNORECASE,
)

# SMT size codes in the name indicate surface-mount (small, not long).
# Use lookahead/lookbehind instead of \b to avoid matching inside part numbers
# like "R0805-series" or "Model1206X".
_SMT_SIZE_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9])(?:0201|0402|0603|0805|1206|1210|1812|2010|2512)(?![a-zA-Z0-9])"
    r"|\bsmt\b|\bsmd\b|\bsurface[\s\-]?mount",
    re.IGNORECASE,
)

# Default quantity thresholds
DEFAULT_SMALL_COMPONENT_QTY_LIMIT = 100
DEFAULT_DIP_IC_QTY_LIMIT = 6
DEFAULT_THROUGH_HOLE_SMALL_QTY_LIMIT = 6


def _is_smt(part: Part) -> bool:
    """Check if a part is surface-mount based on name/package keywords."""
    text = f"{part.name or ''} {part.default_package or ''}"
    return bool(_SMT_SIZE_PATTERN.search(text))


def classify_part(
    part: Part,
    settings: ClassifierSettings | None = None,
) -> StorageClass:
    """Classify a part into a storage class based on its category, name, package, and qty.

    If *settings* is provided the user-configured thresholds are used,
    otherwise built-in defaults apply.
    """
    if part.storage_class_override:
        try:
            return StorageClass(part.storage_class_override)
        except ValueError:
            pass

    if settings is not None:
        small_component_qty_limit = settings.small_component_qty_limit
        dip_ic_qty_limit = settings.dip_ic_qty_limit
        through_hole_small_qty_limit = settings.through_hole_small_qty_limit
    else:
        small_component_qty_limit = DEFAULT_SMALL_COMPONENT_QTY_LIMIT
        dip_ic_qty_limit = DEFAULT_DIP_IC_QTY_LIMIT
        through_hole_small_qty_limit = DEFAULT_THROUGH_HOLE_SMALL_QTY_LIMIT

    text = f"{part.category or ''} {part.name or ''}"
    package_text = f"{part.name or ''} {part.default_package or ''}"

    # Rule 1-3: ICs
    if _IC_PATTERN.search(text):
        if _SMT_FOOTPRINT_PATTERN.search(package_text):
            return StorageClass.BINDER_CARD
        if _DIP_PATTERN.search(package_text) and part.qty < dip_ic_qty_limit:
            return StorageClass.SMALL_SHORT_CELL
        return StorageClass.BINDER_CARD

    # Rule 3.5: Transistors
    if _TRANSISTOR_PATTERN.search(text):
        if _SMT_FOOTPRINT_PATTERN.search(package_text) or _SMT_SIZE_PATTERN.search(package_text):
            return StorageClass.BINDER_CARD
        if _THROUGH_HOLE_PACKAGE_PATTERN.search(package_text) and part.qty < dip_ic_qty_limit:
            return StorageClass.SMALL_SHORT_CELL
        return StorageClass.BINDER_CARD

    # Rule 4: Large mechanical parts
    if _LARGE_PART_PATTERN.search(text):
        return StorageClass.LARGE_CELL

    # Rule 5: Through-hole resistors, diodes, LEDs, electrolytic/film caps → long cells
    # (SMT versions of these go to small cells below)
    if (_LONG_PART_PATTERN.search(text) or _LONG_PART_PATTERN.search(package_text)) and not _is_smt(part):
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
    logger.debug(
        "Part %r (category=%r) fell through to SMALL_SHORT_CELL fallback",
        part.name,
        part.category,
    )
    return StorageClass.SMALL_SHORT_CELL


def classify_part_compat(
    part: Part,
    settings: ClassifierSettings | None = None,
) -> PartCompatibility:
    """Classify a part and return its full compatibility profile."""
    preferred = classify_part(part, settings)
    return _COMPAT_MATRIX[preferred]
