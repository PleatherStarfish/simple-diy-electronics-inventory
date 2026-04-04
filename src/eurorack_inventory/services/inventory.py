from __future__ import annotations

import logging
import sqlite3

from eurorack_inventory.domain.enums import CellLength, CellSize, SlotType, StorageClass
from eurorack_inventory.domain.models import Part, PartAlias, PartDetail, PartLocation
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
        if "storage_class_override" in fields:
            self._unassign_if_incompatible(updated)
            refreshed = self.part_repo.get_part_by_id(part_id)
            if refreshed is not None:
                updated = refreshed
        return updated

    def _unassign_if_incompatible(self, part: Part) -> None:
        """Unassign any stored quantities that no longer fit their slots."""
        compat = classify_part_compat(part)
        for location in self.part_repo.list_part_locations(part.id):
            slot = self.storage_repo.get_slot(location.slot_id)
            if slot is None:
                continue
            slot_class = _slot_to_storage_class(slot)
            if slot_class is None or compat.penalty_for(slot_class) is not None:
                continue
            self.part_repo.move_part_location(part.id, location.slot_id, None)
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

    def list_part_locations(self, part_id: int) -> list[PartLocation]:
        return self.part_repo.list_part_locations(part_id)

    def get_part_detail(self, part_id: int) -> PartDetail:
        part = self.part_repo.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part {part_id}")
        aliases = self.part_repo.list_aliases_for_part(part_id)
        locations = self.part_repo.list_part_locations(part_id)
        location = self.part_repo.get_part_location(part_id)
        return PartDetail(part=part, aliases=aliases, location=location, locations=locations)

    def replace_part_locations(self, part_id: int, locations: list[tuple[int | None, int]]) -> Part:
        part = self.part_repo.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part {part_id}")
        self.part_repo.replace_part_locations(part_id, locations)
        updated = self.part_repo.get_part_by_id(part_id)
        assert updated is not None
        self.audit_repo.add_event(
            event_type="part.locations_updated",
            entity_type="part",
            entity_id=part_id,
            message=f"Updated locations for part {updated.name}",
            payload={"location_count": len(self.part_repo.list_part_locations(part_id))},
        )
        return updated

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

    def unassign_parts_from_slot(self, part_ids: list[int], source_slot_id: int) -> None:
        if not part_ids:
            return
        slot = self.storage_repo.get_slot(source_slot_id)
        slot_label = slot.label if slot else f"slot #{source_slot_id}"
        for part_id in part_ids:
            self.part_repo.move_part_location(part_id, source_slot_id, None)
            self.audit_repo.add_event(
                event_type="part.unassigned",
                entity_type="part",
                entity_id=part_id,
                message=f"Part quantity moved out of {slot_label}",
                payload={"source_slot_id": source_slot_id},
            )

    def reassign_part_slot(
        self,
        part_id: int,
        new_slot_id: int,
        source_slot_id: int | None = None,
    ) -> Part:
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
                for occ in other_occupants:
                    self.part_repo.move_part_location(occ.id, new_slot_id, None)
                    self.audit_repo.add_event(
                        event_type="part.bumped",
                        entity_type="part",
                        entity_id=occ.id,
                        message=f"Bumped part {occ.name} to Unassigned (displaced by move)",
                        payload={"from_slot_id": new_slot_id},
                    )

        locations = self.part_repo.list_part_locations(part_id)
        if source_slot_id is None:
            if len(locations) > 1:
                raise ValueError(
                    "Part has multiple locations. Move it from a specific slot or edit its locations."
                )
            if len(locations) == 1:
                source_slot_id = locations[0].slot_id

        if source_slot_id is None:
            part = self.part_repo.get_part_by_id(part_id)
            if part is None:
                raise ValueError(f"Unknown part {part_id}")
            self.part_repo.replace_part_locations(part_id, [(new_slot_id, part.qty)])
        else:
            self.part_repo.move_part_location(part_id, source_slot_id, new_slot_id)

        updated = self.part_repo.get_part_by_id(part_id)
        assert updated is not None
        container = self.storage_repo.get_container(slot.container_id) if slot else None
        loc = f"{container.name} / {slot.label}" if container and slot else f"slot #{new_slot_id}"
        self.audit_repo.add_event(
            event_type="part.moved",
            entity_type="part",
            entity_id=part_id,
            message=f"Moved part {updated.name} to {loc}",
            payload={"new_slot_id": new_slot_id, "source_slot_id": source_slot_id},
        )
        return updated

    def get_unassigned_slot_id(self) -> int | None:
        """Get the Unassigned/Main slot ID."""
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            return None
        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        return slot.id if slot else None

    def _get_unassigned_slot_id(self) -> int | None:
        return self.get_unassigned_slot_id()

    def counts(self) -> dict[str, int]:
        return {
            "parts": self.part_repo.count_parts(),
        }
