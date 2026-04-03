from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.services.common import normalize_text
from eurorack_inventory.ui.models import InventoryTableModel
from eurorack_inventory.ui.part_dialog import PartDialog


class _SearchableComboDelegate(QStyledItemDelegate):
    """Delegate that shows a searchable combo box for editing."""

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self._populate(combo, index)
        return combo

    def _populate(self, combo: QComboBox, index) -> None:
        raise NotImplementedError

    def setEditorData(self, editor, index):
        current = index.data(Qt.DisplayRole) or ""
        idx = editor.findText(current, Qt.MatchFlag.MatchExactly)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setEditText(current)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.EditRole)


class _CategoryDelegate(_SearchableComboDelegate):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context

    def _populate(self, combo, index):
        configured = self._context.settings_repo.get_categories()
        from_db = self._context.part_repo.list_distinct_categories()
        seen = set()
        for cat in configured + from_db:
            if cat not in seen:
                combo.addItem(cat, cat)
                seen.add(cat)

    def setModelData(self, editor, model, index):
        text = editor.currentText().strip()
        model.setData(index, text, Qt.EditRole)


class _PackageDelegate(_SearchableComboDelegate):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context

    def _populate(self, combo, index):
        combo.addItem("(none)", "")
        for pkg in self._context.settings_repo.get_package_types():
            combo.addItem(pkg, pkg)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.EditRole)


class _LocationDelegate(_SearchableComboDelegate):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context

    def _populate(self, combo, index):
        occupied = self._context.part_repo.list_occupied_slot_ids()
        combo.addItem("(none)", None)
        model = combo.model()
        for container in self._context.storage_service.list_containers():
            for slot in self._context.storage_service.list_slots(container.id):
                label = f"{container.name} / {slot.label}"
                if slot.id in occupied:
                    combo.addItem(f"{label}  \u25cf", slot.id)
                    item = model.item(combo.count() - 1)
                    item.setForeground(QBrush(QColor(180, 130, 0)))
                else:
                    combo.addItem(f"{label}  \u25cb", slot.id)

    def setEditorData(self, editor, index):
        current = index.data(Qt.DisplayRole) or ""
        idx = editor.findText(current, Qt.MatchFlag.MatchStartsWith)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setCurrentIndex(0)


class _MergeDropTableView(QTableView):
    """QTableView that supports dragging one row onto another to trigger a merge."""

    merge_requested = Signal(int, int)  # (drag_part_id, drop_part_id)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(InventoryTableModel.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(InventoryTableModel.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not mime.hasFormat(InventoryTableModel.MIME_TYPE):
            super().dropEvent(event)
            return

        drag_id = int(bytes(mime.data(InventoryTableModel.MIME_TYPE)).decode())
        drop_index = self.indexAt(event.position().toPoint())
        if not drop_index.isValid():
            event.ignore()
            return

        model = self.model()
        drop_id = model.part_id_at(drop_index.row())
        if drop_id is None or drop_id == drag_id:
            event.ignore()
            return

        event.acceptProposedAction()
        self.merge_requested.emit(drag_id, drop_id)


