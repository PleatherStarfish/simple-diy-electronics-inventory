import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.models import RawBomItem
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.bom import BomService
from eurorack_inventory.services.bom_matching import BomMatchingService
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.services.storage import StorageService


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def ctx(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    bom_repo = BomRepository(db)
    search_svc = SearchService(part_repo)
    inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
    storage_svc = StorageService(storage_repo, audit_repo)
    storage_svc.ensure_default_unassigned_slot()
    matching_svc = BomMatchingService(search_svc, part_repo)
    bom_svc = BomService(bom_repo, part_repo, matching_svc, audit_repo)
    yield bom_svc, inventory_svc, search_svc, bom_repo, db
    db.close()


def _write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


class TestBomServiceImportCSV:
    def test_import_combined_csv(self, ctx, tmp_path):
        bom_svc, _, _, bom_repo, _ = ctx
        csv_path = tmp_path / "combined.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "5", "DETAILS": ""},
            {"_module": "Sloth", "VALUE": "TL072", "QUANTITY": "2", "DETAILS": ""},
            {"_module": "Neuron", "VALUE": "10K", "QUANTITY": "3", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        assert len(sources) == 2
        names = {s.module_name for s in sources}
        assert names == {"Sloth", "Neuron"}

        # Verify raw and normalized items created
        for source in sources:
            raw = bom_repo.list_raw_items(source.id)
            norm = bom_repo.list_normalized_items(source.id)
            assert len(raw) > 0
            assert len(norm) > 0

    def test_reimport_replaces_existing(self, ctx, tmp_path):
        bom_svc, _, _, bom_repo, _ = ctx
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "5", "DETAILS": ""},
        ])

        sources1 = bom_svc.import_csv(csv_path)
        assert len(sources1) == 1
        first_id = sources1[0].id

        sources2 = bom_svc.import_csv(csv_path)
        assert len(sources2) == 1
        assert sources2[0].id != first_id
        assert bom_repo.get_bom_source(first_id) is None  # old deleted

    def test_import_creates_audit_events(self, ctx, tmp_path):
        bom_svc, _, _, _, db = ctx
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""},
        ])
        bom_svc.import_csv(csv_path)
        events = db.query_all(
            "SELECT * FROM audit_events WHERE event_type = 'bom.imported'"
        )
        assert len(events) == 1


class TestBomServiceImportPdf:
    def test_import_pdf_persists_rows_from_uppercase_normalized_table(self, ctx, tmp_path, monkeypatch):
        bom_svc, _, _, bom_repo, _ = ctx
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_text("fake pdf")

        uppercase_table = pd.DataFrame(
            {
                "VALUE": ["100n", "TL072"],
                "QUANTITY": ["3", "1"],
                "DETAILS": ["0805", "SOIC"],
            }
        )

        monkeypatch.setattr(
            "eurorack_inventory.services.bom.get_pdf_runtime_status",
            lambda: SimpleNamespace(available=True),
        )
        monkeypatch.setitem(sys.modules, "tabula", SimpleNamespace())
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._extract_tables_from_pdf",
            lambda *_args, **_kwargs: [uppercase_table],
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._clean_bom_dataframe_with_reason",
            lambda df, min_cols=2, min_rows=3: (df, ""),
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._normalize_bom_table_with_reason",
            lambda df: (df, ""),
        )

        source = bom_svc.import_pdf(pdf_path)

        assert len(bom_repo.list_raw_items(source.id)) == 2
        assert len(bom_repo.list_normalized_items(source.id)) == 2

    def test_import_pdf_handles_variant_rows_with_float_designators(self, ctx, tmp_path, monkeypatch):
        bom_svc, _, _, bom_repo, _ = ctx
        pdf_path = tmp_path / "variant.pdf"
        pdf_path.write_text("fake pdf")

        variant_table = pd.DataFrame(
            {
                0: [float("nan"), "R1", "R2"],
                "torpor": ["100K", "220K", "330K"],
                "apathy": ["", "", ""],
                "inertia": ["", "", ""],
            }
        )

        monkeypatch.setattr(
            "eurorack_inventory.services.bom.get_pdf_runtime_status",
            lambda: SimpleNamespace(available=True),
        )
        monkeypatch.setitem(sys.modules, "tabula", SimpleNamespace())
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._extract_tables_from_pdf",
            lambda *_args, **_kwargs: [variant_table],
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._clean_bom_dataframe_with_reason",
            lambda df, min_cols=2, min_rows=3: (df, ""),
        )

        source = bom_svc.import_pdf(pdf_path)

        assert len(bom_repo.list_raw_items(source.id)) == 3
        assert len(bom_repo.list_normalized_items(source.id)) == 3

    def test_import_pdf_rejects_empty_extraction_without_creating_source(self, ctx, tmp_path, monkeypatch):
        bom_svc, _, _, bom_repo, _ = ctx
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_text("fake pdf")

        monkeypatch.setattr(
            "eurorack_inventory.services.bom.get_pdf_runtime_status",
            lambda: SimpleNamespace(available=True),
        )
        monkeypatch.setattr("eurorack_inventory.services.bom.extract_pdf", lambda _path: [])

        with pytest.raises(ValueError, match="No BOM data detected"):
            bom_svc.import_pdf(pdf_path)

        assert bom_repo.count_bom_sources() == 0

    def test_import_pdf_persists_after_reopen(self, tmp_path, monkeypatch):
        db_path = tmp_path / "persist.db"
        db = Database(db_path)
        MigrationRunner(db, MIGRATIONS_DIR).apply()
        part_repo = PartRepository(db)
        storage_repo = StorageRepository(db)
        audit_repo = AuditRepository(db)
        bom_repo = BomRepository(db)
        search_svc = SearchService(part_repo)
        inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
        storage_svc = StorageService(storage_repo, audit_repo)
        storage_svc.ensure_default_unassigned_slot()
        matching_svc = BomMatchingService(search_svc, part_repo)
        bom_svc = BomService(bom_repo, part_repo, matching_svc, audit_repo)

        pdf_path = tmp_path / "persist.pdf"
        pdf_path.write_text("fake pdf")

        monkeypatch.setattr(
            "eurorack_inventory.services.bom.get_pdf_runtime_status",
            lambda: SimpleNamespace(available=True),
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom.extract_pdf",
            lambda _path: [
                RawBomItem(
                    id=None,
                    bom_source_id=0,
                    line_number=1,
                    raw_description="100K",
                    raw_qty="2",
                    raw_notes="0805",
                )
            ],
        )

        source = bom_svc.import_pdf(pdf_path)
        assert len(bom_repo.list_raw_items(source.id)) == 1
        db.close()

        reopened = Database(db_path)
        MigrationRunner(reopened, MIGRATIONS_DIR).apply()
        reopened_bom_repo = BomRepository(reopened)
        persisted_source = reopened_bom_repo.get_bom_source(source.id)

        assert persisted_source is not None
        assert len(reopened_bom_repo.list_raw_items(source.id)) == 1
        assert len(reopened_bom_repo.list_normalized_items(source.id)) == 1

        reopened.close()


