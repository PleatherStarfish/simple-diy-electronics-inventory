from pathlib import Path

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.storage import StorageService


def test_upsert_and_adjust_qty(tmp_path: Path) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)

    slot = storage_service.ensure_default_unassigned_slot()

    part = inventory_service.upsert_part(name="100k resistor", category="Resistors", qty=50, slot_id=slot.id)
    assert part.qty == 50
    assert part.slot_id is None
    assert [(location.slot_id, location.qty) for location in part_repo.list_part_locations(part.id)] == [
        (slot.id, 50),
    ]

    new_qty = inventory_service.adjust_qty(part.id, -10)
    assert new_qty == 40

    updated = part_repo.get_part_by_id(part.id)
    assert updated is not None
    assert updated.qty == 40
    assert [(location.slot_id, location.qty) for location in part_repo.list_part_locations(part.id)] == [
        (slot.id, 40),
    ]

    db.close()


def test_delete_part(tmp_path: Path) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)

    part = inventory_service.upsert_part(name="TL072", category="ICs", qty=4)
    inventory_service.delete_part(part.id)

    assert part_repo.get_part_by_id(part.id) is None

    db.close()


def test_reassign_bumps_occupant_to_unassigned(tmp_path: Path) -> None:
    """Dropping a part onto an occupied slot should bump the occupant to Unassigned."""
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)
    storage_service.ensure_default_unassigned_slot()

    container = storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slots = storage_repo.list_slots_for_container(container.id)
    slot_a, slot_b = slots[0], slots[1]

    p1 = inventory_service.upsert_part(name="100R 0805", category="Resistors", qty=10, slot_id=slot_a.id)
    p2 = inventory_service.upsert_part(name="220R 0805", category="Resistors", qty=10, slot_id=slot_b.id)

    # Drag p1 onto p2's slot — p2 should be bumped to unassigned
    inventory_service.reassign_part_slot(p1.id, slot_b.id)

    p1_updated = part_repo.get_part_by_id(p1.id)
    p2_updated = part_repo.get_part_by_id(p2.id)

    assert p1_updated.slot_id == slot_b.id

    # p2 should now be in the Unassigned container
    unassigned_container = storage_repo.get_container_by_name("Unassigned")
    unassigned_slot = storage_repo.get_slot_by_label(unassigned_container.id, "Main")
    assert p2_updated.slot_id is None
    assert [(location.slot_id, location.qty) for location in part_repo.list_part_locations(p2.id)] == [
        (unassigned_slot.id, 10),
    ]

    db.close()


def test_replace_part_locations_splits_quantity_and_updates_summary(tmp_path: Path) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)

    container = storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slots = storage_repo.list_slots_for_container(container.id)
    slot_a, slot_b = slots[0], slots[1]

    part = inventory_service.upsert_part(name="100R 0805", category="Resistors", qty=10)
    inventory_service.replace_part_locations(part.id, [(slot_a.id, 7), (slot_b.id, 3)])

    updated = part_repo.get_part_by_id(part.id)
    assert updated is not None
    assert updated.slot_id is None
    assert [(location.slot_id, location.qty) for location in part_repo.list_part_locations(part.id)] == [
        (slot_a.id, 7),
        (slot_b.id, 3),
    ]

    [summary] = inventory_service.list_inventory([part.id])
    assert summary.locations == "Box 1 / A0 (7) +1 more"

    db.close()


def test_change_override_to_large_unassigns_from_small_cell(tmp_path: Path) -> None:
    """Setting a part's storage class to LARGE should auto-unassign it from a small cell."""
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo, part_repo)

    container = storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slots = storage_repo.list_slots_for_container(container.id)
    small_slot = slots[0]  # default: small/short

    part = inventory_service.upsert_part(name="10k resistor", category="Resistors", qty=5, slot_id=small_slot.id)
    assert part.slot_id == small_slot.id

    # Change override to LARGE_CELL — can't fit in small cell
    updated = inventory_service.update_part(part.id, storage_class_override=StorageClass.LARGE_CELL.value)
    assert updated.slot_id is None

    db.close()


def test_change_override_to_large_keeps_large_cell(tmp_path: Path) -> None:
    """Setting a part's storage class to LARGE should keep it in a large cell."""
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo, part_repo)

    container = storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slots = storage_repo.list_slots_for_container(container.id)
    slot = slots[0]
    storage_service.update_cell_properties(slot_id=slot.id, cell_size="large")

    part = inventory_service.upsert_part(name="10k resistor", category="Resistors", qty=5, slot_id=slot.id)

    # Change override to LARGE_CELL — still fits in large cell
    updated = inventory_service.update_part(part.id, storage_class_override=StorageClass.LARGE_CELL.value)
    assert updated.slot_id == slot.id

    db.close()


def test_shrink_cell_unassigns_large_part(tmp_path: Path) -> None:
    """Shrinking a cell should auto-unassign parts that no longer fit."""
    migrations_dir = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo, part_repo)

    container = storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slots = storage_repo.list_slots_for_container(container.id)
    slot = slots[0]
    storage_service.update_cell_properties(slot_id=slot.id, cell_size="large")

    # Place a large part
    part = inventory_service.upsert_part(name="Toggle Switch", category="Switches", qty=3, slot_id=slot.id)
    inventory_service.update_part(part.id, storage_class_override=StorageClass.LARGE_CELL.value)
    assert part_repo.get_part_by_id(part.id).slot_id == slot.id

    # Now shrink the cell back to small — part should be auto-unassigned
    storage_service.update_cell_properties(slot_id=slot.id, cell_size="small")
    assert part_repo.get_part_by_id(part.id).slot_id is None

    db.close()
