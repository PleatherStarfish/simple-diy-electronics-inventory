from __future__ import annotations

from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.models import BomLine, Project, StorageContainer, StorageSlot
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.common import make_part_fingerprint
from eurorack_inventory.repositories.dedup_feedback import DedupFeedbackRepository
from eurorack_inventory.services.dedup import DedupService
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.services.storage import StorageService

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "eurorack_inventory"
    / "db"
    / "migrations"
)


@pytest.fixture()
def ctx(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    project_repo = ProjectRepository(db)
    search_svc = SearchService(part_repo)
    inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
    storage_svc = StorageService(storage_repo, audit_repo)
    storage_svc.ensure_default_unassigned_slot()
    feedback_repo = DedupFeedbackRepository(db)
    dedup_svc = DedupService(db, part_repo, audit_repo, search_svc, feedback_repo)
    yield {
        "db": db,
        "part_repo": part_repo,
        "audit_repo": audit_repo,
        "project_repo": project_repo,
        "storage_repo": storage_repo,
        "inventory_svc": inventory_svc,
        "search_svc": search_svc,
        "dedup_svc": dedup_svc,
    }
    db.close()


def _make_part(ctx, *, name, category=None, qty=0, supplier_sku=None, mpn=None,
               manufacturer=None, default_package=None, slot_id=None, notes=None):
    return ctx["inventory_svc"].upsert_part(
        name=name, category=category, supplier_sku=supplier_sku,
        package=default_package, qty=qty, slot_id=slot_id, notes=notes,
    )


def _update_part(ctx, part_id, **fields):
    ctx["inventory_svc"].update_part(part_id, **fields)


def _create_project(ctx, name="Test Project"):
    proj = Project(id=None, fingerprint=f"test|{name}|", name=name, maker="Test")
    return ctx["project_repo"].upsert_project(proj)


def _add_bom_line(ctx, project_id, part_id, qty=1, reference_note=None, is_optional=False):
    bl = BomLine(
        id=None, project_id=project_id, part_id=part_id,
        qty_required=qty, reference_note=reference_note, is_optional=is_optional,
    )
    return ctx["project_repo"].add_bom_line(bl)


_slot_counter = 0

def _create_slot(ctx, container_name="Box1", label="A1"):
    """Create a storage container and slot, return slot_id."""
    global _slot_counter
    _slot_counter += 1
    unique_name = f"{container_name}_{_slot_counter}"
    container = ctx["storage_repo"].create_container(
        StorageContainer(id=None, name=unique_name, container_type="grid_box",
                         metadata={"rows": 2, "cols": 2}),
    )
    slot = ctx["storage_repo"].create_slot(
        StorageSlot(id=None, container_id=container.id, label=label, slot_type="cell"),
    )
    return slot.id


# ──────────────────────────────────────────────────────────
# Detection tests
# ──────────────────────────────────────────────────────────


class TestFindDuplicatePairs:
    def test_similar_names_paired(self, ctx):
        _make_part(ctx, name="100K Resistor 1/4W", category="Resistor")
        _make_part(ctx, name="100K Resistor 1/4 Watt", category="Resistor")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=70.0)
        assert len(pairs) >= 1
        names = {pairs[0].part_a.name, pairs[0].part_b.name}
        assert "100K Resistor 1/4W" in names
        assert "100K Resistor 1/4 Watt" in names

    def test_different_categories_not_paired(self, ctx):
        _make_part(ctx, name="100K", category="Resistor")
        _make_part(ctx, name="100K", category="Potentiometer")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=70.0)
        assert len(pairs) == 0

    def test_exact_sku_different_names_paired(self, ctx):
        _make_part(ctx, name="Alpha Pot 100K", supplier_sku="A-1234")
        _make_part(ctx, name="100K Linear Potentiometer", supplier_sku="A-1234")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=90.0)
        assert len(pairs) >= 1
        assert any("exact_sku" in r for r in pairs[0].match_reasons)

    def test_exact_mpn_different_names_paired(self, ctx):
        p1 = _make_part(ctx, name="Ceramic Cap 100nF")
        _update_part(ctx, p1.id, mpn="CC0805KRX7R9BB104", manufacturer="Yageo")
        p2 = _make_part(ctx, name="0.1uF MLCC")
        _update_part(ctx, p2.id, mpn="CC0805KRX7R9BB104", manufacturer="Yageo")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=90.0)
        assert len(pairs) >= 1
        assert any("exact_mpn" in r for r in pairs[0].match_reasons)

    def test_no_transitive_grouping(self, ctx):
        # A and B similar, B and C similar, but A and C are not
        _make_part(ctx, name="TL072 Dual Op-Amp", category="IC")
        _make_part(ctx, name="TL072 Op-Amp IC", category="IC")
        _make_part(ctx, name="Op-Amp IC LM358", category="IC")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=70.0)
        # Each pair should be independent — no single pair should group all three
        for pair in pairs:
            ids = {pair.part_a.id, pair.part_b.id}
            assert len(ids) == 2  # always exactly two parts per pair

    def test_match_reasons_truthful(self, ctx):
        _make_part(ctx, name="100K Resistor 1/4W", category="Resistors")
        _make_part(ctx, name="100K Resistor Quarter Watt", category="Resistors")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=70.0)
        assert len(pairs) >= 1
        reasons = pairs[0].match_reasons
        # Should have typed match reasons
        assert len(reasons) >= 1

    def test_value_gate_rejects_different_values(self, ctx):
        """100nF and 10nF should NOT be paired despite similar names."""
        _make_part(ctx, name="100nF Capacitor", category="Capacitor")
        _make_part(ctx, name="10nF Capacitor", category="Capacitor")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=60.0)
        assert len(pairs) == 0

    def test_value_gate_rejects_different_resistor_values(self, ctx):
        """100K and 10K should NOT be paired."""
        _make_part(ctx, name="100K Resistor", category="Resistor")
        _make_part(ctx, name="10K Resistor", category="Resistor")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=60.0)
        assert len(pairs) == 0

    def test_value_gate_allows_same_values(self, ctx):
        """Same component value with different descriptions should still pair."""
        _make_part(ctx, name="100nF Capacitor", category="Capacitor")
        _make_part(ctx, name="100nF Cap MLCC", category="Capacitor")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=60.0)
        assert len(pairs) == 1

    def test_unknown_category_parts_not_paired_by_typed_blocking(self, ctx):
        """Parts without typed identity fields are not paired by the new system.
        This is intentional — only typed blocking generates candidates now."""
        _make_part(ctx, name="Arduino Nano", category="Dev Board")
        _make_part(ctx, name="Arduino Nano Clone", category="Dev Board")
        ctx["search_svc"].rebuild()
        pairs = ctx["dedup_svc"].find_duplicate_pairs(threshold=60.0)
        # No typed blocking rule matches for "Dev Board" category
        assert len(pairs) == 0


