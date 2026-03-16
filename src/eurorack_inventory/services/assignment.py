from __future__ import annotations

import json
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
from eurorack_inventory.domain.models import Part, StorageSlot, utc_now_iso
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.classifier import (
    PartCompatibility,
    classify_part,
    classify_part_compat,
)
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


@dataclass(frozen=True)
class AssignmentPlan:
    assignments: tuple[tuple[int, int], ...]  # (part_id, slot_id)
    unassigned_part_ids: tuple[int, ...]
    estimate: StorageEstimate
    unassigned_reasons: tuple[tuple[int, str], ...] = ()

    def reason_for(self, part_id: int) -> str:
        for pid, reason in self.unassigned_reasons:
            if pid == part_id:
                return reason
        return "unknown"


@dataclass(slots=True)
class AssignmentResult:
    assigned_count: int = 0
    assignments: list[tuple[int, int]] = field(default_factory=list)
    unassigned_count: int = 0
    estimate: StorageEstimate = field(default_factory=StorageEstimate)


@dataclass(slots=True)
class AvailableSlot:
    """A slot with its remaining capacity for the packer."""
    slot: StorageSlot
    remaining_capacity: int  # 1 for grid cells, bag_count - occupants for cards


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

    # ------------------------------------------------------------------
    # Pure planner — read-only, no side effects
    # ------------------------------------------------------------------

    def plan(
        self,
        mode: str,
        scope: AssignmentScope,
    ) -> AssignmentPlan:
        """Compute an assignment plan without modifying the database."""
        unassigned_slot_id = self._get_unassigned_slot_id()

        cls_settings: ClassifierSettings | None = None
        if self.settings_repo is not None:
            cls_settings = self.settings_repo.get_classifier_settings()

        # 1. Gather parts (read-only — no resets)
        parts = self._gather_parts_for_plan(mode, scope, unassigned_slot_id)
        if not parts:
            return AssignmentPlan(
                assignments=(),
                unassigned_part_ids=(),
                estimate=StorageEstimate(),
            )

        # 2. Map available slots (with capacity model)
        in_scope_slot_ids: set[int] = set()
        if mode == "full_rebuild":
            for part in parts:
                if part.slot_id is not None and part.slot_id != unassigned_slot_id:
                    in_scope_slot_ids.add(part.slot_id)
        available = self._gather_available_slots(unassigned_slot_id, in_scope_slot_ids)

        # 3. Build current slot map for churn awareness
        current_slot_map = {p.id: p.slot_id for p in parts}

        # 4. Pack with scarcity-first scored greedy
        assignments, unassigned_parts, reasons = self._pack(
            parts, available, cls_settings, current_slot_map, mode=mode,
        )

        # 5. Estimate for unassigned
        estimate = self._estimate(unassigned_parts, cls_settings)

        return AssignmentPlan(
            assignments=tuple(assignments),
            unassigned_part_ids=tuple(p.id for p in unassigned_parts),
            estimate=estimate,
            unassigned_reasons=tuple(reasons.items()),
        )

    # ------------------------------------------------------------------
    # Transactional application
    # ------------------------------------------------------------------

    def apply_plan(
        self,
        plan: AssignmentPlan,
        mode: str,
        scope: AssignmentScope,
    ) -> int:
        """Apply a plan transactionally. Returns the assignment run ID."""
        db = self.part_repo.db

        # Build snapshot of current slot_ids for all parts in the plan
        all_part_ids = [pid for pid, _ in plan.assignments] + list(plan.unassigned_part_ids)
        snapshot: list[list[int | None]] = []
        for pid in all_part_ids:
            p = self.part_repo.get_part_by_id(pid)
            if p is not None:
                snapshot.append([p.id, p.slot_id])

        unassigned_slot_id = self._get_unassigned_slot_id()

        # For full_rebuild: clear existing slot_ids first
        if mode == "full_rebuild":
            clear_ids = [pid for pid in all_part_ids if pid is not None]
            if clear_ids:
                self.part_repo.bulk_clear_slot_ids(clear_ids)

        # Apply assignments
        if plan.assignments:
            self.part_repo.bulk_update_slot_ids(list(plan.assignments))

        # Persist the run
        now = utc_now_iso()
        scope_dict = {
            "all_parts": scope.all_parts,
            "part_ids": scope.part_ids,
            "categories": scope.categories,
        }
        cursor = db.execute(
            """
            INSERT INTO assignment_runs
                (created_at, mode, scope_json, plan_json, snapshot_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                now,
                mode,
                json.dumps(scope_dict, ensure_ascii=False),
                json.dumps(
                    [[pid, sid] for pid, sid in plan.assignments],
                    ensure_ascii=False,
                ),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        run_id = int(cursor.lastrowid)
        db.conn.commit()

        # Audit (outside transaction — non-critical)
        self.audit_repo.add_event(
            event_type="assignment.completed",
            entity_type="assignment_run",
            entity_id=run_id,
            message=(
                f"Assignment run ({mode}): {len(plan.assignments)} assigned, "
                f"{len(plan.unassigned_part_ids)} unassigned"
            ),
            payload={
                "run_id": run_id,
                "mode": mode,
                "assigned_count": len(plan.assignments),
                "unassigned_count": len(plan.unassigned_part_ids),
                "estimate": {
                    "small_short_cells": plan.estimate.small_short_cells_needed,
                    "large_cells": plan.estimate.large_cells_needed,
                    "long_cells": plan.estimate.long_cells_needed,
                    "binder_cards": plan.estimate.binder_cards_needed,
                },
            },
        )

        return run_id

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def undo_run(self, run_id: int) -> tuple[int, list[str]]:
        """Undo an assignment run by restoring the snapshot.

        Returns (restored_count, conflict_warnings).
        Conflicts occur when a part's current slot_id differs from what the
        plan assigned (i.e. the user moved it manually since the run).
        """
        db = self.part_repo.db
        row = db.query_one(
            "SELECT * FROM assignment_runs WHERE id = ? AND undone_at IS NULL",
            (run_id,),
        )
        if row is None:
            return 0, []

        snapshot: list[list[int | None]] = json.loads(row["snapshot_json"])
        plan_assignments: list[list[int | None]] = json.loads(row["plan_json"])

        # Build plan map: part_id → slot_id that the plan assigned
        plan_map: dict[int, int] = {pid: sid for pid, sid in plan_assignments}

        restore_ops: list[tuple[int, int | None]] = []
        conflicts: list[str] = []

        for part_id, original_slot_id in snapshot:
            if part_id is None:
                continue
            current = self.part_repo.get_part_by_id(part_id)
            if current is None:
                continue

            planned_slot = plan_map.get(part_id)
            if planned_slot is not None and current.slot_id != planned_slot:
                conflicts.append(
                    f"Part '{current.name}' (id={part_id}): expected slot {planned_slot}, "
                    f"found slot {current.slot_id} (moved since assignment)"
                )
                continue

            restore_ops.append((part_id, original_slot_id))

        now = utc_now_iso()
        for part_id, original_slot_id in restore_ops:
            db.execute(
                "UPDATE parts SET slot_id = ?, updated_at = ? WHERE id = ?",
                (original_slot_id, now, part_id),
            )
        db.execute(
            "UPDATE assignment_runs SET undone_at = ? WHERE id = ?",
            (now, run_id),
        )
        db.conn.commit()

        self.audit_repo.add_event(
            event_type="assignment.undone",
            entity_type="assignment_run",
            entity_id=run_id,
            message=(
                f"Assignment run {run_id} undone: {len(restore_ops)} restored, "
                f"{len(conflicts)} conflicts"
            ),
        )

        return len(restore_ops), conflicts

    def get_latest_run(self) -> dict | None:
        """Return the latest non-undone assignment run, or None."""
        row = self.part_repo.db.query_one(
            "SELECT * FROM assignment_runs WHERE undone_at IS NULL "
            "ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Convenience: plan + apply in one call (backwards compatible)
    # ------------------------------------------------------------------

    def assign(
        self,
        mode: str,
        scope: AssignmentScope,
    ) -> AssignmentResult:
        """Assign parts to storage slots (plan + apply)."""
        assignment_plan = self.plan(mode, scope)

        if not assignment_plan.assignments and not assignment_plan.unassigned_part_ids:
            return AssignmentResult()

        self.apply_plan(assignment_plan, mode, scope)

        return AssignmentResult(
            assigned_count=len(assignment_plan.assignments),
            assignments=list(assignment_plan.assignments),
            unassigned_count=len(assignment_plan.unassigned_part_ids),
            estimate=assignment_plan.estimate,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_unassigned_slot_id(self) -> int | None:
        """Get the Unassigned/Main slot ID."""
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            return None
        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        return slot.id if slot else None

    def _gather_parts_for_plan(
        self,
        mode: str,
        scope: AssignmentScope,
        unassigned_slot_id: int | None,
    ) -> list[Part]:
        """Get the list of parts for planning (read-only, no DB writes)."""
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
            else:
                # all_parts=False but no filter specified → no parts
                all_parts = []

        if mode == "full_rebuild":
            # Return all matching parts — actual reset happens in apply_plan()
            return all_parts

        # Incremental: only unassigned parts, plus skip locked parts
        # (override + already placed → user explicitly classified and placed them)
        return [
            p for p in all_parts
            if (p.slot_id is None or p.slot_id == unassigned_slot_id)
            and not (
                p.storage_class_override
                and p.slot_id is not None
                and p.slot_id != unassigned_slot_id
            )
        ]

    def _gather_available_slots(
        self,
        unassigned_slot_id: int | None,
        reusable_slot_ids: set[int] | None = None,
    ) -> dict[StorageClass, list[AvailableSlot]]:
        """Build a mapping of StorageClass to available slots with capacity.

        For grid slots, capacity is 1 (one part family per cell).
        For binder cards, capacity is bag_count minus current occupants.

        For scoped full_rebuild, *reusable_slot_ids* contains slot IDs currently
        occupied by in-scope parts.  These slots are treated as available because
        apply_plan() will clear them before reassignment.
        """
        occupancy = self.part_repo.count_parts_per_slot()
        if reusable_slot_ids:
            for sid in reusable_slot_ids:
                occupancy.pop(sid, None)

        containers = self.storage_repo.list_containers()
        result: dict[StorageClass, list[AvailableSlot]] = defaultdict(list)

        for container in containers:
            if container.name == "Unassigned":
                continue

            slots = self.storage_repo.list_slots_for_container(container.id)
            for slot in slots:
                sc = _slot_to_storage_class(slot)
                if sc is None:
                    continue

                current_count = occupancy.get(slot.id, 0)

                if slot.slot_type == SlotType.CARD.value:
                    bag_count = slot.metadata.get("bag_count", 4)
                    remaining = bag_count - current_count
                else:
                    remaining = 1 - current_count

                if remaining > 0:
                    result[sc].append(AvailableSlot(
                        slot=slot, remaining_capacity=remaining,
                    ))

        return result

    def _score_assignment(
        self,
        part: Part,
        compat: PartCompatibility,
        avail: AvailableSlot,
        slot_class: StorageClass,
        category_container_counts: dict[str, dict[int, int]],
        current_slot_id: int | None,
        *,
        mode: str = "incremental",
    ) -> float:
        """Score a candidate (part, slot) pair. Lower is better."""
        # 1. Fit quality (most important)
        fit_penalty = compat.penalty_for(slot_class)
        if fit_penalty is None:
            return float("inf")
        score = fit_penalty * 10.0

        # 2. Churn: prefer keeping parts where they already are
        #    Skipped in full_rebuild — favour optimal placement from scratch.
        if mode != "full_rebuild":
            if current_slot_id is not None and current_slot_id != avail.slot.id:
                score += 2.0

        # 3. Category mixing: prefer container with the most same-category parts
        cat = (part.category or "").lower()
        if cat and cat in category_container_counts:
            counts = category_container_counts[cat]
            best_container = max(counts, key=counts.get)  # type: ignore[arg-type]
            if avail.slot.container_id != best_container:
                score += 1.5

        # 4. Fragmentation: prefer partially-full binder cards (pack tightly)
        if avail.slot.slot_type == SlotType.CARD.value:
            total_bags = avail.slot.metadata.get("bag_count", 4)
            fullness = (total_bags - avail.remaining_capacity) / total_bags
            score -= fullness * 0.5

        # 5. Positional stability: slight preference for earlier ordinal
        score += (avail.slot.ordinal or 0) * 0.001

        return score

    # Deterministic ordering for storage classes when scarcity is tied
    _CLASS_ORDER: dict[StorageClass, int] = {
        StorageClass.BINDER_CARD: 0,
        StorageClass.LARGE_CELL: 1,
        StorageClass.LONG_CELL: 2,
        StorageClass.SMALL_SHORT_CELL: 3,
    }

    def _pack(
        self,
        parts: list[Part],
        available: dict[StorageClass, list[AvailableSlot]],
        cls_settings: ClassifierSettings | None = None,
        current_slot_map: dict[int, int | None] | None = None,
        *,
        mode: str = "incremental",
    ) -> tuple[list[tuple[int, int]], list[Part], dict[int, str]]:
        """Scarcity-first scored greedy packer.

        Returns (assignments, unassigned_parts, unassigned_reasons).
        """
        if not parts:
            return [], [], {}

        # 1. Classify all parts
        part_compats = [(p, classify_part_compat(p, cls_settings)) for p in parts]

        # 2. Count compatible capacity per part
        def _compat_capacity(compat: PartCompatibility) -> int:
            return sum(
                s.remaining_capacity
                for sc in compat.compatible_classes()
                for s in available.get(sc, [])
            )

        # 3. Sort by scarcity (fewest compatible slots first),
        #    then by preferred class (groups same-type parts), then by part ID
        #    for deterministic results.
        part_compats.sort(key=lambda pc: (
            _compat_capacity(pc[1]),
            self._CLASS_ORDER.get(pc[1].preferred, 99),
            pc[0].id,
        ))

        # Track which StorageClasses have any slots at all (before packing)
        classes_with_slots: set[StorageClass] = {
            sc for sc, slots in available.items() if slots
        }

        # 4. Greedy assignment with cost function
        assignments: list[tuple[int, int]] = []
        unassigned: list[Part] = []
        unassigned_reasons: dict[int, str] = {}
        category_container_counts: dict[str, dict[int, int]] = defaultdict(
            lambda: defaultdict(int),
        )
        current_slots = current_slot_map or {}

        for part, compat in part_compats:
            best_slot: AvailableSlot | None = None
            best_score = float("inf")

            for sc in compat.compatible_classes():
                for avail in available.get(sc, []):
                    if avail.remaining_capacity <= 0:
                        continue
                    score = self._score_assignment(
                        part, compat, avail, sc,
                        category_container_counts, current_slots.get(part.id),
                        mode=mode,
                    )
                    if score < best_score:
                        best_score = score
                        best_slot = avail

            if best_slot is not None:
                assignments.append((part.id, best_slot.slot.id))
                best_slot.remaining_capacity -= 1
                cat = (part.category or "").lower()
                if cat:
                    category_container_counts[cat][best_slot.slot.container_id] += 1
            else:
                unassigned.append(part)
                has_compat_type = any(
                    sc in classes_with_slots for sc in compat.compatible_classes()
                )
                if has_compat_type:
                    unassigned_reasons[part.id] = "all compatible slots are full"
                else:
                    unassigned_reasons[part.id] = "no compatible slot type exists"

        return assignments, unassigned, unassigned_reasons

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
