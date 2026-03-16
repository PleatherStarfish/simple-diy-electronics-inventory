from __future__ import annotations

import itertools
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import Part
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.common import make_part_fingerprint, normalize_text
from eurorack_inventory.services.search import SearchService

logger = logging.getLogger(__name__)

# Matches tokens like "100nf", "10k", "4.7uf", "0.25w" — a number followed
# immediately by unit/prefix letters.  Used to reject fuzzy pairs where the
# component values clearly differ (e.g. "100nF" vs "10nF").
_VALUE_TOKEN_RE = re.compile(r"\d+\.?\d*[a-z]+")


def _extract_value_tokens(normalized_name: str) -> set[str]:
    """Extract component-value tokens from a normalized part name."""
    return set(_VALUE_TOKEN_RE.findall(normalized_name))


_MERGE_ADOPTABLE_FIELDS = (
    "manufacturer",
    "mpn",
    "supplier_name",
    "supplier_sku",
    "purchase_url",
    "default_package",
    "storage_class_override",
    "category",
)


@dataclass(slots=True)
class DuplicatePair:
    part_a: Part
    part_b: Part
    score: float
    match_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MergeResult:
    kept_part_id: int
    removed_part_id: int
    qty_added: int
    aliases_transferred: int
    bom_lines_remapped: int
    normalized_items_remapped: int
    discarded_slot_label: str | None