class InventoryScreen(QWidget):
    inventory_changed = Signal()
    find_in_storage_requested = Signal(int)  # slot_id
    merge_requested = Signal(int, int)  # (part_id_a, part_id_b) — drag-drop merge

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_part_id: int | None = None

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search parts, aliases, package, or SKU")
        self.search_edit.textChanged.connect(self.refresh_inventory)

        self.inventory_model = InventoryTableModel([])
        self.inventory_table = _MergeDropTableView()
        self.inventory_table.setModel(self.inventory_model)
        self.inventory_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.inventory_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.inventory_table.setEditTriggers(QTableView.EditTrigger.DoubleClicked)
        self.inventory_table.horizontalHeader().setStretchLastSection(True)
        self.inventory_table.verticalHeader().setVisible(False)
        self.inventory_table.clicked.connect(self._on_inventory_clicked)
        self.inventory_table.merge_requested.connect(self._on_merge_drop)
        self.inventory_model.cell_edited.connect(self._on_cell_edited)
        self.inventory_table.setItemDelegateForColumn(1, _CategoryDelegate(context, self.inventory_table))
        self.inventory_table.setItemDelegateForColumn(3, _PackageDelegate(context, self.inventory_table))
        self.inventory_table.setItemDelegateForColumn(4, _LocationDelegate(context, self.inventory_table))

        self.name_value = QLabel("Select a part")
        self.category_value = QLabel("")
        self.package_value = QLabel("")
        self.total_qty_value = QLabel("")
        self.sku_value = QLabel("")
        self.location_value = QLabel("")
        self.notes_text = QTextEdit()
        self.notes_text.setToolTip("Edit this field and click Save Notes to persist changes")

        # Qty adjustment buttons
        self.plus_one_btn = QPushButton("+1")
        self.plus_one_btn.setToolTip("Add 1 to quantity")
        self.minus_one_btn = QPushButton("-1")
        self.minus_one_btn.setToolTip("Remove 1 from quantity")
        self.plus_ten_btn = QPushButton("+10")
        self.plus_ten_btn.setToolTip("Add 10 to quantity")
        self.minus_ten_btn = QPushButton("-10")
        self.minus_ten_btn.setToolTip("Remove 10 from quantity")

        # Part management buttons
        self.new_part_btn = QPushButton("New Part")
        self.new_part_btn.setToolTip("Add a new component to the inventory")
        self.edit_part_btn = QPushButton("Edit Part")
        self.edit_part_btn.setToolTip("Edit the selected part's details")
        self.delete_part_btn = QPushButton("Delete Part")
        self.delete_part_btn.setToolTip("Remove the selected part from inventory")
        self.add_alias_btn = QPushButton("Add Search Alias")
        self.add_alias_btn.setToolTip("Add an alternate name so this part can be found by different search terms")
        self.find_storage_btn = QPushButton("Find in Storage")
        self.find_storage_btn.setToolTip("Show where this part is stored")
        self.save_notes_btn = QPushButton("Save Notes")
        self.save_notes_btn.setToolTip("Save changes to the part notes")

        self.plus_one_btn.clicked.connect(lambda: self._adjust_qty(1))
        self.minus_one_btn.clicked.connect(lambda: self._adjust_qty(-1))
        self.plus_ten_btn.clicked.connect(lambda: self._adjust_qty(10))
        self.minus_ten_btn.clicked.connect(lambda: self._adjust_qty(-10))
        self.find_storage_btn.clicked.connect(self._find_in_storage)
        self.new_part_btn.clicked.connect(self._new_part)
        self.edit_part_btn.clicked.connect(self._edit_part)
        self.delete_part_btn.clicked.connect(self._delete_part)
        self.add_alias_btn.clicked.connect(self._add_alias)
        self.save_notes_btn.clicked.connect(self._save_notes)

        self._build_ui()
        self.refresh_inventory()

    def _build_ui(self) -> None:
        detail_form = QFormLayout()
        detail_form.addRow("Part", self.name_value)
        detail_form.addRow("Category", self.category_value)
        detail_form.addRow("Package", self.package_value)
        detail_form.addRow("Total Qty", self.total_qty_value)
        detail_form.addRow("SKU", self.sku_value)
        location_row = QHBoxLayout()
        location_row.addWidget(self.location_value)
        location_row.addWidget(self.find_storage_btn)
        detail_form.addRow("Location", location_row)

        detail_group = QGroupBox("Part Details")
        detail_group.setLayout(detail_form)

        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()
        notes_layout.addWidget(self.notes_text)
        notes_layout.addWidget(self.save_notes_btn)
        notes_group.setLayout(notes_layout)

        qty_group = QGroupBox("Adjust Quantity")
        qty_row = QHBoxLayout()
        for btn in [self.plus_one_btn, self.minus_one_btn, self.plus_ten_btn, self.minus_ten_btn]:
            qty_row.addWidget(btn)
        qty_group.setLayout(qty_row)

        part_actions_group = QGroupBox("Part Actions")
        part_actions_row = QHBoxLayout()
        for btn in [self.new_part_btn, self.edit_part_btn, self.delete_part_btn, self.add_alias_btn]:
            part_actions_row.addWidget(btn)
        part_actions_group.setLayout(part_actions_row)

        right_layout = QVBoxLayout()
        right_layout.addWidget(detail_group)
        right_layout.addWidget(notes_group)
        right_layout.addWidget(qty_group)
        right_layout.addWidget(part_actions_group)
        right_layout.addStretch()

        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.inventory_table)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([700, 450])

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def selected_part_ids(self) -> list[int]:
        """Return part IDs for currently selected rows."""
        indexes = self.inventory_table.selectionModel().selectedRows()
        ids = []
        for idx in indexes:
            pid = self.inventory_model.part_id_at(idx.row())
            if pid is not None:
                ids.append(pid)
        return ids

    def refresh_inventory(self) -> None:
        query = self.search_edit.text().strip()
        if query:
            ids = self.context.search_service.search(query)
            rows = self.context.inventory_service.list_inventory(ids)
        else:
            rows = self.context.inventory_service.list_inventory()
        self.inventory_model.update_rows(rows)
        if rows and self.current_part_id is None:
            self._load_detail(rows[0].part_id)

    def refresh_current_detail(self) -> None:
        if self.current_part_id is not None:
            self._load_detail(self.current_part_id)
        self.refresh_inventory()
        self.inventory_changed.emit()

    def _on_inventory_clicked(self, index) -> None:
        part_id = self.inventory_model.part_id_at(index.row())
        if part_id is not None:
            self._load_detail(part_id)

    def _load_detail(self, part_id: int) -> None:
        detail = self.context.inventory_service.get_part_detail(part_id)
        self.current_part_id = part_id
        self.name_value.setText(detail.part.name)
        self.category_value.setText(detail.part.category or "")
        self.package_value.setText(detail.part.default_package or "")
        self.total_qty_value.setText(str(detail.part.qty))
        self.sku_value.setText(detail.part.supplier_sku or "")
        self.location_value.setText(detail.location or "")
        self.notes_text.setPlainText(detail.part.notes or "")

    def _get_slot_choices(self) -> list[tuple[int, str]]:
        """Build list of (slot_id, label) for all storage slots."""
        choices: list[tuple[int, str]] = []
        for container in self.context.storage_service.list_containers():
            for slot in self.context.storage_service.list_slots(container.id):
                choices.append((slot.id, f"{container.name} / {slot.label}"))
        return choices

    def _adjust_qty(self, delta: int) -> None:
        if self.current_part_id is None:
            QMessageBox.information(self, "Select a part", "Select a part first.")
            return
        try:
            self.context.inventory_service.adjust_qty(self.current_part_id, delta)
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Quantity update failed", str(exc))

    def _part_dialog_options(self) -> dict:
        return {
            "slots": self._get_slot_choices(),
            "occupied_slot_ids": self.context.part_repo.list_occupied_slot_ids(),
            "categories": self.context.part_repo.list_distinct_categories(),
            "packages": self.context.part_repo.list_distinct_packages(),
        }

    def _new_part(self) -> None:
        dialog = PartDialog(self, **self._part_dialog_options())
        if dialog.exec() != PartDialog.DialogCode.Accepted:
            return
        fields = dialog.get_fields()
        try:
            part = self.context.inventory_service.upsert_part(
                name=fields["name"],
                category=fields["category"],
                package=fields["default_package"],
                supplier_sku=fields["supplier_sku"],
                purchase_url=fields["purchase_url"],
                notes=fields["notes"],
                qty=fields["qty"],
                slot_id=fields["slot_id"],
            )
            # Set fields not in upsert_part signature
            extra = {}
            if fields["manufacturer"]:
                extra["manufacturer"] = fields["manufacturer"]
            if fields["mpn"]:
                extra["mpn"] = fields["mpn"]
            if fields["supplier_name"]:
                extra["supplier_name"] = fields["supplier_name"]
            if extra:
                self.context.inventory_service.update_part(part.id, **extra)
            self.context.search_service.rebuild()
            self.current_part_id = part.id
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Create failed", str(exc))

    def _edit_part(self) -> None:
        if self.current_part_id is None:
            QMessageBox.information(self, "Select a part", "Select a part first.")
            return
        part = self.context.part_repo.get_part_by_id(self.current_part_id)
        if part is None:
            return
        dialog = PartDialog(self, part=part, **self._part_dialog_options())
        if dialog.exec() != PartDialog.DialogCode.Accepted:
            return
        fields = dialog.get_fields()
        try:
            normalized_name = normalize_text(fields["name"])
            self.context.inventory_service.update_part(
                self.current_part_id,
                name=fields["name"],
                normalized_name=normalized_name,
                category=fields["category"],
                manufacturer=fields["manufacturer"],
                mpn=fields["mpn"],
                supplier_name=fields["supplier_name"],
                supplier_sku=fields["supplier_sku"],
                purchase_url=fields["purchase_url"],
                default_package=fields["default_package"],
                notes=fields["notes"],
                qty=fields["qty"],
                slot_id=fields["slot_id"],
                storage_class_override=fields.get("storage_class_override"),
            )
            self.context.search_service.rebuild()
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Update failed", str(exc))

    def _delete_part(self) -> None:
        if self.current_part_id is None:
            QMessageBox.information(self, "Select a part", "Select a part first.")
            return
        part = self.context.part_repo.get_part_by_id(self.current_part_id)
        if part is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete part",
            f"Are you sure you want to delete '{part.name}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.inventory_service.delete_part(self.current_part_id)
            self.current_part_id = None
            self.context.search_service.rebuild()
            self.refresh_current_detail()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot delete", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))

    def _on_cell_edited(self, part_id: int, column: int, value: object) -> None:
        try:
            if column == 0:  # Component name
                name = str(value).strip()
                if name:
                    self.context.inventory_service.update_part(
                        part_id, name=name, normalized_name=normalize_text(name),
                    )
                    self.context.search_service.rebuild()
            elif column == 1:  # Category
                self.context.inventory_service.update_part(
                    part_id, category=str(value).strip() or None,
                )
            elif column == 2:  # Qty
                try:
                    new_qty = max(0, int(value))
                except (ValueError, TypeError):
                    return
                self.context.inventory_service.update_part(part_id, qty=new_qty)
            elif column == 3:  # Package
                self.context.inventory_service.update_part(
                    part_id, default_package=str(value).strip() or None,
                )
            elif column == 4:  # Location
                slot_id = value  # slot_id (int) or None from delegate
                self.context.inventory_service.update_part(part_id, slot_id=slot_id)
            elif column == 5:  # SKU
                self.context.inventory_service.update_part(
                    part_id, supplier_sku=str(value).strip() or None,
                )
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Edit failed", str(exc))

    def _save_notes(self) -> None:
        if self.current_part_id is None:
            return
        new_notes = self.notes_text.toPlainText().strip() or None
        reply = QMessageBox.question(
            self,
            "Save notes",
            "Are you sure you want to save the updated notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.inventory_service.update_part_notes(self.current_part_id, new_notes)
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Save notes failed", str(exc))

    def _on_merge_drop(self, drag_id: int, drop_id: int) -> None:
        self.merge_requested.emit(drag_id, drop_id)

    def _find_in_storage(self) -> None:
        if self.current_part_id is None:
            QMessageBox.information(self, "Select a part", "Select a part first.")
            return
        part = self.context.part_repo.get_part_by_id(self.current_part_id)
        if part is None or part.slot_id is None:
            QMessageBox.information(self, "Not assigned", "This part has no storage assignment.")
            return
        self.find_in_storage_requested.emit(part.slot_id)

    def _add_alias(self) -> None:
        if self.current_part_id is None:
            return
        alias, ok = QInputDialog.getText(self, "Add alias", "Alias:")
        if not ok or not alias.strip():
            return
        try:
            self.context.inventory_service.add_alias(self.current_part_id, alias.strip())
            self.context.search_service.rebuild()
            self.refresh_current_detail()
        except Exception as exc:
            QMessageBox.critical(self, "Alias failed", str(exc))
