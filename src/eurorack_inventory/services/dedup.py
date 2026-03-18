from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import PartSignature, ReviewPriority
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.dedup_feedback import DedupFeedbackRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.common import make_part_fingerprint, normalize_text
from eurorack_inventory.services.dedup_blocking import generate_candidates
from eurorack_inventory.services.dedup_conflicts import check_conflicts
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.services.signature_parser import SignatureParser

logger = logging.getLogger(__name__)


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

_MERGE_OVERRIDABLE_FIELDS = {
    "name",
    "category",
    "manufacturer",
    "mpn",
    "supplier_name",
    "supplier_sku",
    "purchase_url",
    "default_package",
    "notes",
    "storage_class_override",
}


@dataclass(slots=True)
class DuplicatePair:
    part_a: Part
    part_b: Part
    score: float
    match_reasons: list[str] = field(default_factory=list)
    hard_rejects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    priority: str = ReviewPriority.LOW
    sig_a: PartSignature | None = None
    sig_b: PartSignature | None = None


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
        feedback_repo: DedupFeedbackRepository | None = None,
    ) -> None:
        self.db = db
        self.part_repo = part_repo
        self.audit_repo = audit_repo
        self.search_service = search_service
        self.feedback_repo = feedback_repo
        self._parser = SignatureParser()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def find_duplicate_pairs(self, threshold: float = 75.0) -> list[DuplicatePair]:
        """Find duplicate pairs using typed signature pipeline.

        The threshold parameter is kept for API compatibility but is no longer
        the primary matching mechanism. Typed blocking rules now drive candidate
        generation. The threshold is used only for within-bucket fuzzy fallback.
        """
        parts = self.part_repo.list_parts()
        parts_by_id = {p.id: p for p in parts if p.id is not None}

        # Step 1: Parse all signatures in memory
        signatures: dict[int, PartSignature] = {}
        for p in parts:
            if p.id is not None:
                signatures[p.id] = self._parser.parse(p)

        # Step 2: Load suppressed pairs from feedback
        suppressed: set[tuple[int, int]] = set()
        if self.feedback_repo:
            suppressed = self.feedback_repo.list_suppressed_pairs()

        # Step 3: Generate candidates via typed blocking
        raw_candidates = generate_candidates(parts, signatures, suppressed)

        # Step 4: Filter through conflicts + score
        result: list[DuplicatePair] = []
        for id_a, id_b, block_reasons in raw_candidates:
            pa = parts_by_id.get(id_a)
            pb = parts_by_id.get(id_b)
            if not pa or not pb:
                continue

            sig_a = signatures.get(id_a)
            sig_b = signatures.get(id_b)
            if sig_a is None or sig_b is None:
                continue

            # Check hard rejects and warnings
            hard_rejects, warnings = check_conflicts(pa, pb, sig_a, sig_b)

            # Skip pairs with hard rejects
            if hard_rejects:
                continue

            # Score the pair
            priority, score, reasons = score_pair(
                pa, pb, sig_a, sig_b, block_reasons,
            )

            result.append(DuplicatePair(
                part_a=pa,
                part_b=pb,
                score=score,
                match_reasons=reasons,
                hard_rejects=hard_rejects,
                warnings=warnings,
                priority=priority,
                sig_a=sig_a,
                sig_b=sig_b,
            ))

        # Sort by priority tier then score
        priority_order = {ReviewPriority.HIGH: 0, ReviewPriority.MEDIUM: 1, ReviewPriority.LOW: 2}
        result.sort(key=lambda p: (priority_order.get(p.priority, 3), -p.score))
        return result

    def get_signature(self, part: Part) -> PartSignature:
        """Parse and return the signature for a single part."""
        return self._parser.parse(part)

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge_parts(
        self,
        keep_id: int,
        remove_id: int,
        keep_slot_id: int | None = None,
        *,
        score: float = 0.0,
        reasons: list[str] | None = None,
        sig_a: PartSignature | None = None,
        sig_b: PartSignature | None = None,
        overrides: dict[str, str | None] | None = None,
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

            # Record merge feedback
            if self.feedback_repo:
                self.feedback_repo.record_merge(
                    keep_id, remove_id, score, reasons or [],
                    sig_a, sig_b, keep.name, remove.name,
                )

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

            # 2b. Apply caller overrides (custom name, category, etc.)
            overrides_applied: list[str] = []
            if overrides:
                for fname, fval in overrides.items():
                    if fname not in _MERGE_OVERRIDABLE_FIELDS:
                        continue
                    current = update_fields.get(fname, getattr(keep, fname, None))
                    if fval != current:
                        update_fields[fname] = fval
                        overrides_applied.append(fname)
                # Name change requires updating normalized_name too
                if "name" in overrides and "name" in overrides_applied:
                    update_fields["normalized_name"] = normalize_text(overrides["name"] or "")

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
            post_name = update_fields.get("name", keep.name)
            post_category = update_fields.get("category", keep.category)
            post_sku = update_fields.get("supplier_sku", keep.supplier_sku)
            post_package = update_fields.get("default_package", keep.default_package)
            new_fingerprint = make_part_fingerprint(
                category=post_category,
                name=post_name,
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
                    "fields_overridden": overrides_applied,
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


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

def score_pair(
    part_a: Part,
    part_b: Part,
    sig_a: PartSignature,
    sig_b: PartSignature,
    block_reasons: list[str],
) -> tuple[str, float, list[str]]:
    """Score a candidate pair and assign review priority.

    Returns (priority, score, reasons).
    """
    score = 0.0
    reasons: list[str] = []
    warnings_count = 0

    # Feature weights
    if "exact_sku" in block_reasons:
        score += 50
        reasons.append("exact_sku")

    if "exact_mpn" in block_reasons:
        score += 50
        reasons.append("exact_mpn")

    if "same_base_device" in block_reasons:
        if sig_a.package and sig_b.package and sig_a.package == sig_b.package:
            score += 40
            reasons.append("same_base_device_same_package")
        else:
            score += 30
            reasons.append("same_base_device")

    # Typed value match (resistor, capacitor, pot)
    typed_value_match = False
    if sig_a.value_ohms is not None and sig_b.value_ohms is not None:
        if abs(sig_a.value_ohms - sig_b.value_ohms) / max(sig_a.value_ohms, sig_b.value_ohms) <= 0.01:
            score += 30
            reasons.append("typed_value_match")
            typed_value_match = True
    elif sig_a.value_pf is not None and sig_b.value_pf is not None:
        if abs(sig_a.value_pf - sig_b.value_pf) / max(sig_a.value_pf, sig_b.value_pf) <= 0.01:
            score += 30
            reasons.append("typed_value_match")
            typed_value_match = True

    # Name fuzzy score (scaled 0-20)
    name_ratio = fuzz.token_sort_ratio(
        part_a.normalized_name, part_b.normalized_name,
    )
    name_score = name_ratio * 0.2  # scale 0-100 -> 0-20
    score += name_score
    if name_ratio >= 70:
        reasons.append(f"name_similarity:{name_ratio:.0f}")

    # Package match
    if (
        sig_a.package and sig_b.package
        and sig_a.package == sig_b.package
    ):
        score += 10
        reasons.append("package_match")

    # Manufacturer match
    if part_a.manufacturer and part_b.manufacturer:
        if normalize_text(part_a.manufacturer) == normalize_text(part_b.manufacturer):
            score += 5
            reasons.append("manufacturer_match")

    # Category match
    if part_a.category and part_b.category:
        if normalize_text(part_a.category) == normalize_text(part_b.category):
            score += 5
            reasons.append("category_match")

    # Alias name match
    # (Could check part aliases here for +15, but keeping simple for Phase 1)

    # ── Assign priority ───────────────────────────────────────────────────
    has_exact = "exact_sku" in block_reasons or "exact_mpn" in block_reasons
    has_typed_identity = typed_value_match or "same_base_device" in block_reasons
    has_multi_field_match = sum(1 for r in reasons if r not in ("category_match",)) >= 3

    if has_exact:
        priority = ReviewPriority.HIGH
    elif has_typed_identity and has_multi_field_match:
        priority = ReviewPriority.HIGH
    elif has_typed_identity:
        priority = ReviewPriority.MEDIUM
    elif "fuzzy_name" in block_reasons:
        priority = ReviewPriority.LOW
    else:
        priority = ReviewPriority.MEDIUM

    return priority, score, reasons
