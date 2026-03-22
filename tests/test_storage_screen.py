from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from eurorack_inventory.app import build_app_context
from eurorack_inventory.domain.enums import CellLength, CellSize
from eurorack_inventory.services.assignment import AssignmentScope
from eurorack_inventory.ui.storage_screen import (
    DeleteContainerDialog,
    StorageScreen,
    _GRID_CELL_MIN_HEIGHT,
    _GRID_CELL_SELECTION_ROLE,
)


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def ui_context(tmp_path: Path):
    context = build_app_context(tmp_path / "app.db")
    yield context
    context.db.close()


def _cell_center(screen: StorageScreen, row: int, col: int) -> QPoint:
    return QPoint(
        screen.grid_table.columnViewportPosition(col) + screen.grid_table.columnWidth(col) // 2,
        screen.grid_table.rowViewportPosition(row) + screen.grid_table.rowHeight(row) // 2,
    )


def test_grid_initial_render_paints_slot_text_without_widgets(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Grid", rows=2, cols=2)
    a0 = ui_context.storage_repo.get_slot_by_label(container.id, "A0")
    assert a0 is not None

    ui_context.storage_service.update_cell_properties(
        slot_id=a0.id,
        cell_size=CellSize.LARGE.value,
        cell_length=CellLength.LONG.value,
    )

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)

    item = screen.grid_table.item(0, 0)
    assert item is not None
    assert screen.grid_table.cellWidget(0, 0) is None
    assert "A0" in item.text()
    assert "L / long" in item.text()
    assert not bool(item.data(_GRID_CELL_SELECTION_ROLE))
    assert screen.grid_table.verticalHeader().minimumSectionSize() >= _GRID_CELL_MIN_HEIGHT

    screen.close()


