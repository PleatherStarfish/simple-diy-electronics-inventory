from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.domain.part_signature import ReviewPriority
from eurorack_inventory.services.dedup import DuplicatePair


# Only non-empty fields are shown in the comparison.
_COMPARISON_FIELDS = [
    ("Name", "name"),
    ("Category", "category"),
    ("Qty", "qty"),
    ("Package", "default_package"),
    ("SKU", "supplier_sku"),
    ("Manufacturer", "manufacturer"),
    ("MPN", "mpn"),
    ("Supplier", "supplier_name"),
    ("URL", "purchase_url"),
    ("Storage Class", "storage_class_override"),
    ("Location", None),
    ("Aliases", None),
    ("BOM Refs", None),
    ("Created", "created_at"),
    ("Notes", "notes"),
]

# Subtle tints that sit well on the #FFFFFF table surface.
_GREEN = QColor("#EBF5EB")
_AMBER = QColor("#FFF8E1")
_RED = QColor("#FEECEC")
_GRAY_DIFF = QColor("#F5F5FA")

# Map conflict rules to the comparison labels they highlight.
_CONFLICT_FIELD_MAP: dict[str, list[str]] = {
    "resistor_value_differs": ["Name"],
    "capacitor_value_differs": ["Name"],
    "connector_pin_count_differs": ["Name"],
    "connector_pitch_differs": ["Name"],
    "connector_subtype_differs": ["Name"],
    "dip_socket_pin_count_differs": ["Name"],
    "pot_value_differs": ["Name"],
    "switch_function_differs": ["Name"],
    "package_technology_differs": ["Package"],
    "semiconductor_base_device_differs": ["Name", "MPN"],
    "component_family_differs": ["Category"],
    "disjoint_tayda_sku": ["SKU"],
    "different_manufacturer": ["Manufacturer"],
    "packing_suffix_differs": ["MPN"],
    "generic_vs_specific": ["Package", "Name"],
    "different_tolerance": ["Name"],
    "different_voltage_rating": ["Name"],
}

# ── Inline button styles matching the app's accent blue ───────────────────

_BTN_PRIMARY = """
    QPushButton {
        background-color: #0071E3; color: #FFFFFF; border: none;
        border-radius: 6px; padding: 6px 20px; font-weight: 600; min-height: 22px;
    }
    QPushButton:hover   { background-color: #005BB5; }
    QPushButton:pressed { background-color: #004A94; }
    QPushButton:disabled { background-color: #B0D4F1; color: #FFFFFF; }
"""

_BTN_OUTLINE_RED = """
    QPushButton {
        background-color: #FFFFFF; color: #C62828;
        border: 1px solid #E0E0E0; border-radius: 6px;
        padding: 6px 14px; min-height: 22px;
    }
    QPushButton:hover { background-color: #FFEBEE; border-color: #C62828; }
    QPushButton:disabled { color: #BDBDBD; border-color: #EEEEEE; }
"""



_SEARCH_STYLE = """
    QLineEdit {
        border: 1px solid #D1D1D6; border-radius: 6px;
        padding: 5px 10px; font-size: 13px;
        background-color: #FFFFFF;
    }
    QLineEdit:focus { border-color: #0071E3; }
"""

_OVERRIDE_FIELD_DEFS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("category", "Category"),
    ("manufacturer", "Manufacturer"),
    ("mpn", "MPN"),
    ("supplier_sku", "Supplier SKU"),
    ("supplier_name", "Supplier"),
    ("default_package", "Package"),
    ("purchase_url", "Purchase URL"),
    ("notes", "Notes"),
]


