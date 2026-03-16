"""Structured signature for deduplication identity comparison."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ComponentFamily(StrEnum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    CONNECTOR = "connector"
    POT = "pot"
    SWITCH = "switch"
    IC = "ic"
    DIODE = "diode"
    TRANSISTOR = "transistor"
    LED = "led"
    REGULATOR = "regulator"
    SENSOR = "sensor"
    UNKNOWN = "unknown"


class ReviewPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PartSignature:
    """Typed identity signature parsed from a Part's name and metadata.

    Fields are family-specific: most will be None for any given part.
    ``canonical_value`` is family-appropriate base units:
    ohms for resistors/pots, picofarads for capacitors.
    """

    component_family: ComponentFamily

    # ── Value (resistors, capacitors, pots) ──
    value_ohms: float | None = None
    value_pf: float | None = None
    value_display: str | None = None

    # ── Physical ──
    mounting: str | None = None       # "smd", "through_hole"
    package: str | None = None        # "0805", "DIP-8", "SOT-23"
    wattage: float | None = None
    tolerance: str | None = None
    voltage_rating: float | None = None

    # ── Capacitor-specific ──
    polarized: bool | None = None
    dielectric: str | None = None     # "C0G", "X7R", "electrolytic"

    # ── Connector-specific ──
    connector_subtype: str | None = None  # "female_header", "male_header_strip",
                                          # "dip_socket", "box_header", "audio_jack",
                                          # "power_header", "ic_socket"
    pin_count: int | None = None
    row_count: int | None = None
    pitch_um: int | None = None       # microns: 2540 for 2.54mm
    gender: str | None = None         # "male", "female"
    shrouded: bool | None = None
    machine_tooled: bool | None = None

    # ── Pot-specific ──
    taper: str | None = None          # "B" (linear), "A" (log), "C"
    body_size_mm: int | None = None   # 9, 16, 24
    shaft_style: str | None = None    # "spline", "round", "d-shaft"
    manufacturer_hint: str | None = None

    # ── Switch-specific ──
    pole_throw: str | None = None     # "SPDT", "DPDT", "SPST"
    action_pattern: str | None = None  # "ON-OFF-ON", "ON-ON", "ON-OFF"
    momentary_positions: tuple[str, ...] | None = None
    lever_style: str | None = None    # "standard", "short", "flat"

    # ── IC / Semiconductor ──
    orderable_mpn: str | None = None  # full MPN: "CD4070BM96"
    base_device: str | None = None    # "CD4070BM", "PT2399", "TL072"
    packing_suffix: str | None = None  # "96", "/TR", "-SN", ",115"
