"""Hard reject and soft warning rules for dedup candidate pairs."""
from __future__ import annotations

from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import ComponentFamily, PartSignature
from eurorack_inventory.services.common import normalize_text


def check_conflicts(
    part_a: Part,
    part_b: Part,
    sig_a: PartSignature,
    sig_b: PartSignature,
) -> tuple[list[str], list[str]]:
    """Check a candidate pair for hard rejects and soft warnings.

    Returns (hard_rejects, warnings).
    Hard rejects mean the pair should never be surfaced for review.
    Warnings reduce priority and flag fields for human attention.
    """
    hard: list[str] = []
    warnings: list[str] = []

    # ── Hard rejects ──────────────────────────────────────────────────────

    # Component family differs (neither UNKNOWN)
    if (
        sig_a.component_family != sig_b.component_family
        and sig_a.component_family != ComponentFamily.UNKNOWN
        and sig_b.component_family != ComponentFamily.UNKNOWN
    ):
        hard.append("component_family_differs")

    # Resistor value differs
    if (
        sig_a.value_ohms is not None
        and sig_b.value_ohms is not None
        and sig_a.component_family in (ComponentFamily.RESISTOR, ComponentFamily.POT)
        and sig_b.component_family in (ComponentFamily.RESISTOR, ComponentFamily.POT)
    ):
        if not _values_within_tolerance(sig_a.value_ohms, sig_b.value_ohms, 0.01):
            if sig_a.component_family == ComponentFamily.POT:
                hard.append("pot_value_differs")
            else:
                hard.append("resistor_value_differs")

    # Capacitor value differs
    if (
        sig_a.value_pf is not None
        and sig_b.value_pf is not None
    ):
        if not _values_within_tolerance(sig_a.value_pf, sig_b.value_pf, 0.01):
            hard.append("capacitor_value_differs")

    # Connector pin count differs
    if sig_a.pin_count is not None and sig_b.pin_count is not None:
        if sig_a.pin_count != sig_b.pin_count:
            if (
                sig_a.connector_subtype == "dip_socket"
                or sig_b.connector_subtype == "dip_socket"
            ):
                hard.append("dip_socket_pin_count_differs")
            else:
                hard.append("connector_pin_count_differs")

    # Connector pitch differs
    if sig_a.pitch_um is not None and sig_b.pitch_um is not None:
        if sig_a.pitch_um != sig_b.pitch_um:
            hard.append("connector_pitch_differs")

    # Connector subtype differs
    if sig_a.connector_subtype is not None and sig_b.connector_subtype is not None:
        if sig_a.connector_subtype != sig_b.connector_subtype:
            hard.append("connector_subtype_differs")

    # Switch function differs
    if sig_a.component_family == ComponentFamily.SWITCH and sig_b.component_family == ComponentFamily.SWITCH:
        # Momentary vs non-momentary
        if (sig_a.momentary_positions is not None) != (sig_b.momentary_positions is not None):
            hard.append("switch_function_differs")
        # Action pattern differs (e.g. ON-ON vs ON-OFF-ON)
        elif (
            sig_a.action_pattern is not None
            and sig_b.action_pattern is not None
            and sig_a.action_pattern != sig_b.action_pattern
        ):
            hard.append("switch_function_differs")

    # Package technology differs (SMD vs THT)
    if (
        sig_a.mounting is not None
        and sig_b.mounting is not None
        and sig_a.mounting != sig_b.mounting
        and sig_a.mounting in ("smd", "through_hole")
        and sig_b.mounting in ("smd", "through_hole")
    ):
        hard.append("package_technology_differs")

    # Semiconductor base device differs
    if (
        sig_a.base_device is not None
        and sig_b.base_device is not None
        and sig_a.base_device != sig_b.base_device
    ):
        hard.append("semiconductor_base_device_differs")

    # ── Soft warnings ─────────────────────────────────────────────────────

    # Disjoint Tayda SKU
    if part_a.supplier_sku and part_b.supplier_sku:
        skus_a = _parse_sku_set(part_a.supplier_sku)
        skus_b = _parse_sku_set(part_b.supplier_sku)
        if skus_a and skus_b and not skus_a & skus_b:
            warnings.append("disjoint_tayda_sku")

    # Different manufacturer
    if part_a.manufacturer and part_b.manufacturer:
        if normalize_text(part_a.manufacturer) != normalize_text(part_b.manufacturer):
            warnings.append("different_manufacturer")

    # Packing suffix differs (same base device)
    if (
        sig_a.base_device is not None
        and sig_b.base_device is not None
        and sig_a.base_device == sig_b.base_device
        and sig_a.packing_suffix is not None
        and sig_b.packing_suffix is not None
        and sig_a.packing_suffix != sig_b.packing_suffix
    ):
        warnings.append("packing_suffix_differs")

    # Generic vs specific: one side has parsed fields the other lacks
    if _is_generic_vs_specific(sig_a, sig_b):
        warnings.append("generic_vs_specific")

    # Different tolerance
    if sig_a.tolerance is not None and sig_b.tolerance is not None:
        if sig_a.tolerance != sig_b.tolerance:
            warnings.append("different_tolerance")

    # Different voltage rating
    if sig_a.voltage_rating is not None and sig_b.voltage_rating is not None:
        if sig_a.voltage_rating != sig_b.voltage_rating:
            warnings.append("different_voltage_rating")

    return hard, warnings


def _values_within_tolerance(a: float, b: float, tolerance: float) -> bool:
    """Check if two values are within a relative tolerance of each other."""
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance


def _parse_sku_set(sku_str: str) -> set[str]:
    """Parse a SKU field that may contain multiple SKUs separated by / or ,."""
    parts = set()
    for sep in ("/", ","):
        if sep in sku_str:
            for s in sku_str.split(sep):
                s = s.strip().upper()
                if s:
                    parts.add(s)
            return parts
    s = sku_str.strip().upper()
    if s:
        parts.add(s)
    return parts


def _is_generic_vs_specific(sig_a: PartSignature, sig_b: PartSignature) -> bool:
    """Check if one signature is a generic version and the other is specific.

    E.g. "10uF capacitor" (no package/mounting) vs "10uF capacitor (0805 SMD)".
    """
    if sig_a.component_family != sig_b.component_family:
        return False

    specificity_fields = ("package", "mounting", "tolerance", "dielectric", "voltage_rating", "wattage")
    a_count = sum(1 for f in specificity_fields if getattr(sig_a, f, None) is not None)
    b_count = sum(1 for f in specificity_fields if getattr(sig_b, f, None) is not None)

    # One side has significantly more parsed detail
    return abs(a_count - b_count) >= 2
