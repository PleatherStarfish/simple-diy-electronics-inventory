from pathlib import Path

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.services.storage import StorageService


def test_search_prefers_direct_name_and_alias(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations").apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)
    slot = storage_service.ensure_default_unassigned_slot()

    part = inventory_service.upsert_part(name="TL072CP", category="ICs", supplier_sku="A-123", qty=4, slot_id=slot.id)
    inventory_service.add_alias(part.id, "TL072")

    other = inventory_service.upsert_part(name="TL074CP", category="ICs", supplier_sku="A-456", qty=2, slot_id=slot.id)

    search = SearchService(part_repo)
    search.rebuild()

    ids = search.search("tl072")
    assert ids[0] == part.id

    db.close()
