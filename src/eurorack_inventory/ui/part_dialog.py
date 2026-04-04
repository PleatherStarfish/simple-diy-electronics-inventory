from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part, PartLocation
from eurorack_inventory.ui.part_locations_dialog import PartLocationsDialog

_STORAGE_CLASS_LABELS = {
    StorageClass.SMALL_SHORT_CELL: "Small / Short Cell",
    StorageClass.LARGE_CELL: "Large Cell",
    StorageClass.LONG_CELL: "Long Cell",
    StorageClass.BINDER_CARD: "Binder Card",
}


class PartDialog(QDialog):
    """Dialog for creating or editing a part."""

    def __init__(
        self,
        parent=None,
        *,
        part: Part | None = None,
        slots: list[tuple[int, str]] | None = None,
        occupied_slot_ids: set[int] | None = None,
        categories: list[str] | None = None,
        packages: list[str] | None = None,
        locations: list[PartLocation] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Part" if part else "New Part")
        self.setMinimumWidth(450)
        self._slot_choices = slots or []
        self._occupied_slot_ids = occupied_slot_ids or set()
        self._default_unassigned_slot_id = next(
            (
                slot_id
                for slot_id, label in self._slot_choices
                if label == "Unassigned / Main"
            ),
            None,
        )
        self._locations: list[tuple[int, int]] = []

        self.name_edit = QLineEdit()
        self.category_combo = self._make_searchable_combo(categories or [])
        self.manufacturer_edit = QLineEdit()
        self.mpn_edit = QLineEdit()
        self.supplier_name_edit = QLineEdit()
        self.supplier_sku_edit = QLineEdit()
        self.purchase_url_edit = QLineEdit()
        self.package_combo = self._make_searchable_combo(packages or [])
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 999_999)
        self.locations_summary = QLabel("")
        self.locations_summary.setWordWrap(True)
        self.manage_locations_btn = QPushButton("Manage...")
        self.manage_locations_btn.clicked.connect(self._manage_locations)
        self.storage_type_combo = QComboBox()
        self.storage_type_combo.addItem("(auto)", None)
        for sc in StorageClass:
            self.storage_type_combo.addItem(_STORAGE_CLASS_LABELS[sc], sc.value)
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)

        # Pre-fill for edit mode
        if part is not None:
            self.name_edit.setText(part.name)
            self.category_combo.setCurrentText(part.category or "")
            self.manufacturer_edit.setText(part.manufacturer or "")
            self.mpn_edit.setText(part.mpn or "")
            self.supplier_name_edit.setText(part.supplier_name or "")
            self.supplier_sku_edit.setText(part.supplier_sku or "")
            self.purchase_url_edit.setText(part.purchase_url or "")
            self.package_combo.setCurrentText(part.default_package or "")
            self.qty_spin.setValue(part.qty)
            self.notes_edit.setPlainText(part.notes or "")
            if part.storage_class_override:
                idx = self.storage_type_combo.findData(part.storage_class_override)
                if idx >= 0:
                    self.storage_type_combo.setCurrentIndex(idx)
        if locations:
            self._locations = [(location.slot_id, location.qty) for location in locations]
        self._refresh_locations_summary()

        form = QFormLayout()
        form.addRow("Name *", self.name_edit)
        form.addRow("Category", self.category_combo)
        form.addRow("Manufacturer", self.manufacturer_edit)
        form.addRow("MPN", self.mpn_edit)
        form.addRow("Supplier", self.supplier_name_edit)
        form.addRow("Supplier SKU", self.supplier_sku_edit)
        form.addRow("Purchase URL", self.purchase_url_edit)
        form.addRow("Package", self.package_combo)
        form.addRow("Quantity", self.qty_spin)
        form.addRow("Storage Type", self.storage_type_combo)
        locations_row = QHBoxLayout()
        locations_row.addWidget(self.locations_summary, 1)
        locations_row.addWidget(self.manage_locations_btn)
        form.addRow("Locations", locations_row)
        form.addRow("Notes", self.notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _make_searchable_combo(items: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItem("")
        combo.addItems(items)
        combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        return combo

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        if self._locations:
            allocated = sum(qty for _slot_id, qty in self._locations)
            if allocated != self.qty_spin.value():
                QMessageBox.warning(
                    self,
                    "Validation",
                    f"Location quantities must sum to {self.qty_spin.value()}. Currently allocated: {allocated}.",
                )
                return
        self.accept()

    def _manage_locations(self) -> None:
        dialog = PartLocationsDialog(
            self,
            part_name=self.name_edit.text().strip() or "New Part",
            total_qty=self.qty_spin.value(),
            slot_choices=self._slot_choices,
            occupied_slot_ids=self._occupied_slot_ids,
            initial_locations=self._locations,
            default_slot_id=self._default_unassigned_slot_id,
        )
        if dialog.exec() != PartLocationsDialog.DialogCode.Accepted:
            return
        self._locations = dialog.get_locations()
        self._refresh_locations_summary()

    def _refresh_locations_summary(self) -> None:
        if not self._locations:
            self.locations_summary.setText("(auto: Unassigned)")
            return

        label_map = dict(self._slot_choices)
        lines = [
            f"{label_map.get(slot_id, f'slot #{slot_id}')} ({qty})"
            for slot_id, qty in self._locations
        ]
        self.locations_summary.setText("; ".join(lines))

    def get_fields(self) -> dict:
        """Return the field values entered by the user."""
        return {
            "name": self.name_edit.text().strip(),
            "category": self.category_combo.currentText().strip() or None,
            "manufacturer": self.manufacturer_edit.text().strip() or None,
            "mpn": self.mpn_edit.text().strip() or None,
            "supplier_name": self.supplier_name_edit.text().strip() or None,
            "supplier_sku": self.supplier_sku_edit.text().strip() or None,
            "purchase_url": self.purchase_url_edit.text().strip() or None,
            "default_package": self.package_combo.currentText().strip() or None,
            "qty": self.qty_spin.value(),
            "storage_class_override": self.storage_type_combo.currentData(),
            "locations": list(self._locations),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
