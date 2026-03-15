from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from eurorack_inventory.domain.enums import (
    CellLength,
    CellSize,
    ContainerType,
    SlotType,
    StorageClass,
)
from eurorack_inventory.domain.models import Part, StorageSlot
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.classifier import classify_part
from eurorack_inventory.services.settings import ClassifierSettings, SettingsRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AssignmentScope:
    all_parts: bool = True
    part_ids: list[int] | None = None
    categories: list[str] | None = None


@dataclass(slots=True)
class StorageEstimate:
    small_short_cells_needed: int = 0
    large_cells_needed: int = 0
    long_cells_needed: int = 0
    binder_cards_needed: int = 0


@dataclass(slots=True)
class AssignmentResult:
    assigned_count: int = 0
    assignments: list[tuple[int, int]] = field(default_factory=list)
    unassigned_count: int = 0
    estimate: StorageEstimate = field(default_factory=StorageEstimate)


def _slot_to_storage_class(slot: StorageSlot) -> StorageClass | None:
    """Map a storage slot to its StorageClass based on type and metadata."""
    if slot.slot_type == SlotType.CARD.value:
        return StorageClass.BINDER_CARD

    if slot.slot_type == SlotType.GRID_REGION.value:
        cell_size = slot.metadata.get("cell_size", CellSize.SMALL.value)
        cell_length = slot.metadata.get("cell_length", CellLength.SHORT.value)

        if cell_size == CellSize.LARGE.value:
            return StorageClass.LARGE_CELL
        if cell_length == CellLength.LONG.value:
            return StorageClass.LONG_CELL
        return StorageClass.SMALL_SHORT_CELL

    return None