class TestBomServiceAutoMatch:
    def test_auto_match_finds_inventory_parts(self, ctx, tmp_path):
        bom_svc, inventory_svc, search_svc, bom_repo, _ = ctx

        # Create inventory parts
        inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=10)
        inventory_svc.upsert_part(name="TL072 IC", category="ICs", qty=5)
        search_svc.rebuild()

        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "2", "DETAILS": ""},
            {"_module": "Sloth", "VALUE": "TL072", "QUANTITY": "1", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        source = sources[0]

        matched = bom_svc.auto_match_bom(source.id)
        assert matched >= 1  # at least one should match

        # Check that matched items have part_ids
        items = bom_repo.list_normalized_items(source.id)
        matched_items = [i for i in items if i.part_id is not None]
        assert len(matched_items) >= 1

    def test_unmatched_items_remain(self, ctx, tmp_path):
        bom_svc, _, search_svc, bom_repo, _ = ctx
        search_svc.rebuild()

        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "2", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        bom_svc.auto_match_bom(sources[0].id)

        # No inventory parts exist, so nothing should match
        unmatched = bom_repo.list_unmatched_items(sources[0].id)
        assert len(unmatched) > 0


class TestBomServiceShoppingList:
    def test_shopping_list_with_shortages(self, ctx, tmp_path):
        bom_svc, inventory_svc, search_svc, bom_repo, _ = ctx

        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=3)
        search_svc.rebuild()

        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "5", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        source = sources[0]

        # Manually match
        items = bom_repo.list_normalized_items(source.id)
        for item in items:
            if "100K" in item.normalized_value:
                bom_repo.link_to_part(item.id, part.id, 1.0, "manually_matched")

        shopping = bom_svc.get_shopping_list([source.id])
        assert len(shopping) >= 1
        resistor = next(s for s in shopping if "100K" in s.normalized_value)
        assert resistor.qty_needed == 5
        assert resistor.qty_available == 3
        assert resistor.qty_to_buy == 2

    def test_shopping_list_multiple_boms_same_part(self, ctx, tmp_path):
        """Shortage when multiple BOMs reference the same inventory part."""
        bom_svc, inventory_svc, _, bom_repo, _ = ctx

        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=5)

        for name, hash_val in [("Sloth", "h1"), ("Neuron", "h2")]:
            csv_path = tmp_path / f"{name}.csv"
            _write_csv(csv_path, [
                {"_module": name, "VALUE": "100K", "QUANTITY": "4", "DETAILS": ""},
            ])
            sources = bom_svc.import_csv(csv_path)
            items = bom_repo.list_normalized_items(sources[0].id)
            for item in items:
                bom_repo.link_to_part(item.id, part.id, 1.0, "manually_matched")

        all_sources = bom_repo.list_bom_sources()
        shopping = bom_svc.get_shopping_list([s.id for s in all_sources])
        assert len(shopping) == 1
        assert shopping[0].qty_needed == 8
        assert shopping[0].qty_available == 5
        assert shopping[0].qty_to_buy == 3


