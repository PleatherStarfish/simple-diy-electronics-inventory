from __future__ import annotations

import logging
import sqlite3

from eurorack_inventory.domain.enums import CellLength, CellSize, SlotType, StorageClass
from eurorack_inventory.domain.models import Part, PartAlias, PartDetail
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.classifier import classify_part_compat
from eurorack_inventory.services.common import make_part_fingerprint, normalize_text

logger = logging.getLogger(__name__)


def _slot_to_storage_class(slot) -> StorageClass | None:
    """Map a storage slot to its StorageClass based on type and metadata."""
    if slot.slot_type == SlotType.CARD.value:
        return StorageClass.BINDER_CARD
    if slot.slot_type == SlotType.GRID_REGION.value:
        cell_size = slot.metadata.get("cell_size", CellSize.SMALL.value)
        cell_length = slot.metadata.get("cell_length", CellLength.SHORT.value)
        if cell_length == CellLength.LONG.value:
            return StorageClass.LONG_CELL
        if cell_size == CellSize.LARGE.value:
            return StorageClass.LARGE_CELL
        return StorageClass.SMALL_SHORT_CELL
    return None


class InventoryService:
    def __init__(
        self,
        part_repo: PartRepository,
        storage_repo: StorageRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self.audit_repo = audit_repo

    def upsert_part(
        self,
        *,
        name: str,
        category: str | None = None,
        supplier_sku: str | None = None,
        purchase_url: str | None = None,
        notes: str | None = None,
        package: str | None = None,
        qty: int = 0,
        slot_id: int | None = None,
    ) -> Part:
        part = Part(
            id=None,
            fingerprint=make_part_fingerprint(
                category=category,
                name=name,
                supplier_sku=supplier_sku,
                package=package,
            ),
            name=name,
            normalized_name=normalize_text(name),
            category=category,
            supplier_name="Tayda" if supplier_sku else None,
            supplier_sku=supplier_sku,
            purchase_url=purchase_url,
            default_package=package,
            notes=notes,
            qty=qty,
            slot_id=slot_id,
        )
        saved = self.part_repo.upsert_part(part)
        self.audit_repo.add_event(
            event_type="part.upserted",
            entity_type="part",
            entity_id=saved.id,
            message=f"Upserted part {saved.name}",
            payload={"category": saved.category, "supplier_sku": saved.supplier_sku},
        )
        return saved

    def update_part(self, part_id: int, **fields) -> Part:
        """Update a part by ID with the given fields."""
        updated = self.part_repo.update_part(part_id, **fields)
        self.audit_repo.add_event(
            event_type="part.updated",
            entity_type="part",
            entity_id=part_id,
            message=f"Updated part {updated.name}",
            payload={"fields": list(fields.keys())},
        )
        # If the part's storage class changed, check whether it still fits
        if "storage_class_override" in fields and updated.slot_id is not None:
            self._unassign_if_incompatible(updated)
        return updated

    def _unassign_if_incompatible(self, part: Part) -> None:
        """Unassign part from its slot if the slot's storage class is forbidden."""
        if part.slot_id is None:
            return
        slot = self.storage_repo.get_slot(part.slot_id)
        if slot is None:
            return
        slot_class = _slot_to_storage_class(slot)
        if slot_class is None:
            return
        compat = classify_part_compat(part)
        if compat.penalty_for(slot_class) is None:
            # Forbidden — move to unassigned
            self.part_repo.update_part(part.id, slot_id=None)
            part.slot_id = None
            self.audit_repo.add_event(
                event_type="part.auto_unassigned",
                entity_type="part",
                entity_id=part.id,
                message=f"Auto-unassigned {part.name}: no longer fits in {slot.label}",
                payload={"slot_id": slot.id, "slot_label": slot.label},
            )

    def delete_part(self, part_id: int) -> None:
        """Delete a part. Raises ValueError if part is used in a BOM."""
        part = self.part_repo.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part {part_id}")
        try:
            self.part_repo.delete_part(part_id)
        except sqlite3.IntegrityError:
            raise ValueError(
                f"Cannot delete '{part.name}' — it is referenced by a project BOM. "
                "Remove it from all BOMs first."
            )
        self.audit_repo.add_event(
            event_type="part.deleted",
            entity_type="part",
            entity_id=part_id,
            message=f"Deleted part {part.name}",
            payload={"category": part.category},
        )

    def add_alias(self, part_id: int, alias: str) -> PartAlias:
        normalized = normalize_text(alias)
        result = self.part_repo.add_alias(part_id, alias, normalized)
        self.audit_repo.add_event(
            event_type="part.alias_added",
            entity_type="part",
            entity_id=part_id,
            message=f"Added alias {alias}",
            payload={"alias": alias},
        )
        return result

    def adjust_qty(self, part_id: int, delta: int) -> int:
        """Adjust quantity for a part. Returns the new quantity."""
        if delta == 0:
            raise ValueError("delta must not be zero")
        new_qty = self.part_repo.adjust_qty(part_id, delta)
        self.audit_repo.add_event(
            event_type="part.qty_adjusted",
            entity_type="part",
            entity_id=part_id,
            message=f"Adjusted qty by {delta:+d}, now {new_qty}",
            payload={"delta": delta, "new_qty": new_qty},
        )
        return new_qty

    def update_part_notes(self, part_id: int, notes: str | None) -> None:
        part = self.part_repo.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part {part_id}")
        self.part_repo.update_part_notes(part_id, notes)
        self.audit_repo.add_event(
            event_type="part.notes_updated",
            entity_type="part",
            entity_id=part_id,
            message=f"Updated notes for part {part.name}",
            payload={"part_id": part_id},
        )

    def list_inventory(self, part_ids: list[int] | None = None):
        return self.part_repo.list_inventory_summaries(part_ids)

    def get_part_detail(self, part_id: int) -> PartDetail:
        part = self.part_repo.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part {part_id}")
        aliases = self.part_repo.list_aliases_for_part(part_id)
        location = self.part_repo.get_part_location(part_id)
        return PartDetail(part=part, aliases=aliases, location=location)

    def unassign_parts(self, part_ids: list[int]) -> None:
        """Clear slot assignment for the given parts, making them unassigned."""
        if not part_ids:
            return
        self.part_repo.bulk_clear_slot_ids(part_ids)
        for pid in part_ids:
            self.audit_repo.add_event(
                event_type="part.unassigned",
                entity_type="part",
                entity_id=pid,
                message="Part unassigned from storage slot",
                payload={},
            )

    def reassign_part_slot(self, part_id: int, new_slot_id: int) -> Part:
        """Move a part to a different storage slot.

        For grid cells (capacity 1): existing occupants are bumped to Unassigned.
        For binder cards (capacity = bag_count): the part is added if there's room,
        otherwise a ValueError is raised.
        """
        slot = self.storage_repo.get_slot(new_slot_id)
        if slot is None:
            raise ValueError(f"Unknown slot_id={new_slot_id}")

        occupants = self.part_repo.list_parts_by_slot_ids([new_slot_id]).get(new_slot_id, [])
        other_occupants = [o for o in occupants if o.id != part_id]

        if slot.slot_type == SlotType.CARD.value:
            # Binder card: check bag capacity — don't bump, just reject if full
            bag_count = slot.metadata.get("bag_count", 4)
            if len(other_occupants) >= bag_count:
                raise ValueError(
                    f"Card is full ({len(other_occupants)}/{bag_count} bags used)"
                )
        else:
            # Grid cell or other slot: bump existing occupants to Unassigned
            if other_occupants:
                unassigned_slot_id = self._get_unassigned_slot_id()
                for occ in other_occupants:
                    self.part_repo.update_part(occ.id, slot_id=unassigned_slot_id)
                    self.audit_repo.add_event(
                        event_type="part.bumped",
                        entity_type="part",
                        entity_id=occ.id,
                        message=f"Bumped part {occ.name} to Unassigned (displaced by move)",
                        payload={"from_slot_id": new_slot_id, "to_slot_id": unassigned_slot_id},
                    )

        updated = self.part_repo.update_part(part_id, slot_id=new_slot_id)
        container = self.storage_repo.get_container(slot.container_id) if slot else None
        loc = f"{container.name} / {slot.label}" if container and slot else f"slot #{new_slot_id}"
        self.audit_repo.add_event(
            event_type="part.moved",
            entity_type="part",
            entity_id=part_id,
            message=f"Moved part {updated.name} to {loc}",
            payload={"new_slot_id": new_slot_id},
        )
        return updated

    def _get_unassigned_slot_id(self) -> int | None:
        """Get the Unassigned/Main slot ID."""
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            return None
        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        return slot.id if slot else None

    def counts(self) -> dict[str, int]:
        return {
            "parts": self.part_repo.count_parts(),
        }