class AssignmentService:
    def __init__(
        self,
        part_repo: PartRepository,
        storage_repo: StorageRepository,
        audit_repo: AuditRepository,
        settings_repo: SettingsRepository | None = None,
    ) -> None:
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self.audit_repo = audit_repo
        self.settings_repo = settings_repo

    def assign(
        self,
        mode: str,
        scope: AssignmentScope,
    ) -> AssignmentResult:
        """Assign parts to storage slots.

        mode: "full_rebuild" clears existing assignments first.
              "incremental" only assigns currently unassigned parts.
        """
        unassigned_slot_id = self._get_unassigned_slot_id()

        # Load classifier settings
        cls_settings: ClassifierSettings | None = None
        if self.settings_repo is not None:
            cls_settings = self.settings_repo.get_classifier_settings()

        # 1. Gather parts
        parts = self._gather_parts(mode, scope, unassigned_slot_id)
        if not parts:
            return AssignmentResult()

        # 2. Classify parts
        classified: dict[StorageClass, list[Part]] = defaultdict(list)
        for part in parts:
            sc = classify_part(part, cls_settings)
            classified[sc].append(part)

        # 3. Sort within each class by category then name (for grouping)
        for sc in classified:
            classified[sc].sort(key=lambda p: (p.category or "", p.name or ""))

        # 4. Map available slots to StorageClass
        available = self._gather_available_slots(unassigned_slot_id)

        # 5. Pack parts into slots
        assignments: list[tuple[int, int]] = []
        unassigned_parts: list[Part] = []

        for sc in StorageClass:
            sc_parts = classified.get(sc, [])
            sc_slots = available.get(sc, [])
            assigned_here, leftover = self._pack(sc_parts, sc_slots)
            assignments.extend(assigned_here)
            unassigned_parts.extend(leftover)

        # 6. Bulk update
        if assignments:
            self.part_repo.bulk_update_slot_ids(assignments)

        # 7. Estimate additional storage needed
        estimate = self._estimate(unassigned_parts, cls_settings)

        # 8. Audit
        self.audit_repo.add_event(
            event_type="assignment.completed",
            entity_type="assignment",
            entity_id=0,
            message=(
                f"Assignment run ({mode}): {len(assignments)} assigned, "
                f"{len(unassigned_parts)} unassigned"
            ),
            payload={
                "mode": mode,
                "assigned_count": len(assignments),
                "unassigned_count": len(unassigned_parts),
                "estimate": {
                    "small_short_cells": estimate.small_short_cells_needed,
                    "large_cells": estimate.large_cells_needed,
                    "long_cells": estimate.long_cells_needed,
                    "binder_cards": estimate.binder_cards_needed,
                },
            },
        )

        return AssignmentResult(
            assigned_count=len(assignments),
            assignments=assignments,
            unassigned_count=len(unassigned_parts),
            estimate=estimate,
        )

    def _get_unassigned_slot_id(self) -> int | None:
        """Get the Unassigned/Main slot ID."""
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            return None
        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        return slot.id if slot else None

    def _gather_parts(
        self,
        mode: str,
        scope: AssignmentScope,
        unassigned_slot_id: int | None,
    ) -> list[Part]:
        """Get the list of parts to assign based on mode and scope."""
        all_parts = self.part_repo.list_parts()

        # Apply scope filter
        if not scope.all_parts:
            if scope.part_ids is not None:
                id_set = set(scope.part_ids)
                all_parts = [p for p in all_parts if p.id in id_set]
            elif scope.categories is not None:
                cat_set = {c.lower() for c in scope.categories}
                all_parts = [
                    p for p in all_parts
                    if (p.category or "").lower() in cat_set
                ]

        if mode == "full_rebuild":
            # Reset all matching parts to unassigned
            if unassigned_slot_id is not None:
                resets = [(p.id, unassigned_slot_id) for p in all_parts]
                if resets:
                    self.part_repo.bulk_update_slot_ids(resets)
            return all_parts

        # Incremental: only unassigned parts
        return [
            p for p in all_parts
            if p.slot_id is None or p.slot_id == unassigned_slot_id
        ]

    def _gather_available_slots(
        self,
        unassigned_slot_id: int | None,
    ) -> dict[StorageClass, list[StorageSlot]]:
        """Build a mapping of StorageClass to available (empty) slots."""
        occupied = self.part_repo.list_occupied_slot_ids()
        containers = self.storage_repo.list_containers()

        result: dict[StorageClass, list[StorageSlot]] = defaultdict(list)

        for container in containers:
            # Skip the Unassigned container
            if container.name == "Unassigned":
                continue

            slots = self.storage_repo.list_slots_for_container(container.id)
            for slot in slots:
                if slot.id in occupied:
                    continue
                sc = _slot_to_storage_class(slot)
                if sc is not None:
                    result[sc].append(slot)

        return result

    def _pack(
        self,
        parts: list[Part],
        slots: list[StorageSlot],
    ) -> tuple[list[tuple[int, int]], list[Part]]:
        """Assign parts to slots using category-affinity first-fit.

        Returns (assignments, unassigned_parts).
        """
        if not parts:
            return [], []
        if not slots:
            return [], list(parts)

        # Build container→slot index
        container_slots: dict[int, list[StorageSlot]] = defaultdict(list)
        for slot in slots:
            container_slots[slot.container_id].append(slot)

        # Track which categories are in which containers (from existing assignments)
        container_categories: dict[int, set[str]] = defaultdict(set)
        for container_id, cslots in container_slots.items():
            # We only have empty slots here, but we can check existing assignments
            # in this container via the DB. For simplicity, build affinity as we go.
            pass

        used_slot_ids: set[int] = set()
        assignments: list[tuple[int, int]] = []
        unassigned: list[Part] = []

        # Index: container_id → available slot iterator
        slot_iterators: dict[int, int] = {cid: 0 for cid in container_slots}

        def _take_slot_from_container(container_id: int) -> StorageSlot | None:
            cslots = container_slots[container_id]
            idx = slot_iterators[container_id]
            while idx < len(cslots):
                s = cslots[idx]
                idx += 1
                slot_iterators[container_id] = idx
                if s.id not in used_slot_ids:
                    used_slot_ids.add(s.id)
                    return s
            slot_iterators[container_id] = idx
            return None

        # Category → preferred container_id (affinity)
        category_affinity: dict[str, int] = {}

        for part in parts:
            cat = (part.category or "").lower()
            placed = False

            # Try affinity container first
            if cat in category_affinity:
                preferred_cid = category_affinity[cat]
                slot = _take_slot_from_container(preferred_cid)
                if slot is not None:
                    assignments.append((part.id, slot.id))
                    placed = True

            # Try any container with available slots
            if not placed:
                for cid in container_slots:
                    if cid in category_affinity.values() and cid != category_affinity.get(cat):
                        # Skip containers already affinity-mapped to other categories
                        # unless they still have room
                        pass
                    slot = _take_slot_from_container(cid)
                    if slot is not None:
                        assignments.append((part.id, slot.id))
                        category_affinity[cat] = cid
                        placed = True
                        break

            if not placed:
                unassigned.append(part)

        return assignments, unassigned

    def _estimate(
        self,
        unassigned_parts: list[Part],
        cls_settings: ClassifierSettings | None = None,
    ) -> StorageEstimate:
        """Estimate additional storage needed for unassigned parts."""
        counts: dict[StorageClass, int] = defaultdict(int)
        for part in unassigned_parts:
            sc = classify_part(part, cls_settings)
            counts[sc] += 1

        return StorageEstimate(
            small_short_cells_needed=counts.get(StorageClass.SMALL_SHORT_CELL, 0),
            large_cells_needed=counts.get(StorageClass.LARGE_CELL, 0),
            long_cells_needed=counts.get(StorageClass.LONG_CELL, 0),
            binder_cards_needed=counts.get(StorageClass.BINDER_CARD, 0),
        )
