from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.services.dedup import DuplicatePair


_COMPARISON_FIELDS = [
    ("Name", "name"),
    ("Category", "category"),
    ("Quantity", "qty"),
    ("Package", "default_package"),
    ("Supplier SKU", "supplier_sku"),
    ("Manufacturer", "manufacturer"),
    ("MPN", "mpn"),
    ("Supplier", "supplier_name"),
    ("Purchase URL", "purchase_url"),
    ("Storage Class", "storage_class_override"),
    ("Location", None),       # special: from get_part_location
    ("Aliases", None),        # special: count
    ("BOM References", None), # special: count
    ("Created", "created_at"),
    ("Notes", "notes"),
]


class DedupDialog(QDialog):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Find & Merge Duplicates")
        self.setMinimumSize(850, 550)
        self._pairs: list[DuplicatePair] = []
        self._current_pair: DuplicatePair | None = None

        # ── Top bar ──
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Threshold:"))
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(50, 100)
        self._threshold_spin.setValue(75)
        top_bar.addWidget(self._threshold_spin)

        self._scan_btn = QPushButton("Scan for Duplicates")
        self._scan_btn.clicked.connect(self._do_scan)
        top_bar.addWidget(self._scan_btn)

        self._count_label = QLabel("")
        top_bar.addStretch()
        top_bar.addWidget(self._count_label)

        # ── Pair list (left) ──
        self._pair_list = QListWidget()
        self._pair_list.currentItemChanged.connect(self._on_pair_selected)

        # ── Detail panel (right) ──
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        self._comparison_table = QTableWidget()
        self._comparison_table.setColumnCount(3)
        self._comparison_table.setHorizontalHeaderLabels(["Field", "Part A", "Part B"])
        self._comparison_table.horizontalHeader().setStretchLastSection(True)
        self._comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._comparison_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        detail_layout.addWidget(self._comparison_table)

        # Keep radio buttons
        keep_row = QHBoxLayout()
        self._keep_group = QButtonGroup(self)
        self._keep_a_radio = QRadioButton("Keep Part A")
        self._keep_b_radio = QRadioButton("Keep Part B")
        self._keep_a_radio.setChecked(True)
        self._keep_group.addButton(self._keep_a_radio, 0)
        self._keep_group.addButton(self._keep_b_radio, 1)
        keep_row.addWidget(self._keep_a_radio)
        keep_row.addWidget(self._keep_b_radio)
        keep_row.addStretch()
        detail_layout.addLayout(keep_row)

        # Slot conflict resolution
        self._slot_row = QHBoxLayout()
        self._slot_label = QLabel("Location:")
        self._slot_group = QButtonGroup(self)
        self._slot_a_radio = QRadioButton("Slot A")
        self._slot_b_radio = QRadioButton("Slot B")
        self._slot_a_radio.setChecked(True)
        self._slot_group.addButton(self._slot_a_radio, 0)
        self._slot_group.addButton(self._slot_b_radio, 1)
        self._slot_warning = QLabel("Both parts are stored in different locations — choose which to keep.")
        self._slot_warning.setStyleSheet("color: #B25000; font-weight: bold;")
        self._slot_row.addWidget(self._slot_label)
        self._slot_row.addWidget(self._slot_a_radio)
        self._slot_row.addWidget(self._slot_b_radio)
        self._slot_row.addStretch()

        self._slot_container = QWidget()
        slot_vlayout = QVBoxLayout(self._slot_container)
        slot_vlayout.setContentsMargins(0, 0, 0, 0)
        slot_vlayout.addWidget(self._slot_warning)
        slot_vlayout.addLayout(self._slot_row)
        self._slot_container.setVisible(False)
        detail_layout.addWidget(self._slot_container)

        # Status label
        self._status_label = QLabel("")
        detail_layout.addWidget(self._status_label)

        # Action buttons
        btn_row = QHBoxLayout()
        self._merge_btn = QPushButton("Merge")
        self._merge_btn.clicked.connect(self._do_merge)
        self._merge_btn.setEnabled(False)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.clicked.connect(self._skip_pair)
        self._skip_btn.setEnabled(False)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._merge_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        detail_layout.addLayout(btn_row)

        # ── Splitter ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._pair_list)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        # ── Main layout ──
        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(splitter)

    def _do_scan(self) -> None:
        threshold = self._threshold_spin.value()
        self.context.search_service.rebuild()
        self._pairs = self.context.dedup_service.find_duplicate_pairs(threshold)
        self._populate_pair_list()

    def _populate_pair_list(self) -> None:
        self._pair_list.clear()
        self._current_pair = None
        self._comparison_table.setRowCount(0)
        self._merge_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._slot_container.setVisible(False)

        if not self._pairs:
            self._count_label.setText("No duplicates found")
            self._status_label.setText("")
            return

        self._count_label.setText(f"{len(self._pairs)} pair(s) found")
        for pair in self._pairs:
            label = f"score {pair.score:.0f}: {pair.part_a.name} vs {pair.part_b.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pair)
            self._pair_list.addItem(item)

        self._pair_list.setCurrentRow(0)

    def _on_pair_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            self._current_pair = None
            self._merge_btn.setEnabled(False)
            self._skip_btn.setEnabled(False)
            return

        pair: DuplicatePair = current.data(Qt.ItemDataRole.UserRole)
        self._current_pair = pair
        self._skip_btn.setEnabled(True)
        self._populate_comparison(pair)
        self._select_default_keep(pair)

    def _populate_comparison(self, pair: DuplicatePair) -> None:
        pa, pb = pair.part_a, pair.part_b
        self._comparison_table.setRowCount(len(_COMPARISON_FIELDS))

        loc_a = self.context.part_repo.get_part_location(pa.id)
        loc_b = self.context.part_repo.get_part_location(pb.id)
        alias_count_a = len(self.context.part_repo.list_aliases_for_part(pa.id))
        alias_count_b = len(self.context.part_repo.list_aliases_for_part(pb.id))
        bom_count_a = self.context.part_repo.count_bom_references(pa.id)
        bom_count_b = self.context.part_repo.count_bom_references(pb.id)

        for row, (label, attr) in enumerate(_COMPARISON_FIELDS):
            self._comparison_table.setItem(row, 0, QTableWidgetItem(label))
            if attr is not None:
                val_a = str(getattr(pa, attr) or "")
                val_b = str(getattr(pb, attr) or "")
            elif label == "Location":
                val_a, val_b = loc_a, loc_b
            elif label == "Aliases":
                val_a, val_b = str(alias_count_a), str(alias_count_b)
            elif label == "BOM References":
                val_a, val_b = str(bom_count_a), str(bom_count_b)
            else:
                val_a = val_b = ""

            item_a = QTableWidgetItem(val_a)
            item_b = QTableWidgetItem(val_b)
            # Highlight differences
            if val_a != val_b and val_a and val_b:
                item_a.setBackground(Qt.GlobalColor.yellow)
                item_b.setBackground(Qt.GlobalColor.yellow)
            self._comparison_table.setItem(row, 1, item_a)
            self._comparison_table.setItem(row, 2, item_b)

        self._comparison_table.resizeColumnsToContents()

        # Slot conflict UI
        has_slot_conflict = (
            pa.slot_id is not None
            and pb.slot_id is not None
            and pa.slot_id != pb.slot_id
        )
        self._slot_container.setVisible(has_slot_conflict)
        if has_slot_conflict:
            self._slot_a_radio.setText(loc_a or f"Slot #{pa.slot_id}")
            self._slot_b_radio.setText(loc_b or f"Slot #{pb.slot_id}")
            self._slot_a_radio.setChecked(True)

        self._merge_btn.setEnabled(True)
        self._status_label.setText(f"Match reasons: {', '.join(pair.match_reasons)}")

    def _select_default_keep(self, pair: DuplicatePair) -> None:
        pa, pb = pair.part_a, pair.part_b
        bom_a = self.context.part_repo.count_bom_references(pa.id)
        bom_b = self.context.part_repo.count_bom_references(pb.id)

        # Prefer: higher qty → more BOM refs → older created_at
        if pa.qty > pb.qty:
            self._keep_a_radio.setChecked(True)
        elif pb.qty > pa.qty:
            self._keep_b_radio.setChecked(True)
        elif bom_a > bom_b:
            self._keep_a_radio.setChecked(True)
        elif bom_b > bom_a:
            self._keep_b_radio.setChecked(True)
        elif (pa.created_at or "") <= (pb.created_at or ""):
            self._keep_a_radio.setChecked(True)
        else:
            self._keep_b_radio.setChecked(True)

    def _do_merge(self) -> None:
        pair = self._current_pair
        if pair is None:
            return

        keep_a = self._keep_a_radio.isChecked()
        keep_part = pair.part_a if keep_a else pair.part_b
        remove_part = pair.part_b if keep_a else pair.part_a

        # Resolve slot conflict
        keep_slot_id = None
        has_slot_conflict = (
            pair.part_a.slot_id is not None
            and pair.part_b.slot_id is not None
            and pair.part_a.slot_id != pair.part_b.slot_id
        )
        if has_slot_conflict:
            keep_slot_id = (
                pair.part_a.slot_id if self._slot_a_radio.isChecked() else pair.part_b.slot_id
            )

        reply = QMessageBox.question(
            self,
            "Confirm Merge",
            f"Keep \"{keep_part.name}\" (#{keep_part.id}) and remove "
            f"\"{remove_part.name}\" (#{remove_part.id})?\n\n"
            f"This will combine quantities, transfer aliases, and remap BOM references.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self.context.dedup_service.merge_parts(
                keep_part.id, remove_part.id, keep_slot_id=keep_slot_id,
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Merge Failed", str(exc))
            return

        msg = f"Merged \"{remove_part.name}\" into \"{keep_part.name}\""
        if result.discarded_slot_label:
            msg += f"\nDiscarded location: {result.discarded_slot_label}"
        self._status_label.setText(msg)

        # Full rescan after merge
        self._do_scan()

    def _skip_pair(self) -> None:
        row = self._pair_list.currentRow()
        if row < 0:
            return
        self._pair_list.takeItem(row)
        if self._pair_list.count() > 0:
            self._pair_list.setCurrentRow(min(row, self._pair_list.count() - 1))
        else:
            self._current_pair = None
            self._comparison_table.setRowCount(0)
            self._merge_btn.setEnabled(False)
            self._skip_btn.setEnabled(False)
            self._slot_container.setVisible(False)
            self._count_label.setText("No more pairs")
