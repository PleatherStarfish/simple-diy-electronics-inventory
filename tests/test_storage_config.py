from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.enums import CellLength, CellSize, ContainerType, SlotType
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.storage import StorageService


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def services(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    part_repo = PartRepository(db)
    storage_svc = StorageService(storage_repo, audit_repo, part_repo)
    inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
    yield storage_svc, inventory_svc, storage_repo, db
    db.close()


def test_configure_grid_box_auto_populates(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box 1", rows=3, cols=4)

    assert container.container_type == ContainerType.GRID_BOX.value
    assert container.metadata["rows"] == 3
    assert container.metadata["cols"] == 4

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 12  # 3 * 4

    # Check first cell
    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    assert a0 is not None
    assert a0.x1 == 0 and a0.y1 == 0 and a0.x2 == 0 and a0.y2 == 0
    assert a0.metadata["cell_size"] == CellSize.SMALL.value
    assert a0.metadata["cell_length"] == CellLength.SHORT.value

    # Check last cell
    c3 = storage_repo.get_slot_by_label(container.id, "C3")
    assert c3 is not None
    assert c3.x1 == 3 and c3.y1 == 2 and c3.x2 == 3 and c3.y2 == 2


def test_configure_grid_box_can_seed_partial_cells(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(
        name="Box Partial",
        rows=3,
        cols=4,
        initial_cells=3,
    )

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 3
    assert [slot.label for slot in slots] == ["A0", "A1", "A2"]
    assert storage_repo.get_slot_by_label(container.id, "A3") is None
    assert storage_repo.get_slot_by_label(container.id, "B0") is None


def test_configure_grid_box_can_start_empty(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(
        name="Box Empty",
        rows=3,
        cols=4,
        initial_cells=0,
    )

    slots = storage_repo.list_slots_for_container(container.id)
    assert slots == []


def test_configure_binder(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder A", num_cards=5, bags_per_card=6)

    assert container.container_type == ContainerType.BINDER.value
    assert container.metadata["bags_per_card"] == 6

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 5
    assert slots[0].label == "Card 1"
    assert slots[0].metadata["bag_count"] == 6
    assert slots[0].slot_type == SlotType.CARD.value
    assert slots[0].ordinal == 1


def test_configure_binder_default_bags(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder B", num_cards=2)

    slots = storage_repo.list_slots_for_container(container.id)
    assert slots[0].metadata["bag_count"] == 4


def test_merge_cells(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box M", rows=3, cols=3)

    merged = storage_svc.merge_cells(
        container_id=container.id,
        labels=["A0", "A1", "B0", "B1"],
    )

    assert merged.label == "A0-B1"
    assert merged.x1 == 0 and merged.y1 == 0
    assert merged.x2 == 1 and merged.y2 == 1
    assert merged.metadata["cell_size"] == CellSize.LARGE.value
    assert merged.metadata["cell_length"] == CellLength.LONG.value

    # Original cells should be gone
    assert storage_repo.get_slot_by_label(container.id, "A0") is None
    assert storage_repo.get_slot_by_label(container.id, "A1") is None
    assert storage_repo.get_slot_by_label(container.id, "B0") is None
    assert storage_repo.get_slot_by_label(container.id, "B1") is None

    # Merged slot should exist
    assert storage_repo.get_slot_by_label(container.id, "A0-B1") is not None

    # Remaining cells still present
    slots = storage_repo.list_slots_for_container(container.id)
    # 9 original - 4 merged + 1 merged = 6
    assert len(slots) == 6


def test_merge_non_rectangle_fails(services) -> None:
    storage_svc, _, _, _ = services
    container = storage_svc.configure_grid_box(name="Box NR", rows=3, cols=3)

    with pytest.raises(ValueError, match="contiguous rectangle"):
        storage_svc.merge_cells(
            container_id=container.id,
            labels=["A0", "B1"],  # diagonal, not a filled rectangle
        )


def test_merge_allowed_with_one_occupied_slot(services) -> None:
    """Merging is allowed when exactly one of the selected cells has parts."""
    storage_svc, inventory_svc, storage_repo, _ = services
    part_repo = storage_svc.part_repo
    container = storage_svc.configure_grid_box(name="Box S", rows=2, cols=2)

    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    inventory_svc.upsert_part(name="10k resistor", category="Resistors", qty=5, slot_id=a0.id)

    merged = storage_svc.merge_cells(
        container_id=container.id,
        labels=["A0", "A1"],
    )

    # Part should now be assigned to the merged slot
    parts = part_repo.list_parts_by_slot_ids([merged.id])
    assert merged.id in parts
    assert len(parts[merged.id]) == 1
    assert parts[merged.id][0].name == "10k resistor"


def test_merge_blocked_when_multiple_slots_occupied(services) -> None:
    """Merging is blocked when more than one selected cell has parts."""
    storage_svc, inventory_svc, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box S2", rows=2, cols=2)

    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    a1 = storage_repo.get_slot_by_label(container.id, "A1")
    inventory_svc.upsert_part(name="10k resistor", category="Resistors", qty=5, slot_id=a0.id)
    inventory_svc.upsert_part(name="100nF cap", category="Capacitors", qty=3, slot_id=a1.id)

    with pytest.raises(ValueError, match="more than one has parts assigned"):
        storage_svc.merge_cells(
            container_id=container.id,
            labels=["A0", "A1"],
        )


def test_unmerge_cell(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box U", rows=2, cols=2)

    merged = storage_svc.merge_cells(
        container_id=container.id,
        labels=["A0", "A1"],
    )

    new_slots = storage_svc.unmerge_cell(
        container_id=container.id,
        slot_id=merged.id,
    )

    assert len(new_slots) == 2
    labels = sorted(s.label for s in new_slots)
    assert labels == ["A0", "A1"]
    for s in new_slots:
        assert s.metadata["cell_size"] == CellSize.SMALL.value
        assert s.metadata["cell_length"] == CellLength.SHORT.value


def test_toggle_cell_properties(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box T", rows=2, cols=2)

    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    updated = storage_svc.update_cell_properties(
        slot_id=a0.id,
        cell_size=CellSize.LARGE.value,
    )
    assert updated.metadata["cell_size"] == CellSize.LARGE.value
    assert updated.metadata["cell_length"] == CellLength.SHORT.value  # unchanged

    updated2 = storage_svc.update_cell_properties(
        slot_id=a0.id,
        cell_length=CellLength.LONG.value,
    )
    assert updated2.metadata["cell_size"] == CellSize.LARGE.value  # persisted
    assert updated2.metadata["cell_length"] == CellLength.LONG.value


def test_update_slot_repository(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box R", rows=1, cols=1)

    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    a0.notes = "test note"
    updated = storage_repo.update_slot(a0)
    assert updated.notes == "test note"


def test_resize_grid_box_grow(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box G", rows=2, cols=2)

    assert len(storage_repo.list_slots_for_container(container.id)) == 4

    updated = storage_svc.resize_grid_box(
        container_id=container.id, new_rows=3, new_cols=3,
    )
    assert updated.metadata["rows"] == 3
    assert updated.metadata["cols"] == 3

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 9  # 3x3

    # New cells should exist
    c2 = storage_repo.get_slot_by_label(container.id, "C2")
    assert c2 is not None
    assert c2.metadata["cell_size"] == CellSize.SMALL.value

    # Original cells still present
    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    assert a0 is not None


def test_resize_grid_box_preserves_existing_blanks(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(
        name="Box Sparse",
        rows=2,
        cols=3,
        initial_cells=2,
    )

    storage_svc.resize_grid_box(
        container_id=container.id,
        new_rows=3,
        new_cols=4,
    )

    slots = storage_repo.list_slots_for_container(container.id)
    assert sorted(slot.label for slot in slots) == ["A0", "A1", "A3", "B3", "C0", "C1", "C2", "C3"]
    assert storage_repo.get_slot_by_label(container.id, "A2") is None
    assert storage_repo.get_slot_by_label(container.id, "B0") is None
    assert storage_repo.get_slot_by_label(container.id, "B2") is None
    assert storage_repo.get_slot_by_label(container.id, "A3") is not None
    assert storage_repo.get_slot_by_label(container.id, "B3") is not None
    assert storage_repo.get_slot_by_label(container.id, "C0") is not None


def test_resize_grid_box_shrink(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box Sh", rows=3, cols=3)

    updated = storage_svc.resize_grid_box(
        container_id=container.id, new_rows=2, new_cols=2,
    )
    assert updated.metadata["rows"] == 2
    assert updated.metadata["cols"] == 2

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 4  # 2x2

    # Removed cells should be gone
    assert storage_repo.get_slot_by_label(container.id, "C0") is None
    assert storage_repo.get_slot_by_label(container.id, "A2") is None


def test_resize_blocked_by_stock(services) -> None:
    storage_svc, inventory_svc, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box RS", rows=2, cols=2)

    # Put stock in B1 (row 1, col 1) — will be removed if shrinking to 1x1
    b1 = storage_repo.get_slot_by_label(container.id, "B1")
    inventory_svc.upsert_part(name="cap", category="Caps", qty=3, slot_id=b1.id)

    with pytest.raises(ValueError, match="parts assigned"):
        storage_svc.resize_grid_box(
            container_id=container.id, new_rows=1, new_cols=1,
        )


def test_resize_blocked_by_merged_span(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box RM", rows=3, cols=3)

    # Merge B1-B2 (spans into col 2)
    storage_svc.merge_cells(
        container_id=container.id,
        labels=["B1", "B2"],
    )

    # Shrinking to 2 cols should fail because merged cell B1-B2 spans into col 2
    with pytest.raises(ValueError, match="spans across"):
        storage_svc.resize_grid_box(
            container_id=container.id, new_rows=3, new_cols=2,
        )


def test_merge_resize_then_unmerge(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box MRU", rows=2, cols=2)

    # Merge A0+A1
    merged = storage_svc.merge_cells(
        container_id=container.id,
        labels=["A0", "A1"],
    )

    # Grow the box — should not create duplicate A0/A1 cells
    storage_svc.resize_grid_box(
        container_id=container.id, new_rows=3, new_cols=2,
    )
    slots = storage_repo.list_slots_for_container(container.id)
    # 2x2=4, minus 2 merged +1 merged =3, plus 2 new row = 5
    assert len(slots) == 5

    # Unmerge should succeed without UNIQUE constraint error
    new_slots = storage_svc.unmerge_cell(
        container_id=container.id,
        slot_id=merged.id,
    )
    assert len(new_slots) == 2
    assert sorted(s.label for s in new_slots) == ["A0", "A1"]


def test_delete_container_removes_container_and_slots(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box Del", rows=2, cols=2)

    assert len(storage_repo.list_slots_for_container(container.id)) == 4

    storage_svc.delete_container(container.id)

    assert storage_repo.get_container(container.id) is None
    assert storage_repo.list_slots_for_container(container.id) == []


def test_delete_container_unassigns_parts(services) -> None:
    storage_svc, inventory_svc, storage_repo, db = services
    container = storage_svc.configure_grid_box(name="Box DS", rows=2, cols=2)

    a0 = storage_repo.get_slot_by_label(container.id, "A0")
    part = inventory_svc.upsert_part(name="cap", category="Caps", qty=1, slot_id=a0.id)

    storage_svc.delete_container(container.id)

    # Container should be gone
    assert storage_repo.get_container(container.id) is None

    # Part should still exist but with no slot assignment
    from eurorack_inventory.repositories.parts import PartRepository
    part_repo = PartRepository(db)
    updated = part_repo.get_part_by_id(part.id)
    assert updated is not None
    assert updated.slot_id is None
    assert updated.qty == 1


def test_delete_container_unknown_id(services) -> None:
    storage_svc, _, _, _ = services
    with pytest.raises(ValueError, match="Unknown container_id"):
        storage_svc.delete_container(99999)


def test_delete_binder_removes_container_and_cards(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Del", num_cards=3)

    assert len(storage_repo.list_slots_for_container(container.id)) == 3

    storage_svc.delete_container(container.id)

    assert storage_repo.get_container(container.id) is None
    assert storage_repo.list_slots_for_container(container.id) == []


def test_resize_binder_grow(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder G", num_cards=3)

    assert len(storage_repo.list_slots_for_container(container.id)) == 3

    storage_svc.resize_binder(container_id=container.id, new_num_cards=5)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 5
    assert slots[-1].label == "Card 5"
    assert slots[-1].metadata["bag_count"] == 4  # default


def test_resize_binder_shrink(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder S", num_cards=5)

    storage_svc.resize_binder(container_id=container.id, new_num_cards=2)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 2
    labels = [s.label for s in slots]
    assert "Card 1" in labels
    assert "Card 2" in labels
    assert "Card 3" not in labels


def test_resize_binder_shrink_blocked_by_stock(services) -> None:
    storage_svc, inventory_svc, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder BS", num_cards=3)

    card3 = storage_repo.get_slot_by_label(container.id, "Card 3")
    inventory_svc.upsert_part(name="chip", category="ICs", qty=2, slot_id=card3.id)

    with pytest.raises(ValueError, match="parts assigned"):
        storage_svc.resize_binder(container_id=container.id, new_num_cards=1)


def test_update_card_bag_count(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Bags", num_cards=2)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    assert card1.metadata["bag_count"] == 4  # default

    updated = storage_svc.update_card_bag_count(slot_id=card1.id, bag_count=8)
    assert updated.metadata["bag_count"] == 8

    # Card 2 unchanged
    card2 = storage_repo.get_slot_by_label(container.id, "Card 2")
    assert card2.metadata["bag_count"] == 4


def test_update_card_bag_count_invalid(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder BI", num_cards=1)
    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")

    with pytest.raises(ValueError, match="at least 1"):
        storage_svc.update_card_bag_count(slot_id=card1.id, bag_count=0)


def test_update_card_bag_count_wrong_slot_type(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box BC", rows=1, cols=1)
    a0 = storage_repo.get_slot_by_label(container.id, "A0")

    with pytest.raises(ValueError, match="card slots"):
        storage_svc.update_card_bag_count(slot_id=a0.id, bag_count=3)


def test_delete_slot_repository(services) -> None:
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_grid_box(name="Box D", rows=1, cols=2)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 2

    storage_repo.delete_slot(slots[0].id)
    remaining = storage_repo.list_slots_for_container(container.id)
    assert len(remaining) == 1


# ------------------------------------------------------------------ Binder tests


def test_binder_card_ordinals(services) -> None:
    """Cards should have sequential ordinals matching their card number."""
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Ord", num_cards=5)

    slots = storage_repo.list_slots_for_container(container.id)
    for i, slot in enumerate(slots, 1):
        assert slot.ordinal == i
        assert slot.label == f"Card {i}"


def test_binder_resize_preserves_existing_cards(services) -> None:
    """Growing a binder should not alter existing cards."""
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Pres", num_cards=3, bags_per_card=6)

    storage_svc.resize_binder(container_id=container.id, new_num_cards=5)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 5
    # Original cards should still have bag_count=6
    for slot in slots[:3]:
        assert slot.metadata["bag_count"] == 6
    # New cards get the container's default bags_per_card
    for slot in slots[3:]:
        assert slot.metadata["bag_count"] == 6


def test_binder_resize_to_zero_fails(services) -> None:
    storage_svc, _, _, _ = services
    container = storage_svc.configure_binder(name="Binder Zero", num_cards=3)

    with pytest.raises(ValueError, match="at least 1"):
        storage_svc.resize_binder(container_id=container.id, new_num_cards=0)


def test_binder_resize_same_size_noop(services) -> None:
    """Resizing to the same size should not change anything."""
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Same", num_cards=3)

    storage_svc.resize_binder(container_id=container.id, new_num_cards=3)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 3


def test_delete_binder_unassigns_parts(services) -> None:
    """Deleting a binder with assigned parts should unassign them."""
    storage_svc, inventory_svc, storage_repo, db = services
    container = storage_svc.configure_binder(name="Binder DU", num_cards=2)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    part = inventory_svc.upsert_part(name="TL072", category="ICs", qty=3, slot_id=card1.id)

    storage_svc.delete_container(container.id)

    assert storage_repo.get_container(container.id) is None

    from eurorack_inventory.repositories.parts import PartRepository
    part_repo = PartRepository(db)
    updated = part_repo.get_part_by_id(part.id)
    assert updated is not None
    assert updated.slot_id is None
    assert updated.qty == 3


def test_update_bag_count_unassigns_overflow(services) -> None:
    """Reducing bag count below occupancy should auto-unassign excess parts."""
    storage_svc, inventory_svc, storage_repo, db = services
    container = storage_svc.configure_binder(name="Binder OF", num_cards=1, bags_per_card=4)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    p1 = inventory_svc.upsert_part(name="IC 1", category="ICs", qty=1, slot_id=card1.id)
    p2 = inventory_svc.upsert_part(name="IC 2", category="ICs", qty=1, slot_id=card1.id)
    p3 = inventory_svc.upsert_part(name="IC 3", category="ICs", qty=1, slot_id=card1.id)

    # Reduce bag count to 1 — should unassign 2 parts
    storage_svc.update_card_bag_count(slot_id=card1.id, bag_count=1)

    from eurorack_inventory.repositories.parts import PartRepository
    part_repo = PartRepository(db)
    still_assigned = [
        p for p in [part_repo.get_part_by_id(p1.id),
                     part_repo.get_part_by_id(p2.id),
                     part_repo.get_part_by_id(p3.id)]
        if p.slot_id == card1.id
    ]
    unassigned = [
        p for p in [part_repo.get_part_by_id(p1.id),
                     part_repo.get_part_by_id(p2.id),
                     part_repo.get_part_by_id(p3.id)]
        if p.slot_id is None
    ]
    assert len(still_assigned) == 1
    assert len(unassigned) == 2


def test_update_bag_count_no_unassign_when_within_limit(services) -> None:
    """Reducing bag count but still above occupancy should not unassign."""
    storage_svc, inventory_svc, storage_repo, db = services
    container = storage_svc.configure_binder(name="Binder NF", num_cards=1, bags_per_card=6)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    p1 = inventory_svc.upsert_part(name="IC 1", category="ICs", qty=1, slot_id=card1.id)
    p2 = inventory_svc.upsert_part(name="IC 2", category="ICs", qty=1, slot_id=card1.id)

    # Reduce to 4 — still above 2 parts, nothing should change
    storage_svc.update_card_bag_count(slot_id=card1.id, bag_count=4)

    from eurorack_inventory.repositories.parts import PartRepository
    part_repo = PartRepository(db)
    assert part_repo.get_part_by_id(p1.id).slot_id == card1.id
    assert part_repo.get_part_by_id(p2.id).slot_id == card1.id


def test_clone_binder(services) -> None:
    """Cloning a binder should copy structure but not parts."""
    storage_svc, inventory_svc, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Cl", num_cards=3, bags_per_card=5)

    # Assign a part to card 1
    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    inventory_svc.upsert_part(name="IC 1", category="ICs", qty=1, slot_id=card1.id)

    clone = storage_svc.clone_container(container.id, "Binder Cl Copy")

    assert clone.container_type == ContainerType.BINDER.value
    assert clone.metadata["bags_per_card"] == 5

    clone_slots = storage_repo.list_slots_for_container(clone.id)
    assert len(clone_slots) == 3
    for slot in clone_slots:
        assert slot.slot_type == SlotType.CARD.value
        assert slot.metadata["bag_count"] == 5


def test_binder_resize_shrink_preserves_lower_cards(services) -> None:
    """Shrinking should only remove higher-numbered cards."""
    storage_svc, inventory_svc, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder Sh", num_cards=5)

    # Assign part to card 2 — should survive shrink to 3
    card2 = storage_repo.get_slot_by_label(container.id, "Card 2")
    inventory_svc.upsert_part(name="IC 1", category="ICs", qty=1, slot_id=card2.id)

    storage_svc.resize_binder(container_id=container.id, new_num_cards=3)

    slots = storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 3
    labels = [s.label for s in slots]
    assert "Card 2" in labels
    assert "Card 4" not in labels
    assert "Card 5" not in labels


def test_binder_individual_card_bag_counts(services) -> None:
    """Each card can have its own bag count independent of others."""
    storage_svc, _, storage_repo, _ = services
    container = storage_svc.configure_binder(name="Binder IC", num_cards=3, bags_per_card=4)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    card2 = storage_repo.get_slot_by_label(container.id, "Card 2")
    card3 = storage_repo.get_slot_by_label(container.id, "Card 3")

    storage_svc.update_card_bag_count(slot_id=card1.id, bag_count=2)
    storage_svc.update_card_bag_count(slot_id=card3.id, bag_count=10)

    card1 = storage_repo.get_slot_by_label(container.id, "Card 1")
    card2 = storage_repo.get_slot_by_label(container.id, "Card 2")
    card3 = storage_repo.get_slot_by_label(container.id, "Card 3")

    assert card1.metadata["bag_count"] == 2
    assert card2.metadata["bag_count"] == 4  # unchanged
    assert card3.metadata["bag_count"] == 10