class DedupService:
    def __init__(
        self,
        db: Database,
        part_repo: PartRepository,
        audit_repo: AuditRepository,
        search_service: SearchService,
    ) -> None:
        self.db = db
        self.part_repo = part_repo
        self.audit_repo = audit_repo
        self.search_service = search_service

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def find_duplicate_pairs(self, threshold: float = 75.0) -> list[DuplicatePair]:
        parts = self.part_repo.list_parts()
        parts_by_id = {p.id: p for p in parts}

        # Collect candidate pairs as {(min_id, max_id): (score, reasons)}
        candidates: dict[tuple[int, int], tuple[float, list[str]]] = {}

        def _add(id_a: int, id_b: int, score: float, reason: str) -> None:
            key = (min(id_a, id_b), max(id_a, id_b))
            existing_score, existing_reasons = candidates.get(key, (0.0, []))
            if score > existing_score:
                candidates[key] = (score, [reason])
            elif score == existing_score:
                existing_reasons.append(reason)

        # Phase 1: exact key matches
        self._phase1_exact_keys(parts, _add)

        # Phase 2: fuzzy name matching
        self._phase2_fuzzy_names(parts, threshold, _add)

        # Build result pairs
        result: list[DuplicatePair] = []
        for (id_a, id_b), (score, reasons) in candidates.items():
            pa = parts_by_id.get(id_a)
            pb = parts_by_id.get(id_b)
            if pa and pb:
                result.append(DuplicatePair(part_a=pa, part_b=pb, score=score, match_reasons=reasons))

        result.sort(key=lambda p: -p.score)
        return result

    def _phase1_exact_keys(
        self,
        parts: list[Part],
        add: Callable[[int, int, float, str], None],
    ) -> None:
        # Group by normalized supplier_sku
        sku_groups: dict[str, list[int]] = {}
        for p in parts:
            norm_sku = normalize_text(p.supplier_sku)
            if norm_sku:
                sku_groups.setdefault(norm_sku, []).append(p.id)
        for ids in sku_groups.values():
            for a, b in itertools.combinations(ids, 2):
                add(a, b, 100.0, "exact_sku")

        # Group by (normalized mpn, normalized manufacturer)
        mpn_groups: dict[tuple[str, str], list[int]] = {}
        for p in parts:
            norm_mpn = normalize_text(p.mpn)
            norm_mfr = normalize_text(p.manufacturer)
            if norm_mpn and norm_mfr:
                mpn_groups.setdefault((norm_mpn, norm_mfr), []).append(p.id)
        for ids in mpn_groups.values():
            for a, b in itertools.combinations(ids, 2):
                add(a, b, 100.0, "exact_mpn")

    def _phase2_fuzzy_names(
        self,
        parts: list[Part],
        threshold: float,
        add: Callable[[int, int, float, str], None],
    ) -> None:
        names = [(p.id, p.normalized_name, p) for p in parts]
        n = len(names)
        for i in range(n):
            id_a, name_a, part_a = names[i]
            for j in range(i + 1, n):
                id_b, name_b, part_b = names[j]
                base_score = fuzz.WRatio(name_a, name_b)
                if base_score < threshold:
                    continue

                # Category gate
                if (
                    part_a.category
                    and part_b.category
                    and normalize_text(part_a.category) != normalize_text(part_b.category)
                ):
                    continue

                # Value gate: reject when both names contain value tokens
                # but share none (e.g. "100nF" vs "10nF").
                tokens_a = _extract_value_tokens(name_a)
                tokens_b = _extract_value_tokens(name_b)
                if tokens_a and tokens_b and not tokens_a & tokens_b:
                    continue

                # Enrich score
                enriched = base_score
                reasons = [f"name:{base_score:.0f}"]

                if (
                    part_a.supplier_sku
                    and part_b.supplier_sku
                    and normalize_text(part_a.supplier_sku) == normalize_text(part_b.supplier_sku)
                ):
                    enriched += 15
                    reasons.append("sku_match")
                if (
                    part_a.default_package
                    and part_b.default_package
                    and normalize_text(part_a.default_package) == normalize_text(part_b.default_package)
                ):
                    enriched += 10
                    reasons.append("package_match")
                if (
                    part_a.manufacturer
                    and part_b.manufacturer
                    and normalize_text(part_a.manufacturer) == normalize_text(part_b.manufacturer)
                ):
                    enriched += 5
                    reasons.append("manufacturer_match")

                add(id_a, id_b, enriched, ", ".join(reasons))

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge_parts(
        self,
        keep_id: int,
        remove_id: int,
        keep_slot_id: int | None = None,
    ) -> MergeResult:
        if keep_id == remove_id:
            raise ValueError("Cannot merge a part with itself")

        with self.db.transaction():
            keep = self.part_repo.get_part_by_id(keep_id)
            remove = self.part_repo.get_part_by_id(remove_id)
            if keep is None:
                raise ValueError(f"Part #{keep_id} not found")
            if remove is None:
                raise ValueError(f"Part #{remove_id} not found")

            # 1. Sum quantities
            qty_before = keep.qty
            new_qty = keep.qty + remove.qty

            # 2. Fill blank fields
            update_fields: dict = {"qty": new_qty}
            fields_adopted: list[str] = []
            for fname in _MERGE_ADOPTABLE_FIELDS:
                if getattr(keep, fname) is None and getattr(remove, fname) is not None:
                    update_fields[fname] = getattr(remove, fname)
                    fields_adopted.append(fname)

            # 3. Slot resolution
            discarded_slot_label: str | None = None
            has_slot_conflict = (
                keep.slot_id is not None
                and remove.slot_id is not None
                and keep.slot_id != remove.slot_id
            )
            if has_slot_conflict:
                if keep_slot_id is None:
                    raise ValueError(
                        "Slot conflict: caller must specify keep_slot_id"
                    )
                if keep_slot_id not in (keep.slot_id, remove.slot_id):
                    raise ValueError(
                        f"keep_slot_id must be one of {keep.slot_id} or {remove.slot_id}"
                    )
                discarded_id = (
                    remove.slot_id if keep_slot_id == keep.slot_id else keep.slot_id
                )
                # Find label for discarded slot
                discarded_part_id = (
                    remove_id if discarded_id == remove.slot_id else keep_id
                )
                discarded_slot_label = self.part_repo.get_part_location(discarded_part_id)
                update_fields["slot_id"] = keep_slot_id
            elif keep.slot_id is None and remove.slot_id is not None:
                update_fields["slot_id"] = remove.slot_id

            # 4. Merge notes
            notes_parts = []
            if keep.notes:
                notes_parts.append(keep.notes)
            if discarded_slot_label:
                notes_parts.append(
                    f"(Merged from {remove.name}, previously in {discarded_slot_label})"
                )
            if remove.notes and remove.notes != keep.notes:
                notes_parts.append(remove.notes)
            merged_notes = "\n---\n".join(notes_parts) if notes_parts else None
            if merged_notes != keep.notes:
                update_fields["notes"] = merged_notes

            # 5. Transfer aliases
            aliases_before = len(self.part_repo.list_aliases_for_part(keep_id))
            remove_aliases = self.part_repo.list_aliases_for_part(remove_id)
            for alias in remove_aliases:
                self.part_repo.add_alias(keep_id, alias.alias, alias.normalized_alias)
            # Add removed part's name as alias
            self.part_repo.add_alias(keep_id, remove.name, remove.normalized_name)
            aliases_after = len(self.part_repo.list_aliases_for_part(keep_id))
            aliases_transferred = aliases_after - aliases_before

            # 6. Remap bom_lines in place
            cursor = self.db.execute(
                "UPDATE bom_lines SET part_id = ? WHERE part_id = ?",
                (keep_id, remove_id),
            )
            bom_lines_remapped = cursor.rowcount

            # 7. Remap normalized_bom_items
            cursor = self.db.execute(
                "UPDATE normalized_bom_items SET part_id = ? WHERE part_id = ?",
                (keep_id, remove_id),
            )
            normalized_items_remapped = cursor.rowcount

            # 8. Recompute fingerprint
            # Resolve post-merge field values
            post_category = update_fields.get("category", keep.category)
            post_sku = update_fields.get("supplier_sku", keep.supplier_sku)
            post_package = update_fields.get("default_package", keep.default_package)
            new_fingerprint = make_part_fingerprint(
                category=post_category,
                name=keep.name,
                supplier_sku=post_sku,
                package=post_package,
            )
            if new_fingerprint != keep.fingerprint:
                collision = self.db.query_one(
                    "SELECT id FROM parts WHERE fingerprint = ? AND id != ?",
                    (new_fingerprint, keep_id),
                )
                if collision:
                    raise ValueError(
                        f"Merge would create fingerprint collision with part #{collision['id']}"
                    )
                self.db.execute(
                    "UPDATE parts SET fingerprint = ? WHERE id = ?",
                    (new_fingerprint, keep_id),
                )

            # 9. Apply field updates
            self.part_repo.update_part(keep_id, **update_fields)

            # 10. Delete removed part
            self.part_repo.delete_part(remove_id)

            # 11. Audit
            self.audit_repo.add_event(
                event_type="part.merged",
                entity_type="part",
                entity_id=keep_id,
                message=f"Merged part '{remove.name}' (#{remove_id}) into '{keep.name}' (#{keep_id})",
                payload={
                    "keep_id": keep_id,
                    "removed_id": remove_id,
                    "removed_name": remove.name,
                    "removed_fingerprint": remove.fingerprint,
                    "qty_before": qty_before,
                    "qty_after": new_qty,
                    "fields_adopted": fields_adopted,
                    "discarded_slot_label": discarded_slot_label,
                },
            )

            return MergeResult(
                kept_part_id=keep_id,
                removed_part_id=remove_id,
                qty_added=remove.qty,
                aliases_transferred=aliases_transferred,
                bom_lines_remapped=bom_lines_remapped,
                normalized_items_remapped=normalized_items_remapped,
                discarded_slot_label=discarded_slot_label,
            )