class TestBomServicePromotion:
    def test_promote_requires_all_verified(self, ctx, tmp_path):
        bom_svc, inventory_svc, _, bom_repo, _ = ctx

        part = inventory_svc.upsert_part(name="100K", category="R", qty=1)
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        source = sources[0]

        items = bom_repo.list_normalized_items(source.id)
        bom_repo.link_to_part(items[0].id, part.id, 1.0, "manually_matched")
        # Not verified yet
        with pytest.raises(ValueError, match="not verified"):
            bom_svc.promote_to_project(source.id)

    def test_promote_creates_project(self, ctx, tmp_path):
        bom_svc, inventory_svc, _, bom_repo, db = ctx

        part = inventory_svc.upsert_part(name="100K", category="R", qty=1)
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "2", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        source = sources[0]

        items = bom_repo.list_normalized_items(source.id)
        bom_repo.update_normalized_item(
            items[0].id,
            part_id=part.id, match_status="manually_matched", is_verified=True,
        )

        project = bom_svc.promote_to_project(source.id)
        assert project.name == "Sloth"
        assert project.maker == "Nonlinearcircuits"

        # Check promoted_project_id was set
        updated_source = bom_repo.get_bom_source(source.id)
        assert updated_source.promoted_project_id == project.id

        # Check BOM lines created
        bom_lines = db.query_all(
            "SELECT * FROM bom_lines WHERE module_id = ?", (project.id,)
        )
        assert len(bom_lines) == 1
        assert bom_lines[0]["qty_required"] == 2

    def test_promote_twice_raises(self, ctx, tmp_path):
        bom_svc, inventory_svc, _, bom_repo, _ = ctx

        part = inventory_svc.upsert_part(name="100K", category="R", qty=1)
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        items = bom_repo.list_normalized_items(sources[0].id)
        bom_repo.update_normalized_item(
            items[0].id,
            part_id=part.id, match_status="manually_matched", is_verified=True,
        )
        bom_svc.promote_to_project(sources[0].id)

        with pytest.raises(ValueError, match="already promoted"):
            bom_svc.promote_to_project(sources[0].id)


class TestCreatePartAndMatch:
    def test_creates_new_part_with_qty_zero(self, ctx, tmp_path):
        bom_svc, _, _, bom_repo, _ = ctx
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "LM358", "QUANTITY": "2", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        items = bom_repo.list_normalized_items(sources[0].id)
        item = items[0]

        part = bom_svc.create_part_and_match(
            item.id,
            {"name": "LM358", "category": "ic", "default_package": "DIP-8"},
        )

        assert part.id is not None
        assert part.qty == 0
        assert part.name == "LM358"
        assert part.default_package == "DIP-8"

        updated_item = bom_repo.get_normalized_item(item.id)
        assert updated_item.part_id == part.id
        assert updated_item.match_status == "manually_matched"
        assert updated_item.is_verified is True
        assert updated_item.match_confidence == 1.0

    def test_fingerprint_collision_links_without_overwriting(self, ctx, tmp_path):
        bom_svc, inventory_svc, _, bom_repo, _ = ctx

        existing = inventory_svc.upsert_part(
            name="LM358", category="ic", package="DIP-8", qty=50,
        )

        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "LM358", "QUANTITY": "1", "DETAILS": ""},
        ])
        sources = bom_svc.import_csv(csv_path)
        items = bom_repo.list_normalized_items(sources[0].id)

        part = bom_svc.create_part_and_match(
            items[0].id,
            {"name": "LM358", "category": "ic", "default_package": "DIP-8"},
        )

        # Should link to existing part, not create a new one
        assert part.id == existing.id
        # Existing part qty must NOT be overwritten
        from eurorack_inventory.repositories.parts import PartRepository
        fresh = PartRepository(bom_repo.db).get_part_by_id(existing.id)
        assert fresh.qty == 50

        updated_item = bom_repo.get_normalized_item(items[0].id)
        assert updated_item.part_id == existing.id
        assert updated_item.match_status == "manually_matched"
        assert updated_item.is_verified is True

    def test_atomicity_on_invalid_item_id(self, ctx, tmp_path):
        bom_svc, _, _, bom_repo, db = ctx

        parts_before = db.query_one("SELECT COUNT(*) as c FROM parts")["c"]

        with pytest.raises(Exception):
            bom_svc.create_part_and_match(
                999999,  # non-existent item
                {"name": "Ghost Part", "category": "resistor"},
            )

        parts_after = db.query_one("SELECT COUNT(*) as c FROM parts")["c"]
        assert parts_after == parts_before