def test_grid_selection_supports_multi_select_and_merge(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Merge Grid", rows=2, cols=2)

    screen = StorageScreen(ui_context)
    screen.resize(900, 600)
    screen.show()
    qapp.processEvents()
    screen.load_container(container.id)
    qapp.processEvents()

    assert screen._toggle_selection_at_grid_pos(_cell_center(screen, 0, 0))
    assert screen._toggle_selection_at_grid_pos(_cell_center(screen, 0, 1))

    selected = screen._get_selected_slots()
    assert [label for label, _slot in selected] == ["A0", "A1"]

    screen._merge_selected()

    assert ui_context.storage_repo.get_slot_by_label(container.id, "A0-A1") is not None
    assert screen.grid_table.columnSpan(0, 0) == 2
    assert screen._get_selected_slots() == []

    screen.close()


def test_new_grid_box_all_cells_clickable_immediately(qapp, ui_context) -> None:
    """Regression: newly created grid boxes must have every cell clickable without resize."""
    container = ui_context.storage_service.configure_grid_box(name="Fresh Grid", rows=6, cols=6)

    screen = StorageScreen(ui_context)
    screen.resize(900, 600)
    screen.show()
    qapp.processEvents()
    screen.load_container(container.id)
    qapp.processEvents()

    # Every cell should have a backing slot in _slot_map
    for row in range(6):
        for col in range(6):
            assert (row, col) in screen._slot_map, f"Cell ({row},{col}) has no backing slot"

    # Every cell should be clickable (toggle returns True)
    for row in range(6):
        for col in range(6):
            pos = _cell_center(screen, row, col)
            slot = screen._slot_at_grid_pos(pos)
            assert slot is not None, f"Cell ({row},{col}) not clickable at pos {pos}"

    screen.close()


def test_new_grid_box_supports_merge_unmerge_without_resize(qapp, ui_context) -> None:
    """Regression: merge/unmerge must work on a freshly created grid box."""
    container = ui_context.storage_service.configure_grid_box(name="MU Grid", rows=3, cols=3)

    screen = StorageScreen(ui_context)
    screen.resize(900, 600)
    screen.show()
    qapp.processEvents()
    screen.load_container(container.id)
    qapp.processEvents()

    # Select A0 and A1, then merge
    assert screen._toggle_selection_at_grid_pos(_cell_center(screen, 0, 0))
    assert screen._toggle_selection_at_grid_pos(_cell_center(screen, 0, 1))
    screen._merge_selected()

    merged = ui_context.storage_repo.get_slot_by_label(container.id, "A0-A1")
    assert merged is not None
    assert screen.grid_table.columnSpan(0, 0) == 2

    # Unmerge
    screen._clear_selection()
    assert screen._toggle_selection_at_grid_pos(_cell_center(screen, 0, 0))
    screen._unmerge_selected()

    assert ui_context.storage_repo.get_slot_by_label(container.id, "A0") is not None
    assert ui_context.storage_repo.get_slot_by_label(container.id, "A1") is not None
    assert ui_context.storage_repo.get_slot_by_label(container.id, "A0-A1") is None

    screen.close()


def test_new_grid_box_context_menu_works(qapp, ui_context) -> None:
    """Regression: context menu property changes work on freshly created grid box."""
    container = ui_context.storage_service.configure_grid_box(name="Ctx Grid", rows=2, cols=2)

    screen = StorageScreen(ui_context)
    screen.resize(900, 600)
    screen.show()
    qapp.processEvents()
    screen.load_container(container.id)
    qapp.processEvents()

    # Verify context menu target resolves
    pos = _cell_center(screen, 0, 0)
    slot = screen._slot_at_grid_pos(pos)
    assert slot is not None

    # Change property via service (simulating context menu action)
    ui_context.storage_service.update_cell_properties(
        slot_id=slot.id,
        cell_size=CellSize.LARGE.value,
    )
    updated = ui_context.storage_repo.get_slot(slot.id)
    assert updated.metadata["cell_size"] == CellSize.LARGE.value

    screen.close()


def test_refresh_reloads_current_container_after_assignment(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Refresh Grid", rows=2, cols=2)
    ui_context.inventory_service.upsert_part(name="100R 0805", category="Resistors", qty=10)

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)

    before = screen.grid_table.item(0, 0)
    assert before is not None
    assert "100R 0805" not in before.text()

    ui_context.assignment_service.assign("incremental", AssignmentScope())
    screen.refresh()

    after = screen.grid_table.item(0, 0)
    assert after is not None
    assert "100R 0805" in after.text()

    screen.close()


def test_selection_and_hit_testing_work_inside_merged_region(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Lookup Grid", rows=2, cols=2)
    merged = ui_context.storage_service.merge_cells(
        container_id=container.id,
        labels=["A0", "A1"],
    )

    screen = StorageScreen(ui_context)
    screen.resize(900, 600)
    screen.show()
    qapp.processEvents()
    screen.load_container(container.id)
    qapp.processEvents()

    pos = _cell_center(screen, 0, 1)
    slot = screen._slot_at_grid_pos(pos)
    assert slot is not None
    assert slot.label == merged.label

    assert screen._toggle_selection_at_grid_pos(pos)
    selected = screen._get_selected_slots()
    assert [label for label, _slot in selected] == [merged.label]

    item = screen.grid_table.item(0, 0)
    assert item is not None
    assert bool(item.data(_GRID_CELL_SELECTION_ROLE))

    screen.close()


def test_delete_dialog_challenge_enables_button(qapp) -> None:
    dialog = DeleteContainerDialog("Test Box")
    ok_btn = dialog._ok_btn

    assert not ok_btn.isEnabled()

    # Wrong text keeps it disabled
    dialog._input.setText("WRONG")
    assert not ok_btn.isEnabled()

    # Correct challenge enables it
    dialog._input.setText(dialog.challenge)
    assert ok_btn.isEnabled()

    # Clearing disables it again
    dialog._input.setText("")
    assert not ok_btn.isEnabled()

    dialog.close()


def test_delete_container_via_screen(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Doomed", rows=2, cols=2)

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)
    assert screen.current_container_id == container.id
    assert screen.delete_container_btn.isEnabled()

    # Delete directly via the service (simulating accepted dialog)
    ui_context.storage_service.delete_container(container.id)
    screen.current_container_id = None
    screen.delete_container_btn.setEnabled(False)
    screen.refresh()

    assert screen.current_container_id is None or screen.current_container_id != container.id
    assert ui_context.storage_repo.get_container(container.id) is None

    screen.close()


def test_binder_renders_cards_as_visual_grid(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_binder(
        name="Binder UI", num_cards=3, bags_per_card=6,
    )

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)

    # 3 cards in a 2-column grid = 2 rows
    assert screen.grid_table.rowCount() == 2
    assert screen.grid_table.columnCount() == 2
    # Card 1 at (0,0), Card 2 at (0,1), Card 3 at (1,0)
    assert "Card 1" in screen.grid_table.item(0, 0).text()
    assert "(0/6)" in screen.grid_table.item(0, 0).text()
    assert "Card 2" in screen.grid_table.item(0, 1).text()
    assert "Card 3" in screen.grid_table.item(1, 0).text()
    assert screen.binder_cards_spin.value() == 3
    # Headers hidden for clean binder look
    assert not screen.grid_table.horizontalHeader().isVisible()
    assert not screen.grid_table.verticalHeader().isVisible()
    # Check visibility policy (not isVisible, which requires a visible parent)
    assert not screen.binder_resize_widget.isHidden()
    assert screen.resize_widget.isHidden()

    screen.close()


def test_binder_resize_via_screen(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_binder(
        name="Binder Resize", num_cards=2,
    )

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)
    # 2 cards = 1 row x 2 cols
    assert screen.grid_table.rowCount() == 1

    # Simulate resize to 4 cards
    screen.binder_cards_spin.setValue(4)
    screen._resize_binder()

    # 4 cards = 2 rows x 2 cols
    assert screen.grid_table.rowCount() == 2
    slots = ui_context.storage_repo.list_slots_for_container(container.id)
    assert len(slots) == 4

    screen.close()


def test_binder_card_bag_count_update_via_service(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_binder(
        name="Binder Bags UI", num_cards=2, bags_per_card=4,
    )

    screen = StorageScreen(ui_context)
    screen.load_container(container.id)

    # Update bag count on card 1 via service
    card1 = ui_context.storage_repo.get_slot_by_label(container.id, "Card 1")
    ui_context.storage_service.update_card_bag_count(slot_id=card1.id, bag_count=10)

    # Reload and verify display — Card 1 at (0,0), Card 2 at (0,1)
    screen.load_container(container.id)
    assert "(0/10)" in screen.grid_table.item(0, 0).text()
    assert "(0/4)" in screen.grid_table.item(0, 1).text()

    screen.close()


def test_unassigned_shows_all_unassigned_parts(qapp, ui_context) -> None:
    """Unassigned container should list parts on Unassigned/Main AND parts with NULL slot_id."""
    # Ensure the Unassigned container exists
    ui_context.storage_service.ensure_default_unassigned_slot()
    unassigned_container = ui_context.storage_repo.get_container_by_name("Unassigned")
    unassigned_slot = ui_context.storage_repo.get_slot_by_label(unassigned_container.id, "Main")

    # Create a part assigned to the Unassigned/Main slot
    p1 = ui_context.inventory_service.upsert_part(
        name="100R 0805", category="Resistors", qty=10, slot_id=unassigned_slot.id,
    )
    # Create a part with NULL slot_id (never assigned)
    p2 = ui_context.inventory_service.upsert_part(
        name="TL072", category="ICs", qty=5,
    )

    screen = StorageScreen(ui_context)
    screen.load_container(unassigned_container.id)

    # The grid table should list both parts as individual rows
    assert screen.grid_table.rowCount() == 2
    names = {screen.grid_table.item(r, 0).text() for r in range(screen.grid_table.rowCount())}
    assert "100R 0805" in names
    assert "TL072" in names

    # The slot table should also list both parts
    assert screen.slot_table.rowCount() == 2
    slot_names = {screen.slot_table.item(r, 0).text() for r in range(screen.slot_table.rowCount())}
    assert "100R 0805" in slot_names
    assert "TL072" in slot_names

    screen.close()
