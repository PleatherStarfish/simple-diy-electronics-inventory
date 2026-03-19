from __future__ import annotations

import logging
from dataclasses import asdict

from eurorack_inventory.domain.enums import CellLength, CellSize, ContainerType, SlotType, StorageClass
from eurorack_inventory.domain.models import StorageContainer, StorageSlot
from eurorack_inventory.domain.storage import (
    GridRegion,
    grid_region_to_label,
    index_to_row_label,
    parse_grid_region,
    region_within_bounds,
    regions_overlap,
)
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(
        self,
        storage_repo: StorageRepository,
        audit_repo: AuditRepository,
        part_repo: PartRepository | None = None,
    ) -> None:
        self.storage_repo = storage_repo
        self.audit_repo = audit_repo
        self.part_repo = part_repo

    def ensure_default_unassigned_slot(self) -> StorageSlot:
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            container = self.storage_repo.create_container(
                StorageContainer(
                    id=None,
                    name="Unassigned",
                    container_type=ContainerType.BIN.value,
                    metadata={},
                    notes="Fallback container for imported or unplaced stock",
                    sort_order=0,
                )
            )
            self.audit_repo.add_event(
                event_type="container.created",
                entity_type="container",
                entity_id=container.id,
                message="Created default Unassigned container",
                payload={"container_type": container.container_type},
            )

        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        if slot is None:
            slot = self.storage_repo.create_slot(
                StorageSlot(
                    id=None,
                    container_id=container.id,
                    label="Main",
                    slot_type=SlotType.BULK.value,
                    ordinal=1,
                    notes="Default fallback slot",
                )
            )
            self.audit_repo.add_event(
                event_type="slot.created",
                entity_type="slot",
                entity_id=slot.id,
                message="Created default Unassigned/Main slot",
                payload={"container_id": container.id},
            )
        return slot

    def create_container(
        self,
        *,
        name: str,
        container_type: str,
        metadata: dict | None = None,
        notes: str | None = None,
        sort_order: int = 0,
    ) -> StorageContainer:
        container = self.storage_repo.create_container(
            StorageContainer(
                id=None,
                name=name,
                container_type=container_type,
                metadata=metadata or {},
                notes=notes,
                sort_order=sort_order,
            )
        )
        self.audit_repo.add_event(
            event_type="container.created",
            entity_type="container",
            entity_id=container.id,
            message=f"Created container {name}",
            payload={"container_type": container_type, "metadata": container.metadata},
        )
        return container

    def rename_container(self, container_id: int, new_name: str) -> StorageContainer:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Container name cannot be empty")
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.name == new_name:
            return container
        existing = self.storage_repo.get_container_by_name(new_name)
        if existing is not None:
            raise ValueError(f"A container named {new_name!r} already exists")
        old_name = container.name
        container.name = new_name
        updated = self.storage_repo.update_container(container)
        self.audit_repo.add_event(
            event_type="container.renamed",
            entity_type="container",
            entity_id=container_id,
            message=f"Renamed container {old_name!r} to {new_name!r}",
            payload={"old_name": old_name, "new_name": new_name},
        )
        return updated

    def update_container_notes(self, container_id: int, notes: str) -> StorageContainer:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        container.notes = notes or None
        updated = self.storage_repo.update_container(container)
        self.audit_repo.add_event(
            event_type="container.notes_updated",
            entity_type="container",
            entity_id=container_id,
            message=f"Updated notes for container {container.name!r}",
            payload={"notes": notes},
        )
        return updated

    def list_containers(self) -> list[StorageContainer]:
        return self.storage_repo.list_containers()

    def list_slots(self, container_id: int) -> list[StorageSlot]:
        return self.storage_repo.list_slots_for_container(container_id)

    def create_grid_slot(
        self,
        *,
        container_id: int,
        label: str,
        notes: str | None = None,
    ) -> StorageSlot:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.container_type != ContainerType.GRID_BOX.value:
            raise ValueError("Grid slots can only be created in grid_box containers")

        region = parse_grid_region(label)
        rows = int(container.metadata.get("rows", 0))
        cols = int(container.metadata.get("cols", 0))
        if rows <= 0 or cols <= 0:
            raise ValueError("Grid container metadata must define positive rows and cols")
        if not region_within_bounds(region, rows, cols):
            raise ValueError(f"Grid region {label!r} is outside container bounds")

        self._validate_grid_slot_overlap(container_id, region)
        slot = self.storage_repo.create_slot(
            StorageSlot(
                id=None,
                container_id=container_id,
                label=grid_region_to_label(region),
                slot_type=SlotType.GRID_REGION.value,
                x1=region.col_start,
                y1=region.row_start,
                x2=region.col_end,
                y2=region.row_end,
                notes=notes,
            )
        )
        self.audit_repo.add_event(
            event_type="slot.created",
            entity_type="slot",
            entity_id=slot.id,
            message=f"Created grid slot {slot.label}",
            payload={"container_id": container_id},
        )
        return slot

    def create_binder_card_slot(
        self,
        *,
        container_id: int,
        card_number: int,
        notes: str | None = None,
    ) -> StorageSlot:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.container_type != ContainerType.BINDER.value:
            raise ValueError("Binder card slots can only be created in binder containers")
        label = f"Card {card_number}"
        existing = self.storage_repo.get_slot_by_label(container_id, label)
        if existing is not None:
            return existing
        slot = self.storage_repo.create_slot(
            StorageSlot(
                id=None,
                container_id=container_id,
                label=label,
                slot_type=SlotType.CARD.value,
                ordinal=card_number,
                notes=notes,
            )
        )
        self.audit_repo.add_event(
            event_type="slot.created",
            entity_type="slot",
            entity_id=slot.id,
            message=f"Created binder card slot {label}",
            payload={"container_id": container_id},
        )
        return slot

    def get_or_create_slot(self, *, container_id: int, label: str) -> StorageSlot:
        existing = self.storage_repo.get_slot_by_label(container_id, label)
        if existing is not None:
            return existing
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")

        if container.container_type == ContainerType.GRID_BOX.value:
            return self.create_grid_slot(container_id=container_id, label=label)
        if container.container_type == ContainerType.BINDER.value and label.lower().startswith("card "):
            try:
                number = int(label.split()[1])
            except (IndexError, ValueError) as exc:
                raise ValueError(f"Invalid binder label: {label!r}") from exc
            return self.create_binder_card_slot(container_id=container_id, card_number=number)

        slot = self.storage_repo.create_slot(
            StorageSlot(
                id=None,
                container_id=container_id,
                label=label,
                slot_type=SlotType.SLOT.value,
                notes=None,
            )
        )
        self.audit_repo.add_event(
            event_type="slot.created",
            entity_type="slot",
            entity_id=slot.id,
            message=f"Created generic slot {label}",
            payload={"container_id": container_id},
        )
        return slot

    def _validate_grid_slot_overlap(self, container_id: int, region: GridRegion) -> None:
        for slot in self.storage_repo.list_slots_for_container(container_id):
            if slot.slot_type != SlotType.GRID_REGION.value:
                continue
            if None in (slot.x1, slot.y1, slot.x2, slot.y2):
                continue
            existing = GridRegion(
                row_start=slot.y1,
                col_start=slot.x1,
                row_end=slot.y2,
                col_end=slot.x2,
            )
            if regions_overlap(region, existing):
                raise ValueError(
                    f"Grid region {grid_region_to_label(region)!r} overlaps existing slot {slot.label!r}"
                )

    def _create_single_cell_grid_slot(
        self,
        *,
        container_id: int,
        row: int,
        col: int,
    ) -> StorageSlot:
        label = f"{index_to_row_label(row)}{col}"
        return self.storage_repo.create_slot(
            StorageSlot(
                id=None,
                container_id=container_id,
                label=label,
                slot_type=SlotType.GRID_REGION.value,
                x1=col,
                y1=row,
                x2=col,
                y2=row,
                metadata={
                    "cell_size": CellSize.SMALL.value,
                    "cell_length": CellLength.SHORT.value,
                },
            )
        )

    def configure_grid_box(
        self,
        *,
        name: str,
        rows: int,
        cols: int,
        notes: str | None = None,
        initial_cells: int | None = None,
    ) -> StorageContainer:
        total_cells = rows * cols
        if initial_cells is None:
            initial_cells = total_cells
        if initial_cells < 0 or initial_cells > total_cells:
            raise ValueError(
                f"initial_cells must be between 0 and {total_cells}, got {initial_cells}"
            )

        container = self.create_container(
            name=name,
            container_type=ContainerType.GRID_BOX.value,
            metadata={"rows": rows, "cols": cols},
            notes=notes,
        )
        for index in range(initial_cells):
            row, col = divmod(index, cols)
            self._create_single_cell_grid_slot(
                container_id=container.id,
                row=row,
                col=col,
            )
        logger.info(
            "Configured grid box %r with %d seeded cells out of %d",
            name,
            initial_cells,
            total_cells,
        )
        return container

    def configure_binder(
        self,
        *,
        name: str,
        num_cards: int,
        bags_per_card: int = 4,
        notes: str | None = None,
    ) -> StorageContainer:
        container = self.create_container(
            name=name,
            container_type=ContainerType.BINDER.value,
            metadata={"bags_per_card": bags_per_card},
            notes=notes,
        )
        for i in range(1, num_cards + 1):
            self.storage_repo.create_slot(
                StorageSlot(
                    id=None,
                    container_id=container.id,
                    label=f"Card {i}",
                    slot_type=SlotType.CARD.value,
                    ordinal=i,
                    metadata={"bag_count": bags_per_card},
                )
            )
        logger.info("Configured binder %r with %d cards", name, num_cards)
        return container

    def merge_cells(
        self,
        *,
        container_id: int,
        labels: list[str],
    ) -> StorageSlot:
        if len(labels) < 2:
            raise ValueError("Need at least two cells to merge")

        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.container_type != ContainerType.GRID_BOX.value:
            raise ValueError("Can only merge cells in grid_box containers")

        slots = []
        for label in labels:
            slot = self.storage_repo.get_slot_by_label(container_id, label)
            if slot is None:
                raise ValueError(f"Slot {label!r} not found in container")
            slots.append(slot)

        # Check none have stock assigned
        slot_ids = [s.id for s in slots]
        if self._slots_have_stock(slot_ids):
            raise ValueError("Cannot merge cells that have parts assigned to them")

        # Compute bounding rectangle from all slot coordinates
        all_rows = []
        all_cols = []
        for s in slots:
            if None in (s.x1, s.y1, s.x2, s.y2):
                raise ValueError(f"Slot {s.label!r} has no grid coordinates")
            all_rows.extend([s.y1, s.y2])
            all_cols.extend([s.x1, s.x2])

        merged_region = GridRegion(
            row_start=min(all_rows),
            col_start=min(all_cols),
            row_end=max(all_rows),
            col_end=max(all_cols),
        )

        # Validate that the selected cells exactly fill the bounding rectangle
        expected_cells = set()
        for r in range(merged_region.row_start, merged_region.row_end + 1):
            for c in range(merged_region.col_start, merged_region.col_end + 1):
                expected_cells.add((r, c))

        actual_cells = set()
        for s in slots:
            for r in range(s.y1, s.y2 + 1):
                for c in range(s.x1, s.x2 + 1):
                    actual_cells.add((r, c))

        if actual_cells != expected_cells:
            raise ValueError("Selected cells do not form a contiguous rectangle")

        # Delete individual slots
        for s in slots:
            self.storage_repo.delete_slot(s.id)

        # Create merged slot
        merged_label = grid_region_to_label(merged_region)
        merged_slot = self.storage_repo.create_slot(
            StorageSlot(
                id=None,
                container_id=container_id,
                label=merged_label,
                slot_type=SlotType.GRID_REGION.value,
                x1=merged_region.col_start,
                y1=merged_region.row_start,
                x2=merged_region.col_end,
                y2=merged_region.row_end,
                metadata={
                    "cell_size": CellSize.LARGE.value,
                    "cell_length": CellLength.LONG.value,
                },
            )
        )
        self.audit_repo.add_event(
            event_type="slot.merged",
            entity_type="slot",
            entity_id=merged_slot.id,
            message=f"Merged {len(labels)} cells into {merged_label}",
            payload={"container_id": container_id, "source_labels": labels},
        )
        return merged_slot

    def unmerge_cell(
        self,
        *,
        container_id: int,
        slot_id: int,
    ) -> list[StorageSlot]:
        slot = self.storage_repo.get_slot(slot_id)
        if slot is None:
            raise ValueError(f"Unknown slot_id={slot_id}")
        if slot.container_id != container_id:
            raise ValueError("Slot does not belong to the specified container")
        if None in (slot.x1, slot.y1, slot.x2, slot.y2):
            raise ValueError("Slot has no grid coordinates")
        if slot.x1 == slot.x2 and slot.y1 == slot.y2:
            raise ValueError("Slot is already a single cell")

        if self._slots_have_stock([slot_id]):
            raise ValueError("Cannot unmerge a cell that has parts assigned to it")

        old_label = slot.label
        self.storage_repo.delete_slot(slot_id)

        new_slots = []
        for row in range(slot.y1, slot.y2 + 1):
            for col in range(slot.x1, slot.x2 + 1):
                label = f"{index_to_row_label(row)}{col}"
                new_slot = self.storage_repo.create_slot(
                    StorageSlot(
                        id=None,
                        container_id=container_id,
                        label=label,
                        slot_type=SlotType.GRID_REGION.value,
                        x1=col,
                        y1=row,
                        x2=col,
                        y2=row,
                        metadata={
                            "cell_size": CellSize.SMALL.value,
                            "cell_length": CellLength.SHORT.value,
                        },
                    )
                )
                new_slots.append(new_slot)

        self.audit_repo.add_event(
            event_type="slot.unmerged",
            entity_type="slot",
            entity_id=slot_id,
            message=f"Unmerged {old_label} into {len(new_slots)} cells",
            payload={"container_id": container_id},
        )
        return new_slots

    def update_cell_properties(
        self,
        *,
        slot_id: int,
        cell_size: str | None = None,
        cell_length: str | None = None,
    ) -> StorageSlot:
        slot = self.storage_repo.get_slot(slot_id)
        if slot is None:
            raise ValueError(f"Unknown slot_id={slot_id}")

        metadata = dict(slot.metadata)
        if cell_size is not None:
            if cell_size not in (CellSize.SMALL.value, CellSize.LARGE.value):
                raise ValueError(f"Invalid cell_size: {cell_size!r}")
            metadata["cell_size"] = cell_size
        if cell_length is not None:
            if cell_length not in (CellLength.SHORT.value, CellLength.LONG.value):
                raise ValueError(f"Invalid cell_length: {cell_length!r}")
            metadata["cell_length"] = cell_length

        slot.metadata = metadata
        updated = self.storage_repo.update_slot(slot)
        self.audit_repo.add_event(
            event_type="slot.properties_updated",
            entity_type="slot",
            entity_id=slot_id,
            message=f"Updated cell properties for {slot.label}",
            payload={"cell_size": cell_size, "cell_length": cell_length},
        )
        self._unassign_incompatible_parts(updated)
        return updated

    def _unassign_incompatible_parts(self, slot: StorageSlot) -> None:
        """Unassign any parts that no longer fit after a cell property change."""
        if self.part_repo is None:
            return
        from eurorack_inventory.services.classifier import classify_part_compat

        slot_class = self._slot_storage_class(slot)
        if slot_class is None:
            return
        parts_map = self.part_repo.list_parts_by_slot_ids([slot.id])
        for part in parts_map.get(slot.id, []):
            compat = classify_part_compat(part)
            if compat.penalty_for(slot_class) is None:
                self.part_repo.update_part(part.id, slot_id=None)
                self.audit_repo.add_event(
                    event_type="part.auto_unassigned",
                    entity_type="part",
                    entity_id=part.id,
                    message=f"Auto-unassigned {part.name}: no longer fits in {slot.label}",
                    payload={"slot_id": slot.id, "slot_label": slot.label},
                )

    @staticmethod
    def _slot_storage_class(slot: StorageSlot) -> StorageClass | None:
        """Map a storage slot to its StorageClass."""
        if slot.slot_type == SlotType.CARD.value:
            return StorageClass.BINDER_CARD
        if slot.slot_type == SlotType.GRID_REGION.value:
            cs = slot.metadata.get("cell_size", CellSize.SMALL.value)
            cl = slot.metadata.get("cell_length", CellLength.SHORT.value)
            if cl == CellLength.LONG.value:
                return StorageClass.LONG_CELL
            if cs == CellSize.LARGE.value:
                return StorageClass.LARGE_CELL
            return StorageClass.SMALL_SHORT_CELL
        return None

    def resize_grid_box(
        self,
        *,
        container_id: int,
        new_rows: int,
        new_cols: int,
    ) -> StorageContainer:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.container_type != ContainerType.GRID_BOX.value:
            raise ValueError("Can only resize grid_box containers")
        if new_rows < 1 or new_cols < 1:
            raise ValueError("Rows and cols must be at least 1")

        old_rows = int(container.metadata.get("rows", 0))
        old_cols = int(container.metadata.get("cols", 0))

        # Find slots to remove (outside the new bounds)
        slots_to_remove: list[StorageSlot] = []
        if new_rows < old_rows or new_cols < old_cols:
            for slot in self.storage_repo.list_slots_for_container(container_id):
                if None in (slot.x1, slot.y1, slot.x2, slot.y2):
                    continue
                if slot.y2 >= new_rows or slot.x2 >= new_cols:
                    slots_to_remove.append(slot)

            # Block if any merged cell straddles the new boundary
            for slot in slots_to_remove:
                if (slot.y1 < new_rows and slot.x1 < new_cols):
                    raise ValueError(
                        f"Cannot shrink: merged cell {slot.label!r} spans across "
                        f"the new boundary. Unmerge it first."
                    )

            # Validate no stock in removed slots
            remove_ids = [s.id for s in slots_to_remove]
            if self._slots_have_stock(remove_ids):
                raise ValueError(
                    "Cannot shrink: some cells being removed have parts assigned"
                )

            for slot in slots_to_remove:
                self.storage_repo.delete_slot(slot.id)

        # Add new cells for expanded area — check coordinate coverage, not labels,
        # because merged slots (e.g. "A0-A1") cover multiple coordinates.
        occupied_coords: set[tuple[int, int]] = set()
        for slot in self.storage_repo.list_slots_for_container(container_id):
            if None in (slot.x1, slot.y1, slot.x2, slot.y2):
                continue
            for r in range(slot.y1, slot.y2 + 1):
                for c in range(slot.x1, slot.x2 + 1):
                    occupied_coords.add((r, c))

        for row in range(new_rows):
            for col in range(new_cols):
                if row < old_rows and col < old_cols:
                    continue
                if (row, col) in occupied_coords:
                    continue
                self._create_single_cell_grid_slot(
                    container_id=container_id,
                    row=row,
                    col=col,
                )

        # Update container metadata
        container.metadata = dict(container.metadata, rows=new_rows, cols=new_cols)
        updated = self.storage_repo.update_container(container)

        self.audit_repo.add_event(
            event_type="container.resized",
            entity_type="container",
            entity_id=container_id,
            message=f"Resized grid box from {old_rows}x{old_cols} to {new_rows}x{new_cols}",
            payload={"old_rows": old_rows, "old_cols": old_cols,
                     "new_rows": new_rows, "new_cols": new_cols},
        )
        return updated

    def resize_binder(
        self,
        *,
        container_id: int,
        new_num_cards: int,
    ) -> StorageContainer:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")
        if container.container_type != ContainerType.BINDER.value:
            raise ValueError("Can only resize binder containers")
        if new_num_cards < 1:
            raise ValueError("Number of cards must be at least 1")

        existing_slots = self.storage_repo.list_slots_for_container(container_id)
        card_slots = [s for s in existing_slots if s.slot_type == SlotType.CARD.value]
        old_num_cards = len(card_slots)
        bags_per_card = int(container.metadata.get("bags_per_card", 4))

        if new_num_cards < old_num_cards:
            # Remove cards from the end; block if any have stock
            slots_to_remove = [s for s in card_slots if s.ordinal > new_num_cards]
            remove_ids = [s.id for s in slots_to_remove]
            if self._slots_have_stock(remove_ids):
                raise ValueError(
                    "Cannot shrink: some cards being removed have parts assigned"
                )
            for s in slots_to_remove:
                self.storage_repo.delete_slot(s.id)
        elif new_num_cards > old_num_cards:
            for i in range(old_num_cards + 1, new_num_cards + 1):
                label = f"Card {i}"
                if self.storage_repo.get_slot_by_label(container_id, label) is not None:
                    continue
                self.storage_repo.create_slot(
                    StorageSlot(
                        id=None,
                        container_id=container_id,
                        label=label,
                        slot_type=SlotType.CARD.value,
                        ordinal=i,
                        metadata={"bag_count": bags_per_card},
                    )
                )

        self.audit_repo.add_event(
            event_type="container.resized",
            entity_type="container",
            entity_id=container_id,
            message=f"Resized binder from {old_num_cards} to {new_num_cards} cards",
            payload={"old_num_cards": old_num_cards, "new_num_cards": new_num_cards},
        )
        return container

    def update_card_bag_count(
        self,
        *,
        slot_id: int,
        bag_count: int,
    ) -> StorageSlot:
        if bag_count < 1:
            raise ValueError("Bag count must be at least 1")
        slot = self.storage_repo.get_slot(slot_id)
        if slot is None:
            raise ValueError(f"Unknown slot_id={slot_id}")
        if slot.slot_type != SlotType.CARD.value:
            raise ValueError("Can only update bag count on card slots")

        metadata = dict(slot.metadata)
        old_bag_count = metadata.get("bag_count", 4)
        metadata["bag_count"] = bag_count
        slot.metadata = metadata
        updated = self.storage_repo.update_slot(slot)
        self.audit_repo.add_event(
            event_type="slot.properties_updated",
            entity_type="slot",
            entity_id=slot_id,
            message=f"Updated bag count for {slot.label} to {bag_count}",
            payload={"old_bag_count": old_bag_count, "bag_count": bag_count},
        )
        # If bag count was reduced, unassign overflow parts
        if bag_count < old_bag_count:
            self._unassign_overflow_parts(updated)
        return updated

    def _unassign_overflow_parts(self, slot: StorageSlot) -> None:
        """Unassign excess parts when a card's bag count is reduced below occupancy."""
        if self.part_repo is None:
            return
        bag_count = slot.metadata.get("bag_count", 4)
        parts_map = self.part_repo.list_parts_by_slot_ids([slot.id])
        parts = parts_map.get(slot.id, [])
        if len(parts) <= bag_count:
            return
        # Unassign the last parts (by id) to bring count down to bag_count
        parts_sorted = sorted(parts, key=lambda p: p.id)
        overflow = parts_sorted[bag_count:]
        for part in overflow:
            self.part_repo.update_part(part.id, slot_id=None)
            self.audit_repo.add_event(
                event_type="part.auto_unassigned",
                entity_type="part",
                entity_id=part.id,
                message=f"Auto-unassigned {part.name}: card {slot.label} bag count reduced",
                payload={"slot_id": slot.id, "slot_label": slot.label},
            )

    def delete_container(self, container_id: int) -> None:
        container = self.storage_repo.get_container(container_id)
        if container is None:
            raise ValueError(f"Unknown container_id={container_id}")

        slots = self.storage_repo.list_slots_for_container(container_id)
        slot_ids = [s.id for s in slots]

        # Unassign any parts currently in this container's slots
        unassigned_count = 0
        if self.part_repo is not None and slot_ids:
            parts_by_slot = self.part_repo.list_parts_by_slot_ids(slot_ids)
            all_part_ids = [p.id for parts in parts_by_slot.values() for p in parts]
            if all_part_ids:
                self.part_repo.bulk_clear_slot_ids(all_part_ids)
                unassigned_count = len(all_part_ids)

        for slot in slots:
            self.storage_repo.delete_slot(slot.id)
        self.storage_repo.delete_container(container_id)

        self.audit_repo.add_event(
            event_type="container.deleted",
            entity_type="container",
            entity_id=container_id,
            message=f"Deleted container {container.name!r}",
            payload={
                "container_type": container.container_type,
                "slots_removed": len(slots),
                "parts_unassigned": unassigned_count,
            },
        )

    def clone_container(self, container_id: int, new_name: str) -> StorageContainer:
        """Clone a container (empty) with all its slot structure and metadata."""
        source = self.storage_repo.get_container(container_id)
        if source is None:
            raise ValueError(f"Unknown container_id={container_id}")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Container name cannot be empty")
        if self.storage_repo.get_container_by_name(new_name) is not None:
            raise ValueError(f"A container named {new_name!r} already exists")

        clone = self.storage_repo.create_container(
            StorageContainer(
                id=None,
                name=new_name,
                container_type=source.container_type,
                metadata=dict(source.metadata),
                notes=source.notes,
                sort_order=source.sort_order,
            )
        )

        for slot in self.storage_repo.list_slots_for_container(container_id):
            self.storage_repo.create_slot(
                StorageSlot(
                    id=None,
                    container_id=clone.id,
                    label=slot.label,
                    slot_type=slot.slot_type,
                    ordinal=slot.ordinal,
                    x1=slot.x1,
                    y1=slot.y1,
                    x2=slot.x2,
                    y2=slot.y2,
                    metadata=dict(slot.metadata),
                    notes=slot.notes,
                )
            )

        self.audit_repo.add_event(
            event_type="container.cloned",
            entity_type="container",
            entity_id=clone.id,
            message=f"Cloned container {source.name!r} as {new_name!r}",
            payload={"source_container_id": container_id},
        )
        return clone

    def suggest_clone_name(self, container_id: int) -> str:
        """Suggest a name for a cloned container, e.g. 'Box 1 (1)'."""
        source = self.storage_repo.get_container(container_id)
        if source is None:
            return ""
        base = source.name
        n = 1
        while True:
            candidate = f"{base} ({n})"
            if self.storage_repo.get_container_by_name(candidate) is None:
                return candidate
            n += 1

    def _slots_have_stock(self, slot_ids: list[int]) -> bool:
        if not slot_ids:
            return False
        placeholders = ",".join("?" * len(slot_ids))
        count = self.storage_repo.db.scalar(
            f"SELECT COUNT(*) FROM parts WHERE slot_id IN ({placeholders}) AND qty > 0",
            tuple(slot_ids),
        )
        return int(count or 0) > 0

    def bootstrap_demo_storage(self) -> list[StorageContainer]:
        containers: list[StorageContainer] = []
        if self.storage_repo.get_container_by_name("Cell Box 1") is None:
            containers.append(
                self.create_container(
                    name="Cell Box 1",
                    container_type=ContainerType.GRID_BOX.value,
                    metadata={"rows": 6, "cols": 6, "row_label_mode": "excel", "col_start": 0},
                    notes="Example 6x6 cell box",
                    sort_order=10,
                )
            )
        if self.storage_repo.get_container_by_name("Binder A") is None:
            containers.append(
                self.create_container(
                    name="Binder A",
                    container_type=ContainerType.BINDER.value,
                    metadata={"card_prefix": "Card"},
                    notes="Example binder storage",
                    sort_order=20,
                )
            )
        self.ensure_default_unassigned_slot()
        return containers
