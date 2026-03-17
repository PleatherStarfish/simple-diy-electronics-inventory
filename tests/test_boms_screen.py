from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from eurorack_inventory.app import build_app_context
from eurorack_inventory.ui.boms_screen import BomsScreen


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def ui_context(tmp_path: Path):
    context = build_app_context(tmp_path / "app.db")
    yield context
    context.db.close()


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_run_import_selects_new_source_and_populates_tables(qapp, ui_context, tmp_path, monkeypatch) -> None:
    existing_csv = tmp_path / "aaa.csv"
    _write_csv(
        existing_csv,
        [{"_module": "AAA", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""}],
    )
    ui_context.bom_service.import_csv(existing_csv)

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    screen = BomsScreen(ui_context)
    screen.show()
    qapp.processEvents()

    assert screen.current_source_id is not None
    initial_source = ui_context.bom_repo.get_bom_source(screen.current_source_id)
    assert initial_source is not None
    assert initial_source.module_name == "AAA"

    imported_csv = tmp_path / "zzz.csv"
    _write_csv(
        imported_csv,
        [{"_module": "ZZZ", "VALUE": "TL072", "QUANTITY": "2", "DETAILS": "SOIC"}],
    )

    screen._run_import([imported_csv], "csv")
    qapp.processEvents()

    selected_source = ui_context.bom_repo.get_bom_source(screen.current_source_id)
    assert selected_source is not None
    assert selected_source.module_name == "ZZZ"
    assert screen.raw_model.rowCount() == 1
    assert screen.norm_model.rowCount() == 1

    current_index = screen.source_list.currentIndex()
    assert current_index.isValid()
    current_source = screen.source_model.source_at(current_index.row())
    assert current_source is not None
    assert current_source.id == selected_source.id

    screen.close()


def test_import_pdf_shows_runtime_diagnostic_warning(qapp, ui_context, monkeypatch) -> None:
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "eurorack_inventory.ui.boms_screen.get_pdf_runtime_status",
        lambda: type("Status", (), {"available": False})(),
    )
    monkeypatch.setattr(
        "eurorack_inventory.ui.boms_screen.format_pdf_runtime_error",
        lambda _status: "Java diagnostic details",
    )

    def fake_warning(_parent, title, text):
        captured["title"] = title
        captured["text"] = text
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    screen = BomsScreen(ui_context)
    screen._import_pdf()

    assert captured["title"] == "PDF Import Unavailable"
    assert captured["text"] == "Java diagnostic details"

    screen.close()