def _thin_rule() -> QFrame:
    """A 1 px horizontal separator."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #E5E5EA;")
    f.setFixedHeight(1)
    return f


# ── Dialog ────────────────────────────────────────────────────────────────

class DedupDialog(QDialog):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Duplicates")
        self.setMinimumSize(920, 560)
        self._pairs: list[DuplicatePair] = []
        self._current_pair: DuplicatePair | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── Header row ──
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        title = QLabel("Find & Merge Duplicates")
        tf = QFont()
        tf.setPointSize(15)
        tf.setWeight(QFont.Weight.DemiBold)
        title.setFont(tf)
        hdr.addWidget(title)
        hdr.addStretch()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #6E6E73; font-size: 12px;")
        hdr.addWidget(self._count_label)
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.setStyleSheet(_BTN_PRIMARY)
        self._scan_btn.setFixedWidth(72)
        self._scan_btn.clicked.connect(self._do_scan)
        hdr.addWidget(self._scan_btn)
        root.addLayout(hdr)

        # ── Splitter ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # Left — pair list
        self._pair_list = QListWidget()
        self._pair_list.setMinimumWidth(200)
        self._pair_list.setMaximumWidth(300)
        self._pair_list.currentItemChanged.connect(self._on_pair_selected)
        splitter.addWidget(self._pair_list)

        # Right — detail
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(12, 0, 0, 0)
        dl.setSpacing(8)

        # Chips line (reasons / warnings)
        self._chips_label = QLabel("")
        self._chips_label.setWordWrap(True)
        self._chips_label.setStyleSheet("font-size: 11px; color: #6E6E73;")
        dl.addWidget(self._chips_label)

        # Comparison table
        self._comparison_table = QTableWidget()
        self._comparison_table.setColumnCount(3)
        self._comparison_table.setHorizontalHeaderLabels(["", "Part A", "Part B"])
        self._comparison_table.horizontalHeader().setStretchLastSection(True)
        self._comparison_table.verticalHeader().setVisible(False)
        self._comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._comparison_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._comparison_table.setShowGrid(False)
        self._comparison_table.setAlternatingRowColors(False)
        self._comparison_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E0E0E0; border-radius: 6px;
                background-color: #FFFFFF;
            }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section {
                background-color: #FAFAFA; border: none;
                border-bottom: 1px solid #E0E0E0;
                padding: 5px 8px; font-weight: 600;
                font-size: 11px; color: #6E6E73;
            }
        """)
        dl.addWidget(self._comparison_table)

        # Keep radios
        keep_row = QHBoxLayout()
        keep_row.setSpacing(14)
        kl = QLabel("Keep:")
        kl.setStyleSheet("font-weight: 600; color: #3A3A3C;")
        self._keep_group = QButtonGroup(self)
        self._keep_a_radio = QRadioButton("Part A")
        self._keep_b_radio = QRadioButton("Part B")
        self._keep_custom_radio = QRadioButton("Custom\u2026")
        self._keep_custom_radio.setToolTip(
            "Merge into Part A but pick individual field values from either part"
        )
        self._keep_a_radio.setChecked(True)
        self._keep_group.addButton(self._keep_a_radio, 0)
        self._keep_group.addButton(self._keep_b_radio, 1)
        self._keep_group.addButton(self._keep_custom_radio, 2)
        keep_row.addWidget(kl)
        keep_row.addWidget(self._keep_a_radio)
        keep_row.addWidget(self._keep_b_radio)
        keep_row.addWidget(self._keep_custom_radio)
        keep_row.addStretch()
        dl.addLayout(keep_row)

        # Slot conflict (hidden by default)
        self._slot_container = QWidget()
        sc = QVBoxLayout(self._slot_container)
        sc.setContentsMargins(0, 0, 0, 0)
        sc.setSpacing(4)
        self._slot_warning = QLabel("Both parts are in different locations.")
        self._slot_warning.setStyleSheet("color: #E65100; font-size: 12px;")
        sc.addWidget(self._slot_warning)
        sr = QHBoxLayout()
        sr.setSpacing(12)
        sl = QLabel("Keep location:")
        sl.setStyleSheet("font-weight: 600; color: #3A3A3C;")
        self._slot_group = QButtonGroup(self)
        self._slot_a_radio = QRadioButton("A")
        self._slot_b_radio = QRadioButton("B")
        self._slot_a_radio.setChecked(True)
        self._slot_group.addButton(self._slot_a_radio, 0)
        self._slot_group.addButton(self._slot_b_radio, 1)
        sr.addWidget(sl)
        sr.addWidget(self._slot_a_radio)
        sr.addWidget(self._slot_b_radio)
        sr.addStretch()
        sc.addLayout(sr)
        self._slot_container.setVisible(False)
        dl.addWidget(self._slot_container)

        dl.addWidget(_thin_rule())

        # ── Merged result fields with per-field A/B picking ──
        self._overrides_group = QGroupBox("Merged Result")
        og_layout = QVBoxLayout()
        og_layout.setContentsMargins(8, 8, 8, 8)
        og_layout.setSpacing(4)
        hint = QLabel("Pick values from A or B per field, or type a custom value.")
        hint.setStyleSheet("color: #6E6E73; font-size: 11px;")
        og_layout.addWidget(hint)
        of = QFormLayout()
        of.setSpacing(12)
        self._override_rows: dict[str, tuple[QRadioButton, QRadioButton, QLineEdit]] = {}
        for field_name, label in _OVERRIDE_FIELD_DEFS:
            grp = QButtonGroup(self)
            grp.setExclusive(False)
            radio_a = QRadioButton("A")
            radio_b = QRadioButton("B")
            grp.addButton(radio_a, 0)
            grp.addButton(radio_b, 1)
            le = QLineEdit()
            le.setStyleSheet(_SEARCH_STYLE)
            radio_a.clicked.connect(lambda checked, fn=field_name: self._pick_field(fn, "a"))
            radio_b.clicked.connect(lambda checked, fn=field_name: self._pick_field(fn, "b"))
            le.textEdited.connect(lambda text, fn=field_name: self._on_field_edited(fn))
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(radio_a)
            row_layout.addWidget(radio_b)
            row_layout.addWidget(le, 1)
            self._override_rows[field_name] = (radio_a, radio_b, le)
            of.addRow(label, row_widget)
        og_layout.addLayout(of)
        self._overrides_group.setLayout(og_layout)
        self._overrides_group.setVisible(False)
        dl.addWidget(self._overrides_group)

        # Show/hide overrides when keep radio changes
        self._keep_group.buttonToggled.connect(self._on_keep_changed)

        dl.addWidget(_thin_rule())

        # Action buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._merge_btn = QPushButton("Merge")
        self._merge_btn.setStyleSheet(_BTN_PRIMARY)
        self._merge_btn.clicked.connect(self._do_merge)
        self._merge_btn.setEnabled(False)
        self._not_dup_btn = QPushButton("Not a Duplicate")
        self._not_dup_btn.setStyleSheet(_BTN_OUTLINE_RED)
        self._not_dup_btn.clicked.connect(self._mark_not_duplicate)
        self._not_dup_btn.setEnabled(False)
        self._not_dup_btn.setToolTip("Permanently dismiss this pair")
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.clicked.connect(self._skip_pair)
        self._skip_btn.setEnabled(False)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(self._merge_btn)
        btns.addWidget(self._not_dup_btn)
        btns.addWidget(self._skip_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        dl.addLayout(btns)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

    # ── Scan ──────────────────────────────────────────────────────────────

    def _do_scan(self) -> None:
        self.context.search_service.rebuild()
        self._pairs = self.context.dedup_service.find_duplicate_pairs()
        self._populate_pair_list()

    def _populate_pair_list(self) -> None:
        self._pair_list.clear()
        self._current_pair = None
        self._comparison_table.setRowCount(0)
        self._set_actions(False)
        self._slot_container.setVisible(False)
        self._overrides_group.setVisible(False)
        self._chips_label.setText("")

        if not self._pairs:
            self._count_label.setText("No duplicates found")
            return

        n = len(self._pairs)
        self._count_label.setText(f"{n} pair{'s' if n != 1 else ''}")

        for pair in self._pairs:
            # Two-line item: part A name / vs part B name
            text = f"{pair.part_a.name}\nvs  {pair.part_b.name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, pair)
            item.setSizeHint(QSize(0, 42))
            self._pair_list.addItem(item)

        self._pair_list.setCurrentRow(0)

    # ── Selection ─────────────────────────────────────────────────────────

    def _on_pair_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            self._current_pair = None
            self._set_actions(False)
            self._overrides_group.setVisible(False)
            return
        pair: DuplicatePair = current.data(Qt.ItemDataRole.UserRole)
        self._current_pair = pair
        self._populate_comparison(pair)
        self._select_default_keep(pair)
        # If Custom was selected from a previous pair, refresh its fields
        if self._keep_custom_radio.isChecked():
            self._refresh_overrides()
        self._set_actions(True)

    def _populate_comparison(self, pair: DuplicatePair) -> None:
        pa, pb = pair.part_a, pair.part_b

        loc_a = self.context.part_repo.get_part_location(pa.id)
        loc_b = self.context.part_repo.get_part_location(pb.id)
        alias_a = len(self.context.part_repo.list_aliases_for_part(pa.id))
        alias_b = len(self.context.part_repo.list_aliases_for_part(pb.id))
        bom_a = self.context.part_repo.count_bom_references(pa.id)
        bom_b = self.context.part_repo.count_bom_references(pb.id)

        # Conflict field sets
        hard_fields: set[str] = set()
        warn_fields: set[str] = set()
        for r in pair.hard_rejects:
            hard_fields.update(_CONFLICT_FIELD_MAP.get(r, []))
        for w in pair.warnings:
            warn_fields.update(_CONFLICT_FIELD_MAP.get(w, []))

        # Build visible rows — skip fields empty on both sides
        rows: list[tuple[str, str, str]] = []
        for label, attr in _COMPARISON_FIELDS:
            if attr is not None:
                va = str(getattr(pa, attr)) if getattr(pa, attr) is not None else ""
                vb = str(getattr(pb, attr)) if getattr(pb, attr) is not None else ""
            elif label == "Location":
                va, vb = loc_a or "", loc_b or ""
            elif label == "Aliases":
                va, vb = (str(alias_a) if alias_a else ""), (str(alias_b) if alias_b else "")
            elif label == "BOM Refs":
                va, vb = (str(bom_a) if bom_a else ""), (str(bom_b) if bom_b else "")
            else:
                va = vb = ""
            if not va and not vb and label != "Name":
                continue
            rows.append((label, va, vb))

        self._comparison_table.setRowCount(len(rows))
        lbl_font = QFont()
        lbl_font.setWeight(QFont.Weight.DemiBold)

        for i, (label, va, vb) in enumerate(rows):
            li = QTableWidgetItem(label)
            li.setFont(lbl_font)
            li.setForeground(QColor("#6E6E73"))
            self._comparison_table.setItem(i, 0, li)

            ia = QTableWidgetItem(va)
            ib = QTableWidgetItem(vb)

            if label in hard_fields:
                ia.setBackground(_RED); ib.setBackground(_RED)
            elif label in warn_fields:
                ia.setBackground(_AMBER); ib.setBackground(_AMBER)
            elif va and vb and va == vb:
                ia.setBackground(_GREEN); ib.setBackground(_GREEN)
            elif va and vb:
                ia.setBackground(_GRAY_DIFF); ib.setBackground(_GRAY_DIFF)

            self._comparison_table.setItem(i, 1, ia)
            self._comparison_table.setItem(i, 2, ib)

        self._comparison_table.resizeColumnsToContents()
        self._comparison_table.setColumnWidth(0, 85)

        # Multi-location merge keeps all locations, so no slot choice is needed.
        self._slot_container.setVisible(False)

        # Chips
        parts: list[str] = []
        for r in pair.match_reasons:
            parts.append(f'<span style="color:#2E7D32">{_humanize(r)}</span>')
        for w in pair.warnings:
            parts.append(f'<span style="color:#E65100">{_humanize(w)}</span>')
        self._chips_label.setText(" \u00b7 ".join(parts) if parts else "")

    def _select_default_keep(self, pair: DuplicatePair) -> None:
        pa, pb = pair.part_a, pair.part_b
        bom_a = self.context.part_repo.count_bom_references(pa.id)
        bom_b = self.context.part_repo.count_bom_references(pb.id)
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

    # ── Override helpers ────────────────────────────────────────────────

    def _on_keep_changed(self, *_args) -> None:
        is_custom = self._keep_custom_radio.isChecked()
        self._overrides_group.setVisible(is_custom)
        if is_custom and self._current_pair is not None:
            self._refresh_overrides()

    def _pick_field(self, field_name: str, source: str) -> None:
        btn_a, btn_b, le = self._override_rows[field_name]
        pair = self._current_pair
        if pair is None:
            return
        part = pair.part_a if source == "a" else pair.part_b
        val = getattr(part, field_name, None)
        le.setText(str(val) if val is not None else "")
        btn_a.setChecked(source == "a")
        btn_b.setChecked(source == "b")

    def _on_field_edited(self, field_name: str) -> None:
        btn_a, btn_b, _le = self._override_rows[field_name]
        btn_a.setChecked(False)
        btn_b.setChecked(False)

    def _refresh_overrides(self) -> None:
        pair = self._current_pair
        if pair is None:
            return
        # Custom mode always merges into Part A; fields start from A with B fallback
        keep = pair.part_a
        remove = pair.part_b
        for field_name, _label in _OVERRIDE_FIELD_DEFS:
            btn_a, btn_b, le = self._override_rows[field_name]
            val_a = getattr(keep, field_name, None)
            val_b = getattr(remove, field_name, None)
            if val_a is not None:
                le.setText(str(val_a))
                btn_a.setChecked(True)
                btn_b.setChecked(False)
            elif val_b is not None:
                le.setText(str(val_b))
                btn_a.setChecked(False)
                btn_b.setChecked(True)
            else:
                le.setText("")
                btn_a.setChecked(False)
                btn_b.setChecked(False)

    def _collect_overrides(self) -> dict[str, str | None] | None:
        if not self._keep_custom_radio.isChecked():
            return None
        pair = self._current_pair
        if pair is None:
            return None
        # In custom mode, keeper is always Part A
        keep = pair.part_a
        remove = pair.part_b
        overrides: dict[str, str | None] = {}
        for field_name, _label in _OVERRIDE_FIELD_DEFS:
            _btn_a, _btn_b, le = self._override_rows[field_name]
            user_val = le.text().strip() or None
            keeper_val = getattr(keep, field_name, None)
            remove_val = getattr(remove, field_name, None)
            effective = keeper_val if keeper_val is not None else remove_val
            if user_val != effective:
                overrides[field_name] = user_val
        return overrides or None

    # ── Actions ───────────────────────────────────────────────────────────

    def _do_merge(self) -> None:
        pair = self._current_pair
        if pair is None:
            return
        # Custom mode always keeps Part A (overrides handle field values)
        keep_a = self._keep_a_radio.isChecked() or self._keep_custom_radio.isChecked()
        keep = pair.part_a if keep_a else pair.part_b
        remove = pair.part_b if keep_a else pair.part_a

        reply = QMessageBox.question(
            self, "Confirm Merge",
            f'Merge "{remove.name}" into "{keep.name}"?\n\n'
            "Quantities, aliases, and BOM references will be combined.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.dedup_service.merge_parts(
                keep.id, remove.id,
                score=pair.score, reasons=pair.match_reasons,
                sig_a=pair.sig_a, sig_b=pair.sig_b,
                overrides=self._collect_overrides(),
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Merge Failed", str(exc))
            return
        self._do_scan()

    def _mark_not_duplicate(self) -> None:
        pair = self._current_pair
        if pair is None:
            return
        self.context.dedup_feedback_repo.record_not_duplicate(
            pair.part_a.id, pair.part_b.id,
            pair.score, pair.match_reasons,
            pair.sig_a, pair.sig_b,
            pair.part_a.name, pair.part_b.name,
        )
        self._advance()

    def _skip_pair(self) -> None:
        self._advance()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _advance(self) -> None:
        row = self._pair_list.currentRow()
        if row < 0:
            return
        self._pair_list.takeItem(row)
        n = self._pair_list.count()
        if n > 0:
            self._pair_list.setCurrentRow(min(row, n - 1))
            self._count_label.setText(f"{n} pair{'s' if n != 1 else ''}")
        else:
            self._current_pair = None
            self._comparison_table.setRowCount(0)
            self._set_actions(False)
            self._slot_container.setVisible(False)
            self._overrides_group.setVisible(False)
            self._chips_label.setText("")
            self._count_label.setText("All done")

    def _set_actions(self, on: bool) -> None:
        self._merge_btn.setEnabled(on)
        self._not_dup_btn.setEnabled(on)
        self._skip_btn.setEnabled(on)


def _humanize(s: str) -> str:
    if ":" in s:
        base, tail = s.rsplit(":", 1)
        try:
            float(tail)
            return base.replace("_", " ")
        except ValueError:
            pass
    return s.replace("_", " ")
