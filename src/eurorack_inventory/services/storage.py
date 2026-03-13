from __future__ import annotations

import logging
from dataclasses import asdict

from eurorack_inventory.domain.enums import ContainerType, SlotType
from eurorack_inventory.domain.models import StorageContainer, StorageSlot
from eurorack_inventory.domain.storage import (
    GridRegion,
    grid_region_to_label,
    parse_grid_region,
    region_within_bounds,
    regions_overlap,
)
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.storage import StorageRepository

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, storage_repo: StorageRepository, audit_repo: AuditRepository) -> None:
        self.storage_repo = storage_repo
        self.audit_repo = audit_repo

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
