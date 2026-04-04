from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.domain.models import PartLocation


class _LocationRow(QWidget):
    changed = Signal()
    remove_requested = Signal(QWidget)

    def __init__(
        self,
        *,
        slot_choices: list[tuple[int, str]],
        slot_id: int | None = None,
        qty: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._slot_choices = slot_choices

        self.slot_combo = QComboBox()
        self.slot_combo.setEditable(False)
        self.slot_combo.addItem("Select a location", None)
        for choice_id, label in slot_choices:
            self.slot_combo.addItem(label, choice_id)
        if slot_id is not None:
            index = self.slot_combo.findData(slot_id)
            if index >= 0:
                self.slot_combo.setCurrentIndex(index)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 999_999)
        self.qty_spin.setValue(qty)

        self.remove_btn = QPushButton("Remove")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slot_combo, 1)
        layout.addWidget(self.qty_spin)
        layout.addWidget(self.remove_btn)

        self.slot_combo.currentIndexChanged.connect(self.changed)
        self.qty_spin.valueChanged.connect(self.changed)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))

    def values(self) -> tuple[int | None, int]:
        return self.slot_combo.currentData(), self.qty_spin.value()


class PartLocationsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        part_name: str,
        total_qty: int,
        slot_choices: list[tuple[int, str]],
        initial_locations: list[PartLocation] | list[tuple[int, int]] | None = None,
        default_slot_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Locations for {part_name}")
        self.setMinimumWidth(560)

        self._total_qty = total_qty
        self._slot_choices = slot_choices
        self._rows: list[_LocationRow] = []

        self._summary_label = QLabel("")
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch()

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(self._rows_container)

        self._add_btn = QPushButton("Add Location")
        self._add_btn.clicked.connect(self._add_empty_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Total quantity: {total_qty}"))
        layout.addWidget(self._summary_label)
        layout.addWidget(scroller, 1)
        layout.addWidget(self._add_btn)
        layout.addWidget(buttons)

        initial_pairs: list[tuple[int, int]] = []
        if initial_locations:
            if isinstance(initial_locations[0], PartLocation):  # type: ignore[index]
                initial_pairs = [
                    (location.slot_id, location.qty)
                    for location in initial_locations  # type: ignore[union-attr]
                ]
            else:
                initial_pairs = list(initial_locations)  # type: ignore[arg-type]

        if not initial_pairs and total_qty > 0 and default_slot_id is not None:
            initial_pairs = [(default_slot_id, total_qty)]

        if initial_pairs:
            for slot_id, qty in initial_pairs:
                self._add_row(slot_id=slot_id, qty=qty)
        else:
            self._update_summary()

    def get_locations(self) -> list[tuple[int, int]]:
        merged: dict[int, int] = {}
        ordered_slot_ids: list[int] = []
        for row in self._rows:
            slot_id, qty = row.values()
            if slot_id is None or qty <= 0:
                continue
            if slot_id not in merged:
                ordered_slot_ids.append(slot_id)
                merged[slot_id] = 0
            merged[slot_id] += qty
        return [(slot_id, merged[slot_id]) for slot_id in ordered_slot_ids]

    def _add_empty_row(self) -> None:
        self._add_row()

    def _add_row(self, *, slot_id: int | None = None, qty: int = 0) -> None:
        row = _LocationRow(slot_choices=self._slot_choices, slot_id=slot_id, qty=qty, parent=self)
        row.changed.connect(self._update_summary)
        row.remove_requested.connect(self._remove_row)
        self._rows.append(row)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._update_summary()

    def _remove_row(self, row: QWidget) -> None:
        self._rows = [candidate for candidate in self._rows if candidate is not row]
        row.setParent(None)
        row.deleteLater()
        self._update_summary()

    def _update_summary(self) -> None:
        allocated = sum(qty for _slot_id, qty in self.get_locations())
        remaining = self._total_qty - allocated
        if remaining == 0:
            self._summary_label.setText(f"Allocated {allocated} / {self._total_qty}")
        elif remaining > 0:
            self._summary_label.setText(
                f"Allocated {allocated} / {self._total_qty} ({remaining} unallocated)"
            )
        else:
            self._summary_label.setText(
                f"Allocated {allocated} / {self._total_qty} ({-remaining} over)"
            )
        self._ok_btn.setEnabled(remaining == 0)

    def _validate_and_accept(self) -> None:
        for row in self._rows:
            slot_id, qty = row.values()
            if qty <= 0:
                continue
            if slot_id is None:
                QMessageBox.warning(self, "Validation", "Choose a location for each quantity row.")
                return

        locations = self.get_locations()
        allocated = sum(qty for _slot_id, qty in locations)
        if allocated != self._total_qty:
            QMessageBox.warning(
                self,
                "Validation",
                f"Location quantities must sum to {self._total_qty}. Currently allocated: {allocated}.",
            )
            return
        self.accept()
