from pathlib import Path

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
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
    assert part.slot_id == slot.id

    new_qty = inventory_service.adjust_qty(part.id, -10)
    assert new_qty == 40

    updated = part_repo.get_part_by_id(part.id)
    assert updated is not None
    assert updated.qty == 40

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
