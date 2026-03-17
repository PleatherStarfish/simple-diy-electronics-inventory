from __future__ import annotations

import logging
import sqlite3

from eurorack_inventory.domain.models import Part, PartAlias, PartDetail
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.common import make_part_fingerprint, normalize_text

logger = logging.getLogger(__name__)


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
        return updated

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

        Any parts already occupying *new_slot_id* are bumped to the
        Unassigned / Main slot so they don't silently share a cell.
        """
        # Bump existing occupants to Unassigned
        occupants = self.part_repo.list_parts_by_slot_ids([new_slot_id]).get(new_slot_id, [])
        if occupants:
            unassigned_slot_id = self._get_unassigned_slot_id()
            for occ in occupants:
                if occ.id == part_id:
                    continue
                self.part_repo.update_part(occ.id, slot_id=unassigned_slot_id)
                self.audit_repo.add_event(
                    event_type="part.bumped",
                    entity_type="part",
                    entity_id=occ.id,
                    message=f"Bumped part {occ.name} to Unassigned (displaced by move)",
                    payload={"from_slot_id": new_slot_id, "to_slot_id": unassigned_slot_id},
                )

        updated = self.part_repo.update_part(part_id, slot_id=new_slot_id)
        slot = self.storage_repo.get_slot(new_slot_id)
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
