from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from eurorack_inventory.domain.models import Part, StorageSlot


class PartDialog(QDialog):
    """Dialog for creating or editing a part."""

    def __init__(
        self,
        parent=None,
        *,
        part: Part | None = None,
        slots: list[tuple[int, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Part" if part else "New Part")
        self.setMinimumWidth(450)

        self.name_edit = QLineEdit()
        self.category_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.mpn_edit = QLineEdit()
        self.supplier_name_edit = QLineEdit()
        self.supplier_sku_edit = QLineEdit()
        self.purchase_url_edit = QLineEdit()
        self.package_edit = QLineEdit()
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 999_999)
        self.location_combo = QComboBox()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)

        # Populate location combo
        self.location_combo.addItem("(none)", None)
        for slot_id, label in (slots or []):
            self.location_combo.addItem(label, slot_id)

        # Pre-fill for edit mode
        if part is not None:
            self.name_edit.setText(part.name)
            self.category_edit.setText(part.category or "")
            self.manufacturer_edit.setText(part.manufacturer or "")
            self.mpn_edit.setText(part.mpn or "")
            self.supplier_name_edit.setText(part.supplier_name or "")
            self.supplier_sku_edit.setText(part.supplier_sku or "")
            self.purchase_url_edit.setText(part.purchase_url or "")
            self.package_edit.setText(part.default_package or "")
            self.qty_spin.setValue(part.qty)
            self.notes_edit.setPlainText(part.notes or "")
            if part.slot_id is not None:
                idx = self.location_combo.findData(part.slot_id)
                if idx >= 0:
                    self.location_combo.setCurrentIndex(idx)

        form = QFormLayout()
        form.addRow("Name *", self.name_edit)
        form.addRow("Category", self.category_edit)
        form.addRow("Manufacturer", self.manufacturer_edit)
        form.addRow("MPN", self.mpn_edit)
        form.addRow("Supplier", self.supplier_name_edit)
        form.addRow("Supplier SKU", self.supplier_sku_edit)
        form.addRow("Purchase URL", self.purchase_url_edit)
        form.addRow("Package", self.package_edit)
        form.addRow("Quantity", self.qty_spin)
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

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        self.accept()

    def get_fields(self) -> dict:
        """Return the field values entered by the user."""
        return {
            "name": self.name_edit.text().strip(),
            "category": self.category_edit.text().strip() or None,
            "manufacturer": self.manufacturer_edit.text().strip() or None,
            "mpn": self.mpn_edit.text().strip() or None,
            "supplier_name": self.supplier_name_edit.text().strip() or None,
            "supplier_sku": self.supplier_sku_edit.text().strip() or None,
            "purchase_url": self.purchase_url_edit.text().strip() or None,
            "default_package": self.package_edit.text().strip() or None,
            "qty": self.qty_spin.value(),
            "slot_id": self.location_combo.currentData(),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
