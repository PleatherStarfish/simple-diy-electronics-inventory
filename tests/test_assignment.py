from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.enums import CellLength, CellSize, StorageClass
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.assignment import AssignmentPlan, AssignmentScope, AssignmentService, StorageEstimate
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.settings import SettingsRepository
from eurorack_inventory.services.storage import StorageService


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def ctx(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    part_repo = PartRepository(db)
    storage_svc = StorageService(storage_repo, audit_repo)
    inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
    settings_repo = SettingsRepository(db)
    assignment_svc = AssignmentService(part_repo, storage_repo, audit_repo, settings_repo)
    storage_svc.ensure_default_unassigned_slot()
    yield assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, db
    db.close()


def _create_parts(inventory_svc, parts_data):
    """Create parts and return them. parts_data is list of (name, category, package, qty) tuples."""
    created = []
    for name, category, package, qty in parts_data:
        p = inventory_svc.upsert_part(
            name=name, category=category, package=package, qty=qty,
        )
        created.append(p)
    return created


class TestIncrementalAssignment:
    def test_assigns_unassigned_smt_parts_to_small_cells(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        # Create a grid box with small cells (default)
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        # SMT resistors → small cells
        parts = _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
            ("220R 0805", "Resistors", "loose", 10),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())

        assert result.assigned_count == 2
        assert result.unassigned_count == 0

        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            assert updated.slot_id is not None

    def test_assigns_package_only_0805_parts_to_small_cells(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=1, cols=2)

        parts = _create_parts(inventory_svc, [
            ("100R", "Resistors", "SMD 0805", 10),
            ("220R", "Resistors", "0805", 10),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())

        assert result.assigned_count == 2
        assert result.unassigned_count == 0

        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            assert updated.slot_id is not None

    def test_assigns_through_hole_resistors_to_long_cells(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)
        # Make two cells long
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_length="long")
        storage_svc.update_cell_properties(slot_id=slots[1].id, cell_length="long")

        # Through-hole resistors (no SMT size code) → long cells
        parts = _create_parts(inventory_svc, [
            ("10K 1/4W", "Resistors", "cut_tape", 50),
            ("100R 1/4W", "Resistors", "cut_tape", 50),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 2

        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            slot = storage_repo.get_slot(updated.slot_id)
            assert slot.metadata.get("cell_length") == "long"

    def test_does_not_reassign_already_placed_parts(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        # Manually assign a part to a specific slot
        p1 = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )
        # Create an unassigned part
        p2 = inventory_svc.upsert_part(name="220R 0805", category="Resistors", qty=10)

        result = assignment_svc.assign("incremental", AssignmentScope())

        # Only p2 should be assigned
        assert result.assigned_count == 1

        # p1 should keep its original slot
        p1_updated = part_repo.get_part_by_id(p1.id)
        assert p1_updated.slot_id == slots[0].id

    def test_no_parts_to_assign(self, ctx):
        assignment_svc, storage_svc, _, _, _, _ = ctx
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 0

    def test_assigns_wide_grid_boxes_in_coordinate_order(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Wide Box", rows=2, cols=15)
        _create_parts(inventory_svc, [
            (f"R{i} 0805", "Resistors", "loose", 10)
            for i in range(5)
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())

        assert result.assigned_count == 5

        assigned_labels = []
        for part_id, slot_id in result.assignments:
            part = part_repo.get_part_by_id(part_id)
            assert part is not None
            slot = storage_repo.get_slot(slot_id)
            assert slot is not None
            assert slot.container_id == container.id
            assigned_labels.append(slot.label)

        assert assigned_labels == ["A0", "A1", "A2", "A3", "A4"]


class TestFullRebuildAssignment:
    def test_clears_and_reassigns_all(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=3)
        slots = storage_repo.list_slots_for_container(container.id)

        # Assign SMT parts to specific slots
        p1 = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )
        p2 = inventory_svc.upsert_part(
            name="220R 0805", category="Resistors", qty=10, slot_id=slots[1].id,
        )

        result = assignment_svc.assign("full_rebuild", AssignmentScope())

        assert result.assigned_count == 2
        assert result.unassigned_count == 0

        p1_updated = part_repo.get_part_by_id(p1.id)
        p2_updated = part_repo.get_part_by_id(p2.id)
        assert p1_updated.slot_id is not None
        assert p2_updated.slot_id is not None


class TestScopeFiltering:
    def test_filter_by_part_ids(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        p1 = inventory_svc.upsert_part(name="100R 0805", category="Resistors", qty=10)
        p2 = inventory_svc.upsert_part(name="220R 0805", category="Resistors", qty=10)

        scope = AssignmentScope(all_parts=False, part_ids=[p1.id])
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 1

        p1_updated = part_repo.get_part_by_id(p1.id)
        p2_updated = part_repo.get_part_by_id(p2.id)
        assert p1_updated.slot_id is not None
        unassigned_slot = assignment_svc._get_unassigned_slot_id()
        assert p2_updated.slot_id is None or p2_updated.slot_id == unassigned_slot

    def test_filter_by_category(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)
        # Make one cell large for the switch, keep one small for resistor
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        p1 = inventory_svc.upsert_part(name="100nF", category="Capacitors", qty=10)
        p2 = inventory_svc.upsert_part(name="Toggle", category="Switches", qty=5)

        scope = AssignmentScope(all_parts=False, categories=["Capacitors"])
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 1
        p1_updated = part_repo.get_part_by_id(p1.id)
        assert p1_updated.slot_id is not None


    def test_filter_by_category_excludes_others(self, ctx):
        """Category scope must NOT assign parts from other categories."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        p1 = inventory_svc.upsert_part(name="100nF 0805", category="Capacitors", qty=10)
        p2 = inventory_svc.upsert_part(name="220R 0805", category="Resistors", qty=10)

        scope = AssignmentScope(all_parts=False, categories=["Capacitors"])
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 1
        assert result.unassigned_count == 0

        p1_updated = part_repo.get_part_by_id(p1.id)
        p2_updated = part_repo.get_part_by_id(p2.id)
        assert p1_updated.slot_id is not None
        # p2 must remain unassigned — it's Resistors, not Capacitors
        unassigned_slot = assignment_svc._get_unassigned_slot_id()
        assert p2_updated.slot_id is None or p2_updated.slot_id == unassigned_slot

    def test_filter_by_multiple_part_ids(self, ctx):
        """Selecting specific part IDs assigns only those parts."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=3, cols=3)

        p1 = inventory_svc.upsert_part(name="100R 0805", category="Resistors", qty=10)
        p2 = inventory_svc.upsert_part(name="220R 0805", category="Resistors", qty=10)
        p3 = inventory_svc.upsert_part(name="330R 0805", category="Resistors", qty=10)

        scope = AssignmentScope(all_parts=False, part_ids=[p1.id, p3.id])
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 2

        p1_u = part_repo.get_part_by_id(p1.id)
        p2_u = part_repo.get_part_by_id(p2.id)
        p3_u = part_repo.get_part_by_id(p3.id)
        assert p1_u.slot_id is not None
        assert p3_u.slot_id is not None
        # p2 was NOT in the scope — must remain unassigned
        unassigned_slot = assignment_svc._get_unassigned_slot_id()
        assert p2_u.slot_id is None or p2_u.slot_id == unassigned_slot

    def test_empty_scope_assigns_nothing(self, ctx):
        """all_parts=False with no filter → no parts assigned."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        inventory_svc.upsert_part(name="100R 0805", category="Resistors", qty=10)

        scope = AssignmentScope(all_parts=False)
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 0
        assert result.unassigned_count == 0

    def test_empty_category_list_assigns_nothing(self, ctx):
        """categories=[] → no parts assigned."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        inventory_svc.upsert_part(name="100R 0805", category="Resistors", qty=10)

        scope = AssignmentScope(all_parts=False, categories=[])
        result = assignment_svc.assign("incremental", scope)

        assert result.assigned_count == 0
        assert result.unassigned_count == 0


class TestCategoryAffinity:
    def test_same_category_groups_in_same_container(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        # Create two boxes with long cells for through-hole resistors
        for name in ("Box 1", "Box 2"):
            container = storage_svc.configure_grid_box(name=name, rows=2, cols=2)
            slots = storage_repo.list_slots_for_container(container.id)
            for s in slots:
                storage_svc.update_cell_properties(slot_id=s.id, cell_length="long")

        # Create 3 through-hole resistors — they should all end up in the same box
        parts = _create_parts(inventory_svc, [
            ("100R 1/4W", "Resistors", "cut_tape", 10),
            ("220R 1/4W", "Resistors", "cut_tape", 10),
            ("330R 1/4W", "Resistors", "cut_tape", 10),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 3

        container_ids = set()
        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            slot = storage_repo.get_slot(updated.slot_id)
            container_ids.add(slot.container_id)
        assert len(container_ids) == 1


class TestSlotTypeMatching:
    def test_large_parts_go_to_large_cells(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        # Make first cell large
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        # Create a switch (large part) and a capacitor (small part)
        p_switch = inventory_svc.upsert_part(name="Toggle", category="Switches", qty=5)
        p_cap = inventory_svc.upsert_part(name="100nF 0805", category="Capacitors", qty=10)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 2

        # Switch should be in the large cell
        switch_updated = part_repo.get_part_by_id(p_switch.id)
        assert switch_updated.slot_id == slots[0].id

    def test_binder_parts_go_to_cards(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_binder(name="Binder 1", num_cards=5)

        p_ic = inventory_svc.upsert_part(name="TL072 SOIC-8", category="ICs", qty=3)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        ic_updated = part_repo.get_part_by_id(p_ic.id)
        assert ic_updated.slot_id is not None

    def test_through_hole_resistors_cannot_go_in_small_cells(self, ctx):
        """Through-hole resistors (long parts) cannot fit in small cells."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        # Box with only small/short cells
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        _create_parts(inventory_svc, [
            ("10K 1/4W", "Resistors", "cut_tape", 50),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 1

    def test_through_hole_diodes_go_to_long_cells(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_length="long")

        p = inventory_svc.upsert_part(name="1N4148", category="Diodes", qty=20)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id == slots[0].id


class TestOverflowAndEstimate:
    def test_overflow_produces_correct_estimate(self, ctx):
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        # Create a box with only 1 small cell
        storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)

        # Create 3 SMT capacitors — only 1 can fit
        _create_parts(inventory_svc, [
            ("100nF 0805", "Capacitors", "loose", 10),
            ("10nF 0805", "Capacitors", "loose", 10),
            ("1uF 0805", "Capacitors", "loose", 10),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1
        assert result.unassigned_count == 2
        assert result.estimate.small_short_cells_needed == 2

    def test_no_slots_all_unassigned(self, ctx):
        assignment_svc, _, inventory_svc, _, _, _ = ctx

        _create_parts(inventory_svc, [
            ("10K 1/4W", "Resistors", "cut_tape", 10),
            ("Toggle", "Switches", None, 5),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 2
        assert result.estimate.long_cells_needed == 1
        assert result.estimate.large_cells_needed == 1


class TestEdgeCases:
    def test_no_parts(self, ctx):
        assignment_svc, storage_svc, _, _, _, _ = ctx
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 0

    def test_all_already_assigned_incremental(self, ctx):
        assignment_svc, storage_svc, inventory_svc, _, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10, slot_id=slots[0].id,
        )

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0

    def test_mixed_storage_types(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        # Box with small cells for SMT passives
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        # Binder for ICs
        storage_svc.configure_binder(name="Binder 1", num_cards=3)

        _create_parts(inventory_svc, [
            ("100nF 0805", "Capacitors", "loose", 10),
            ("TL072 SOIC-8", "ICs", None, 3),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 2
        assert result.unassigned_count == 0


class TestPlan:
    def test_plan_returns_assignments_without_db_changes(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        parts = _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
            ("220R 0805", "Resistors", "loose", 10),
        ])

        plan = assignment_svc.plan("incremental", AssignmentScope())

        # Plan should have assignments
        assert len(plan.assignments) == 2
        assert len(plan.unassigned_part_ids) == 0

        # DB should be unchanged
        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            assert updated.slot_id is None or updated.slot_id == assignment_svc._get_unassigned_slot_id()

    def test_plan_full_rebuild_does_not_reset_db(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        p = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )

        plan = assignment_svc.plan("full_rebuild", AssignmentScope())
        assert len(plan.assignments) == 1

        # Part should still be in its original slot
        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id == slots[0].id

    def test_plan_is_frozen(self, ctx):
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx
        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        _create_parts(inventory_svc, [("100R 0805", "Resistors", "loose", 10)])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        assert isinstance(plan, AssignmentPlan)
        # Frozen dataclass — should not allow mutation
        with pytest.raises(AttributeError):
            plan.assignments = ()


class TestApplyPlan:
    def test_apply_creates_run_record(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, db = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
        ])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        run_id = assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        assert run_id > 0

        # Verify run record exists
        run = assignment_svc.get_latest_run()
        assert run is not None
        assert run["id"] == run_id
        assert run["mode"] == "incremental"
        assert run["undone_at"] is None

    def test_apply_commits_assignments(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        parts = _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
        ])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        updated = part_repo.get_part_by_id(parts[0].id)
        assert updated.slot_id is not None
        assert updated.slot_id != assignment_svc._get_unassigned_slot_id()

    def test_apply_full_rebuild_clears_then_assigns(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=3)
        slots = storage_repo.list_slots_for_container(container.id)

        p1 = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )
        original_slot = p1.slot_id

        plan = assignment_svc.plan("full_rebuild", AssignmentScope())
        assignment_svc.apply_plan(plan, "full_rebuild", AssignmentScope())

        updated = part_repo.get_part_by_id(p1.id)
        assert updated.slot_id is not None


class TestUndo:
    def test_undo_restores_original_slots(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        parts = _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
            ("220R 0805", "Resistors", "loose", 10),
        ])

        # Parts start unassigned
        unassigned_slot = assignment_svc._get_unassigned_slot_id()
        for p in parts:
            orig = part_repo.get_part_by_id(p.id)
            assert orig.slot_id is None or orig.slot_id == unassigned_slot

        # Assign
        plan = assignment_svc.plan("incremental", AssignmentScope())
        run_id = assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        # Verify assigned
        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            assert updated.slot_id is not None

        # Undo
        restored, conflicts = assignment_svc.undo_run(run_id)
        assert restored == 2
        assert conflicts == []

        # Verify restored to original (None or unassigned)
        for p in parts:
            final = part_repo.get_part_by_id(p.id)
            assert final.slot_id is None or final.slot_id == unassigned_slot

    def test_undo_detects_conflict(self, ctx):
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        parts = _create_parts(inventory_svc, [
            ("100R 0805", "Resistors", "loose", 10),
        ])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        run_id = assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        # Manually move the part to a different slot
        assigned_slot = part_repo.get_part_by_id(parts[0].id).slot_id
        other_slot = [s for s in slots if s.id != assigned_slot][0]
        part_repo.update_part(parts[0].id, slot_id=other_slot.id)

        # Undo should detect the conflict
        restored, conflicts = assignment_svc.undo_run(run_id)
        assert restored == 0
        assert len(conflicts) == 1
        assert "moved since assignment" in conflicts[0]

    def test_undo_marks_run_as_undone(self, ctx):
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        _create_parts(inventory_svc, [("100R 0805", "Resistors", "loose", 10)])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        run_id = assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        assignment_svc.undo_run(run_id)

        # get_latest_run should not return the undone run
        latest = assignment_svc.get_latest_run()
        assert latest is None

    def test_undo_nonexistent_run(self, ctx):
        assignment_svc, _, _, _, _, _ = ctx
        restored, conflicts = assignment_svc.undo_run(9999)
        assert restored == 0
        assert conflicts == []

class TestScopedFullRebuild:
    """Regression tests: scoped full_rebuild must treat in-scope occupied slots as reusable."""

    def test_category_scoped_rebuild_reuses_in_scope_slot(self, ctx):
        """A part already in the only slot should be reassigned back into it."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)

        p = inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10, slot_id=slots[0].id,
        )

        scope = AssignmentScope(all_parts=False, categories=["Capacitors"])
        plan = assignment_svc.plan("full_rebuild", scope)

        # The part's current slot must be reusable — it should be assigned
        assert len(plan.assignments) == 1
        assert len(plan.unassigned_part_ids) == 0
        assert plan.assignments[0][0] == p.id

        # Full round-trip: assign() must not lose the part
        result = assignment_svc.assign("full_rebuild", scope)
        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id is not None
        assert result.assigned_count == 1
        assert result.unassigned_count == 0

    def test_part_ids_scoped_rebuild_reuses_in_scope_slot(self, ctx):
        """Same bug with explicit part_ids scope."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)

        p = inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10, slot_id=slots[0].id,
        )

        scope = AssignmentScope(all_parts=False, part_ids=[p.id])
        plan = assignment_svc.plan("full_rebuild", scope)

        assert len(plan.assignments) == 1
        assert len(plan.unassigned_part_ids) == 0

        result = assignment_svc.assign("full_rebuild", scope)
        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id is not None

    def test_out_of_scope_occupied_slots_stay_blocked(self, ctx):
        """Slots occupied by out-of-scope parts must NOT be freed."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)

        # Resistor occupies the only slot — out of scope
        p_resistor = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )
        # Capacitor is unassigned — in scope
        p_cap = inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10,
        )

        scope = AssignmentScope(all_parts=False, categories=["Capacitors"])
        plan = assignment_svc.plan("full_rebuild", scope)

        # The resistor's slot is NOT freeable — capacitor must be unassigned
        assert len(plan.assignments) == 0
        assert len(plan.unassigned_part_ids) == 1
        assert plan.unassigned_part_ids[0] == p_cap.id

        # Resistor must stay put after apply
        result = assignment_svc.assign("full_rebuild", scope)
        resistor_updated = part_repo.get_part_by_id(p_resistor.id)
        assert resistor_updated.slot_id == slots[0].id

    def test_mixed_scope_frees_only_in_scope_slots(self, ctx):
        """With 2 slots and 2 parts, only the in-scope part's slot is reusable."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)

        p_resistor = inventory_svc.upsert_part(
            name="100R 0805", category="Resistors", qty=10, slot_id=slots[0].id,
        )
        p_cap = inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10, slot_id=slots[1].id,
        )

        scope = AssignmentScope(all_parts=False, categories=["Capacitors"])
        plan = assignment_svc.plan("full_rebuild", scope)

        # Capacitor's slot is reusable, resistor's is not
        assert len(plan.assignments) == 1
        assert len(plan.unassigned_part_ids) == 0
        assert plan.assignments[0][0] == p_cap.id


    def test_undo_already_undone_run(self, ctx):
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)
        _create_parts(inventory_svc, [("100R 0805", "Resistors", "loose", 10)])

        plan = assignment_svc.plan("incremental", AssignmentScope())
        run_id = assignment_svc.apply_plan(plan, "incremental", AssignmentScope())

        assignment_svc.undo_run(run_id)
        # Second undo should be a no-op
        restored, conflicts = assignment_svc.undo_run(run_id)
        assert restored == 0
        assert conflicts == []


# ──────────────────────────────────────────────────────────
# Compatibility matrix & fallback placement
# ──────────────────────────────────────────────────────────


class TestFallbackPlacement:
    def test_small_part_falls_back_to_large_cell(self, ctx):
        """Small passive with no small cells but a large cell → placed in large cell."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        p = inventory_svc.upsert_part(name="100nF 0805", category="Capacitors", qty=10)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id == slots[0].id

    def test_binder_part_falls_back_to_small_cell(self, ctx):
        """IC with no binder cards but small cells → placed in small cell."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)

        p = inventory_svc.upsert_part(name="TL072 SOIC-8", category="ICs", qty=2)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id is not None

    def test_binder_part_falls_back_to_large_cell(self, ctx):
        """IC with only large cells → placed with penalty (fallback)."""
        assignment_svc, storage_svc, inventory_svc, _, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        inventory_svc.upsert_part(name="TL072 SOIC-8", category="ICs", qty=2)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1
        assert result.unassigned_count == 0

    def test_large_part_cannot_fit_in_small_cell(self, ctx):
        """Large part with only small cells → cannot be assigned."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=2)

        inventory_svc.upsert_part(name="Toggle Switch", category="Switches", qty=5)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 1

    def test_long_part_cannot_fit_in_large_only_cell(self, ctx):
        """Through-hole resistor with no long cells, only large → cannot be assigned."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        p = inventory_svc.upsert_part(name="10K 1/4W", category="Resistors", qty=50)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 0
        assert result.unassigned_count == 1

    def test_long_part_fits_in_long_cell(self, ctx):
        """Through-hole resistor goes to long cell (which is large by definition)."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(
            slot_id=slots[0].id, cell_size="large", cell_length="long",
        )

        p = inventory_svc.upsert_part(name="10K 1/4W", category="Resistors", qty=50)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id == slots[0].id

    def test_large_part_fits_in_long_cell(self, ctx):
        """Large part can go in a long cell (long is also large)."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(
            slot_id=slots[0].id, cell_size="large", cell_length="long",
        )

        p = inventory_svc.upsert_part(name="Toggle Switch", category="Switches", qty=5)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 1

        updated = part_repo.get_part_by_id(p.id)
        assert updated.slot_id == slots[0].id


# ──────────────────────────────────────────────────────────
# Binder card capacity
# ──────────────────────────────────────────────────────────


class TestBinderCardCapacity:
    def test_multiple_parts_per_card(self, ctx):
        """3 ICs with 1 binder card (4 bags) → all 3 assigned to same card."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_binder(name="Binder 1", num_cards=1, bags_per_card=4)

        parts = _create_parts(inventory_svc, [
            ("TL072 SOIC-8", "ICs", None, 3),
            ("LM358 SOIC-8", "ICs", None, 2),
            ("NE555 SOIC-8", "ICs", None, 1),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 3
        assert result.unassigned_count == 0

        # All should be on the same card
        slot_ids = {part_repo.get_part_by_id(p.id).slot_id for p in parts}
        assert len(slot_ids) == 1

    def test_overflow_at_bag_count(self, ctx):
        """5 ICs with 1 card (4 bags) → 4 assigned, 1 unassigned."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_binder(name="Binder 1", num_cards=1, bags_per_card=4)

        _create_parts(inventory_svc, [
            ("TL072 SOIC-8", "ICs", None, 1),
            ("LM358 SOIC-8", "ICs", None, 1),
            ("NE555 SOIC-8", "ICs", None, 1),
            ("LM741 SOIC-8", "ICs", None, 1),
            ("LM324 SOIC-8", "ICs", None, 1),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 4
        assert result.unassigned_count == 1

    def test_spreads_across_cards(self, ctx):
        """5 ICs with 2 cards (2 bags each) → all 4 fit, 1 unassigned."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_binder(name="Binder 1", num_cards=2, bags_per_card=2)

        _create_parts(inventory_svc, [
            ("TL072 SOIC-8", "ICs", None, 1),
            ("LM358 SOIC-8", "ICs", None, 1),
            ("NE555 SOIC-8", "ICs", None, 1),
            ("LM741 SOIC-8", "ICs", None, 1),
            ("LM324 SOIC-8", "ICs", None, 1),
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 4
        assert result.unassigned_count == 1


# ──────────────────────────────────────────────────────────
# Scarcity ordering
# ──────────────────────────────────────────────────────────


class TestScarcityOrdering:
    def test_constrained_part_gets_its_slot(self, ctx):
        """A large part (only fits large cells) and a small part (fits large or small)
        with 1 large cell and 1 small cell → large part gets large cell, small gets small."""
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")
        # slots[1] stays small/short

        p_switch = inventory_svc.upsert_part(name="Toggle Switch", category="Switches", qty=5)
        p_cap = inventory_svc.upsert_part(name="100nF 0805", category="Capacitors", qty=10)

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 2

        # Switch (LARGE_CELL, more constrained) should get the large cell
        switch_updated = part_repo.get_part_by_id(p_switch.id)
        assert switch_updated.slot_id == slots[0].id

        # Cap (SMALL_SHORT_CELL, flexible) should get the small cell
        cap_updated = part_repo.get_part_by_id(p_cap.id)
        assert cap_updated.slot_id == slots[1].id


# ──────────────────────────────────────────────────────────
# Unassigned reasons
# ──────────────────────────────────────────────────────────


class TestUnassignedReasons:
    def test_reason_no_compatible_slot(self, ctx):
        """Long part with only small cells → reason explains no compatible type."""
        assignment_svc, storage_svc, inventory_svc, _, storage_repo, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)

        p = inventory_svc.upsert_part(name="10K 1/4W", category="Resistors", qty=50)

        plan = assignment_svc.plan("incremental", AssignmentScope())
        assert p.id in plan.unassigned_part_ids
        assert plan.reason_for(p.id) == "no compatible slot type exists"

    def test_large_part_goes_to_binder(self, ctx):
        """Large part with only binder cards → assigned (binders have no restrictions)."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_binder(name="Binder 1", num_cards=1)

        p = inventory_svc.upsert_part(name="Toggle Switch", category="Switches", qty=5)

        plan = assignment_svc.plan("incremental", AssignmentScope())
        assert len(plan.assignments) == 1
        assert p.id not in plan.unassigned_part_ids

    def test_reason_all_full(self, ctx):
        """2 small parts, 1 small cell → second part gets 'all compatible slots are full'."""
        assignment_svc, storage_svc, inventory_svc, _, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=1, cols=1)

        p1 = inventory_svc.upsert_part(name="100nF 0805", category="Capacitors", qty=10)
        p2 = inventory_svc.upsert_part(name="10nF 0805", category="Capacitors", qty=10)

        plan = assignment_svc.plan("incremental", AssignmentScope())
        assert len(plan.unassigned_part_ids) == 1
        unassigned_id = plan.unassigned_part_ids[0]
        assert plan.reason_for(unassigned_id) == "all compatible slots are full"

    def test_reason_for_returns_unknown_for_assigned(self, ctx):
        """reason_for() returns 'unknown' for parts not in unassigned_reasons."""
        plan = AssignmentPlan(
            assignments=((1, 10),),
            unassigned_part_ids=(),
            estimate=StorageEstimate(),
        )
        assert plan.reason_for(1) == "unknown"


# ──────────────────────────────────────────────────────────
# Full rebuild: no churn penalty → optimal placement
# ──────────────────────────────────────────────────────────


class TestFullRebuildOptimalPlacement:
    def test_full_rebuild_ignores_churn_for_better_fit(self, ctx):
        """Full rebuild should place parts optimally even when they already have slots.

        Place a switch in a small cell and a capacitor in a large cell (sub-optimal).
        Full rebuild should swap them: switch → large, capacitor → small.
        """
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        container = storage_svc.configure_grid_box(name="Box 1", rows=1, cols=2)
        slots = storage_repo.list_slots_for_container(container.id)
        # slots[0] = large, slots[1] = small
        storage_svc.update_cell_properties(slot_id=slots[0].id, cell_size="large")

        # Deliberately place parts sub-optimally
        p_switch = inventory_svc.upsert_part(
            name="Toggle Switch", category="Switches", qty=5, slot_id=slots[1].id,
        )
        p_cap = inventory_svc.upsert_part(
            name="100nF 0805", category="Capacitors", qty=10, slot_id=slots[0].id,
        )

        result = assignment_svc.assign("full_rebuild", AssignmentScope())
        assert result.assigned_count == 2

        # After rebuild: switch should be in large cell, cap in small cell
        switch_updated = part_repo.get_part_by_id(p_switch.id)
        cap_updated = part_repo.get_part_by_id(p_cap.id)
        assert switch_updated.slot_id == slots[0].id  # large cell
        assert cap_updated.slot_id == slots[1].id  # small cell


# ──────────────────────────────────────────────────────────
# Count-based category affinity
# ──────────────────────────────────────────────────────────


class TestCountBasedCategoryAffinity:
    def test_majority_container_wins(self, ctx):
        """Category affinity should track the container with the most parts.

        If 3 resistors go to Box A and 1 is forced to Box B, subsequent
        resistors should prefer Box A (majority).
        """
        assignment_svc, storage_svc, inventory_svc, part_repo, storage_repo, _ = ctx

        # Box A: 3 long cells
        container_a = storage_svc.configure_grid_box(name="Box A", rows=1, cols=3)
        for s in storage_repo.list_slots_for_container(container_a.id):
            storage_svc.update_cell_properties(slot_id=s.id, cell_length="long")

        # Box B: 2 long cells
        container_b = storage_svc.configure_grid_box(name="Box B", rows=1, cols=2)
        for s in storage_repo.list_slots_for_container(container_b.id):
            storage_svc.update_cell_properties(slot_id=s.id, cell_length="long")

        # Create 5 through-hole resistors
        parts = _create_parts(inventory_svc, [
            (f"R{i} 1/4W", "Resistors", "cut_tape", 10)
            for i in range(5)
        ])

        result = assignment_svc.assign("incremental", AssignmentScope())
        assert result.assigned_count == 5

        # Count how many went to each container
        container_ids = []
        for p in parts:
            updated = part_repo.get_part_by_id(p.id)
            slot = storage_repo.get_slot(updated.slot_id)
            container_ids.append(slot.container_id)

        # All should be grouped — Box A has 3 slots, so 3 go there; Box B gets 2
        from collections import Counter
        counts = Counter(container_ids)
        assert counts[container_a.id] == 3
        assert counts[container_b.id] == 2


# ──────────────────────────────────────────────────────────
# Deterministic ordering
# ──────────────────────────────────────────────────────────


class TestDeterministicOrdering:
    def test_same_scarcity_produces_deterministic_result(self, ctx):
        """Parts with identical scarcity should produce the same assignments every time."""
        assignment_svc, storage_svc, inventory_svc, part_repo, _, _ = ctx

        storage_svc.configure_grid_box(name="Box 1", rows=2, cols=3)

        _create_parts(inventory_svc, [
            ("100nF 0805", "Capacitors", "loose", 10),
            ("10nF 0805", "Capacitors", "loose", 10),
            ("1uF 0805", "Capacitors", "loose", 10),
        ])

        plan1 = assignment_svc.plan("incremental", AssignmentScope())
        plan2 = assignment_svc.plan("incremental", AssignmentScope())

        assert plan1.assignments == plan2.assignments
