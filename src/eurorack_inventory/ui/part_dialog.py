from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part, StorageSlot

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
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Part" if part else "New Part")
        self.setMinimumWidth(450)

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
        self.location_combo = QComboBox()
        self.storage_type_combo = QComboBox()
        self.storage_type_combo.addItem("(auto)", None)
        for sc in StorageClass:
            self.storage_type_combo.addItem(_STORAGE_CLASS_LABELS[sc], sc.value)
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)

        # Populate location combo, coloring occupied slots
        occupied = occupied_slot_ids or set()
        self.location_combo.addItem("(none)", None)
        model = self.location_combo.model()
        for slot_id, label in (slots or []):
            self.location_combo.addItem(label, slot_id)
            if slot_id in occupied:
                item = model.item(self.location_combo.count() - 1)
                item.setForeground(QBrush(QColor(180, 130, 0)))

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
            if part.slot_id is not None:
                idx = self.location_combo.findData(part.slot_id)
                if idx >= 0:
                    self.location_combo.setCurrentIndex(idx)

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
        form.addRow("Location", self.location_combo)
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
        self.accept()

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
            "slot_id": self.location_combo.currentData(),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