# ──────────────────────────────────────────────────────────
# Merge — data integrity
# ──────────────────────────────────────────────────────────


class TestMergeDataIntegrity:
    def test_sums_quantities(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor", qty=5)
        p2 = _make_part(ctx, name="10K Resistor 1/4W", qty=3)
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        assert result.qty_added == 3
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.qty == 8

    def test_transfers_aliases(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K 1/4W Resistor")
        ctx["inventory_svc"].add_alias(p2.id, "Ten K Res")
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        assert result.aliases_transferred >= 1
        aliases = ctx["part_repo"].list_aliases_for_part(p1.id)
        alias_texts = {a.alias for a in aliases}
        assert "Ten K Res" in alias_texts
        assert "10K 1/4W Resistor" in alias_texts  # removed part's name

    def test_remaps_bom_lines_preserving_semantics(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res")
        proj = _create_project(ctx)
        _add_bom_line(ctx, proj.id, p2.id, qty=2, reference_note="R1,R2", is_optional=False)
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        assert result.bom_lines_remapped == 1
        # Verify the row preserved its semantics
        rows = ctx["db"].query_all(
            "SELECT * FROM bom_lines WHERE part_id = ?", (p1.id,)
        )
        assert len(rows) == 1
        assert rows[0]["qty_required"] == 2
        assert rows[0]["reference_note"] == "R1,R2"
        assert rows[0]["is_optional"] == 0

    def test_both_parts_in_same_bom_both_rows_survive(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res")
        proj = _create_project(ctx)
        _add_bom_line(ctx, proj.id, p1.id, qty=2, reference_note="R1,R2")
        _add_bom_line(ctx, proj.id, p2.id, qty=1, reference_note="R3")
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        rows = ctx["db"].query_all(
            "SELECT * FROM bom_lines WHERE module_id = ? AND part_id = ? ORDER BY reference_note",
            (proj.id, p1.id),
        )
        assert len(rows) == 2
        refs = {row["reference_note"] for row in rows}
        assert refs == {"R1,R2", "R3"}

    def test_remaps_normalized_bom_items(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res")
        # Insert a normalized_bom_item directly (matching bom_sources schema)
        ctx["db"].execute(
            """INSERT INTO bom_sources (filename, file_path, file_hash, source_kind,
               parser_key, manufacturer, module_name, extracted_at)
               VALUES ('test.csv', '/tmp/test.csv', 'abc', 'csv', 'nlc',
                       'Test', 'TestModule', '2024-01-01T00:00:00Z')"""
        )
        source_id = ctx["db"].scalar("SELECT id FROM bom_sources ORDER BY id DESC LIMIT 1")
        ctx["db"].execute(
            """INSERT INTO raw_bom_items (bom_source_id, line_number, raw_description)
               VALUES (?, 1, 'test')""",
            (source_id,),
        )
        raw_id = ctx["db"].scalar("SELECT id FROM raw_bom_items ORDER BY id DESC LIMIT 1")
        ctx["db"].execute(
            """INSERT INTO normalized_bom_items
               (bom_source_id, raw_item_id, normalized_value, qty, part_id, match_status)
               VALUES (?, ?, '10K Res', 1, ?, 'matched')""",
            (source_id, raw_id, p2.id),
        )
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        assert result.normalized_items_remapped == 1
        row = ctx["db"].query_one(
            "SELECT part_id FROM normalized_bom_items WHERE id = (SELECT MAX(id) FROM normalized_bom_items)"
        )
        assert row["part_id"] == p1.id

    def test_adopts_blank_fields_only(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor", category="Resistor")
        p2 = _make_part(ctx, name="10K Res", category="Passive")
        _update_part(ctx, p2.id, manufacturer="Yageo", mpn="RC0805", supplier_name="Tayda",
                     supplier_sku="A-1234", default_package="0805")
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        # Keeper's non-null category should NOT be overwritten
        assert merged.category == "Resistor"
        # Keeper's blank fields should be adopted
        assert merged.manufacturer == "Yageo"
        assert merged.mpn == "RC0805"
        assert merged.supplier_name == "Tayda"
        assert merged.supplier_sku == "A-1234"
        assert merged.default_package == "0805"

    def test_adopts_storage_class_override(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res")
        _update_part(ctx, p2.id, storage_class_override="binder_card")
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.storage_class_override == "binder_card"


# ──────────────────────────────────────────────────────────
# Merge — slot handling
# ──────────────────────────────────────────────────────────


class TestMergeSlots:
    def test_keeper_has_slot_removed_does_not(self, ctx):
        slot_id = _create_slot(ctx, "Box1", "A1")
        p1 = _make_part(ctx, name="Part A", slot_id=slot_id)
        p2 = _make_part(ctx, name="Part B")
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.slot_id == slot_id
        assert result.discarded_slot_label is None

    def test_keeper_no_slot_adopts_removed_slot(self, ctx):
        slot_id = _create_slot(ctx, "Box1", "A1")
        p1 = _make_part(ctx, name="Part A")
        p2 = _make_part(ctx, name="Part B", slot_id=slot_id)
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.slot_id == slot_id
        assert result.discarded_slot_label is None

    def test_different_slots_requires_keep_slot_id(self, ctx):
        slot_a = _create_slot(ctx, "Box1", "A1")
        slot_b = _create_slot(ctx, "Box2", "B1")
        p1 = _make_part(ctx, name="Part A", slot_id=slot_a)
        p2 = _make_part(ctx, name="Part B", slot_id=slot_b)
        with pytest.raises(ValueError, match="Slot conflict"):
            ctx["dedup_svc"].merge_parts(p1.id, p2.id)

    def test_different_slots_with_choice(self, ctx):
        slot_a = _create_slot(ctx, "Box1", "A1")
        slot_b = _create_slot(ctx, "Box2", "B1")
        p1 = _make_part(ctx, name="Part A", slot_id=slot_a)
        p2 = _make_part(ctx, name="Part B", slot_id=slot_b)
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id, keep_slot_id=slot_a)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.slot_id == slot_a
        assert result.discarded_slot_label is not None
        assert "Box2" in result.discarded_slot_label

    def test_same_slot_no_conflict(self, ctx):
        slot_id = _create_slot(ctx, "Box1", "A1")
        p1 = _make_part(ctx, name="Part A", slot_id=slot_id)
        p2 = _make_part(ctx, name="Part B", slot_id=slot_id)
        result = ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        assert merged.slot_id == slot_id
        assert result.discarded_slot_label is None


# ──────────────────────────────────────────────────────────
# Merge — fingerprint
# ──────────────────────────────────────────────────────────


class TestMergeFingerprint:
    def test_fingerprint_recomputed_after_adoption(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res", supplier_sku="A-999")
        old_fp = ctx["part_repo"].get_part_by_id(p1.id).fingerprint
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        merged = ctx["part_repo"].get_part_by_id(p1.id)
        # Fingerprint should have changed since supplier_sku was adopted
        expected = make_part_fingerprint(
            category=merged.category, name=merged.name,
            supplier_sku=merged.supplier_sku, package=merged.default_package,
        )
        assert merged.fingerprint == expected
        assert merged.fingerprint != old_fp

    def test_fingerprint_collision_rolls_back(self, ctx):
        # Create a third part whose fingerprint will collide after merge
        p_existing = _make_part(ctx, name="10K Resistor", supplier_sku="A-999")
        p1 = _make_part(ctx, name="10K Resistor")  # no sku
        p2 = _make_part(ctx, name="10K Res", supplier_sku="A-999")
        # After merge, p1 would adopt sku "A-999" from p2, colliding with p_existing
        with pytest.raises(ValueError, match="fingerprint collision"):
            ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        # Both parts should still exist (transaction rolled back)
        assert ctx["part_repo"].get_part_by_id(p1.id) is not None
        assert ctx["part_repo"].get_part_by_id(p2.id) is not None


# ──────────────────────────────────────────────────────────
# Merge — safety
# ──────────────────────────────────────────────────────────


class TestMergeSafety:
    def test_cannot_merge_with_self(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        with pytest.raises(ValueError, match="Cannot merge a part with itself"):
            ctx["dedup_svc"].merge_parts(p1.id, p1.id)

    def test_audit_event_logged(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor", qty=3)
        p2 = _make_part(ctx, name="10K Res", qty=2)
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        events = ctx["audit_repo"].list_recent(limit=5)
        merge_events = [e for e in events if e["event_type"] == "part.merged"]
        assert len(merge_events) == 1
        assert merge_events[0]["entity_id"] == p1.id
        assert "10K Res" in merge_events[0]["message"]

    def test_removed_part_is_deleted(self, ctx):
        p1 = _make_part(ctx, name="10K Resistor")
        p2 = _make_part(ctx, name="10K Res")
        ctx["dedup_svc"].merge_parts(p1.id, p2.id)
        assert ctx["part_repo"].get_part_by_id(p2.id) is None
