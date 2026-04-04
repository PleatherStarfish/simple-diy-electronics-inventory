from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from eurorack_inventory.app import build_app_context
from eurorack_inventory.ui import inventory_screen as inventory_screen_module
from eurorack_inventory.ui.inventory_screen import InventoryScreen


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def ui_context(tmp_path: Path):
    context = build_app_context(tmp_path / "app.db")
    yield context
    context.db.close()


def test_find_in_storage_jumps_directly_for_single_location(qapp, ui_context) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slot = ui_context.storage_repo.get_slot_by_label(container.id, "A0")
    assert slot is not None
    part = ui_context.inventory_service.upsert_part(
        name="100R 0805",
        category="Resistors",
        qty=10,
        slot_id=slot.id,
    )

    screen = InventoryScreen(ui_context)
    screen.show()
    qapp.processEvents()
    screen.refresh_inventory()
    screen._load_detail(part.id)

    requested: list[int] = []
    screen.find_in_storage_requested.connect(requested.append)

    screen._find_in_storage()

    assert requested == [slot.id]
    screen.close()


def test_find_in_storage_uses_menu_for_split_locations(qapp, ui_context, monkeypatch) -> None:
    container = ui_context.storage_service.configure_grid_box(name="Box 1", rows=1, cols=2)
    slot_a = ui_context.storage_repo.get_slot_by_label(container.id, "A0")
    slot_b = ui_context.storage_repo.get_slot_by_label(container.id, "A1")
    assert slot_a is not None
    assert slot_b is not None

    part = ui_context.inventory_service.upsert_part(
        name="100R 0805",
        category="Resistors",
        qty=10,
    )
    ui_context.inventory_service.replace_part_locations(part.id, [(slot_a.id, 7), (slot_b.id, 3)])

    screen = InventoryScreen(ui_context)
    screen.show()
    qapp.processEvents()
    screen.refresh_inventory()
    screen._load_detail(part.id)

    seen_actions: list[str] = []

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text
            self._data = None

        def text(self) -> str:
            return self._text

        def setData(self, value) -> None:
            self._data = value

        def data(self):
            return self._data

    class _FakeMenu:
        def __init__(self, _parent=None) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str) -> _FakeAction:
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def exec(self, *_args, **_kwargs):
            seen_actions.extend(action.text() for action in self._actions)
            return self._actions[1]

    monkeypatch.setattr(inventory_screen_module, "QMenu", _FakeMenu)

    requested: list[int] = []
    screen.find_in_storage_requested.connect(requested.append)

    screen._find_in_storage()

    assert seen_actions == ["Box 1 / A0 (7)", "Box 1 / A1 (3)"]
    assert requested == [slot_b.id]
    screen.close()


def test_double_clicking_locations_column_opens_locations_editor(qapp, ui_context, monkeypatch) -> None:
    part = ui_context.inventory_service.upsert_part(
        name="TL072",
        category="ICs",
        qty=4,
    )

    screen = InventoryScreen(ui_context)
    screen.show()
    qapp.processEvents()
    screen.refresh_inventory()

    called: list[tuple[int, int]] = []

    def fake_open_locations_editor(part_id: int, index=None) -> None:
        assert index is not None
        called.append((part_id, index.column()))

    monkeypatch.setattr(screen, "_open_locations_editor", fake_open_locations_editor)

    index = screen.inventory_model.index(0, 4)
    screen._on_inventory_double_clicked(index)

    assert called == [(part.id, 4)]
    screen.close()
