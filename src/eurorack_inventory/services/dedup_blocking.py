"""Category-aware typed candidate generation for dedup.

Uses family-specific blocking rules to generate candidate pairs,
replacing broad same-category fuzzy matching.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

from rapidfuzz import fuzz

from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import ComponentFamily, PartSignature
from eurorack_inventory.services.common import normalize_text


def generate_candidates(
    parts: list[Part],
    signatures: dict[int, PartSignature],
    suppressed: set[tuple[int, int]],
) -> list[tuple[int, int, list[str]]]:
    """Generate candidate duplicate pairs using typed blocking rules.

    Returns list of (id_a, id_b, block_reasons) tuples.
    Suppressed pairs (from dedup_feedback) are filtered out.
    """
    seen: dict[tuple[int, int], list[str]] = {}

    def _add(id_a: int, id_b: int, reason: str) -> None:
        key = (min(id_a, id_b), max(id_a, id_b))
        if key in suppressed:
            return
        seen.setdefault(key, []).append(reason)

    parts_by_id = {p.id: p for p in parts if p.id is not None}

    # ── Rule 1: Exact or overlapping Tayda SKU ────────────────────────────
    sku_groups: dict[str, list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None or not p.supplier_sku:
            continue
        for sku in _parse_sku_set(p.supplier_sku):
            if sku:
                sku_groups[sku].append(p.id)
    for ids in sku_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "exact_sku")

    # ── Rule 2: Exact orderable MPN ───────────────────────────────────────
    mpn_groups: dict[str, list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        norm_mpn = normalize_text(p.mpn)
        if norm_mpn:
            mpn_groups[norm_mpn].append(p.id)
    for ids in mpn_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "exact_mpn")

    # ── Rule 3: Same base semiconductor device + same package ─────────────
    semi_groups: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.base_device:
            semi_groups[(sig.base_device, sig.package)].append(p.id)
    for ids in semi_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_base_device")

    # ── Rule 4: Same resistor value + same mounting/package class ─────────
    res_groups: dict[tuple[float, str | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.component_family == ComponentFamily.RESISTOR and sig.value_ohms is not None:
            res_groups[(sig.value_ohms, sig.mounting)].append(p.id)
    for ids in res_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_resistor")

    # ── Rule 5: Same capacitor value + same mounting/package class ────────
    cap_groups: dict[tuple[float, str | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.component_family == ComponentFamily.CAPACITOR and sig.value_pf is not None:
            cap_groups[(sig.value_pf, sig.mounting)].append(p.id)
    for ids in cap_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_capacitor")

    # ── Rule 6: Same connector subtype + pin count + pitch ────────────────
    conn_groups: dict[tuple[str, int | None, int | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.component_family == ComponentFamily.CONNECTOR and sig.connector_subtype:
            conn_groups[(sig.connector_subtype, sig.pin_count, sig.pitch_um)].append(p.id)
    for ids in conn_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_connector")

    # ── Rule 7: Same pot value + taper + form factor ──────────────────────
    pot_groups: dict[tuple[float | None, str | None, int | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.component_family == ComponentFamily.POT and sig.value_ohms is not None:
            pot_groups[(sig.value_ohms, sig.taper, sig.body_size_mm)].append(p.id)
    for ids in pot_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_pot")

    # ── Rule 8: Same switch functional signature ──────────────────────────
    sw_groups: dict[tuple[str | None, str | None], list[int]] = defaultdict(list)
    for p in parts:
        if p.id is None:
            continue
        sig = signatures.get(p.id)
        if sig and sig.component_family == ComponentFamily.SWITCH:
            sw_groups[(sig.pole_throw, sig.action_pattern)].append(p.id)
    for ids in sw_groups.values():
        for a, b in itertools.combinations(ids, 2):
            _add(a, b, "same_switch")

    # ── Rule 9: Within-bucket fuzzy fallback ──────────────────────────────
    # For parts in the same blocking group, use fuzzy name matching
    # to catch lexical variants. Only within already-compatible buckets.
    _add_fuzzy_within_buckets(parts_by_id, seen, suppressed, _add)

    # ── Build result ──────────────────────────────────────────────────────
    return [(a, b, reasons) for (a, b), reasons in seen.items()]


def _add_fuzzy_within_buckets(
    parts_by_id: dict[int, Part],
    existing: dict[tuple[int, int], list[str]],
    suppressed: set[tuple[int, int]],
    add_fn: object,
) -> None:
    """Within existing blocking groups, add fuzzy name matches.

    This catches lexical variants like "100K Resistor 1/4W" vs "100K Resistor 1/4 Watt".
    Only runs within pairs already in the same bucket — never cross-bucket.
    """
    # Collect all part IDs that appeared in any bucket
    bucket_members: set[int] = set()
    for (a, b) in existing:
        bucket_members.add(a)
        bucket_members.add(b)

    # Group by same category for fuzzy fallback
    cat_groups: dict[str, list[int]] = defaultdict(list)
    for pid in bucket_members:
        p = parts_by_id.get(pid)
        if p and p.category:
            cat_groups[normalize_text(p.category)].append(pid)

    threshold = 85.0
    for ids in cat_groups.values():
        for i, id_a in enumerate(ids):
            pa = parts_by_id.get(id_a)
            if pa is None:
                continue
            for id_b in ids[i + 1:]:
                key = (min(id_a, id_b), max(id_a, id_b))
                if key in existing or key in suppressed:
                    continue
                pb = parts_by_id.get(id_b)
                if pb is None:
                    continue
                score = fuzz.token_sort_ratio(pa.normalized_name, pb.normalized_name)
                if score >= threshold:
                    existing.setdefault(key, []).append("fuzzy_name")


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
