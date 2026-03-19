from pathlib import Path

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.services.storage import StorageService

MIGRATIONS = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


def _setup(tmp_path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS).apply()
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)
    slot = storage_service.ensure_default_unassigned_slot()
    search = SearchService(part_repo)
    return db, part_repo, inventory_service, search, slot


def test_search_prefers_direct_name_and_alias(tmp_path: Path) -> None:
    db, part_repo, inventory_service, search, slot = _setup(tmp_path)

    part = inventory_service.upsert_part(name="TL072CP", category="ICs", supplier_sku="A-123", qty=4, slot_id=slot.id)
    inventory_service.add_alias(part.id, "TL072")

    other = inventory_service.upsert_part(name="TL074CP", category="ICs", supplier_sku="A-456", qty=2, slot_id=slot.id)

    search.rebuild()

    ids = search.search("tl072")
    assert ids[0] == part.id

    db.close()


def test_exact_value_match_ranks_first(tmp_path: Path) -> None:
    db, part_repo, inventory_service, search, slot = _setup(tmp_path)

    exact = inventory_service.upsert_part(name="7.4M", category="Resistors", qty=10, slot_id=slot.id)
    inventory_service.upsert_part(name="47M", category="Resistors", qty=5, slot_id=slot.id)
    inventory_service.upsert_part(name="7.5M", category="Resistors", qty=8, slot_id=slot.id)
    inventory_service.upsert_part(name="7.4M Resistor", category="Resistors", qty=3, slot_id=slot.id)

    search.rebuild()

    ids = search.search("7.4M")
    assert ids[0] == exact.id

    db.close()


def test_prefix_match_ranks_above_fuzzy(tmp_path: Path) -> None:
    db, part_repo, inventory_service, search, slot = _setup(tmp_path)

    prefix = inventory_service.upsert_part(name="7.4M Resistor", category="Resistors", qty=3, slot_id=slot.id)
    fuzzy = inventory_service.upsert_part(name="47M", category="Resistors", qty=5, slot_id=slot.id)

    search.rebuild()

    ids = search.search("7.4M")
    assert ids.index(prefix.id) < ids.index(fuzzy.id)

    db.close()


def test_search_ordering_preserved_by_repository(tmp_path: Path) -> None:
    db, part_repo, inventory_service, search, slot = _setup(tmp_path)

    p1 = inventory_service.upsert_part(name="Zebra Part", category="Z", qty=1, slot_id=slot.id)
    p2 = inventory_service.upsert_part(name="Alpha Part", category="A", qty=1, slot_id=slot.id)
    p3 = inventory_service.upsert_part(name="Middle Part", category="M", qty=1, slot_id=slot.id)

    # Pass IDs in a specific order that differs from alphabetical
    ordered_ids = [p1.id, p3.id, p2.id]
    summaries = part_repo.list_inventory_summaries(ordered_ids)
    result_ids = [s.part_id for s in summaries]
    assert result_ids == ordered_ids

    db.close()


def test_search_scored_returns_descending_scores(tmp_path: Path) -> None:
    db, part_repo, inventory_service, search, slot = _setup(tmp_path)

    inventory_service.upsert_part(name="7.4M", category="Resistors", qty=10, slot_id=slot.id)
    inventory_service.upsert_part(name="47M", category="Resistors", qty=5, slot_id=slot.id)
    inventory_service.upsert_part(name="7.5M", category="Resistors", qty=8, slot_id=slot.id)
    inventory_service.upsert_part(name="7.4M Resistor", category="Resistors", qty=3, slot_id=slot.id)

    search.rebuild()

    scored = search.search_scored("7.4M")
    scores = [score for _, score in scored]
    assert scores == sorted(scores, reverse=True)

    db.close()
