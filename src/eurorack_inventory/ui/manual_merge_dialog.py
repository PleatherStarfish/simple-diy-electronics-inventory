from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import PartSignature


# Reuse the same visual constants as dedup_dialog.
_GREEN = QColor("#EBF5EB")
_AMBER = QColor("#FFF8E1")
_RED = QColor("#FEECEC")
_GRAY_DIFF = QColor("#F5F5FA")

_BTN_PRIMARY = """
    QPushButton {
        background-color: #0071E3; color: #FFFFFF; border: none;
        border-radius: 6px; padding: 6px 20px; font-weight: 600; min-height: 22px;
    }
    QPushButton:hover   { background-color: #005BB5; }
    QPushButton:pressed { background-color: #004A94; }
    QPushButton:disabled { background-color: #B0D4F1; color: #FFFFFF; }
"""

_SEARCH_STYLE = """
    QLineEdit {
        border: 1px solid #D1D1D6; border-radius: 6px;
        padding: 5px 10px; font-size: 13px;
        background-color: #FFFFFF;
    }
    QLineEdit:focus { border-color: #0071E3; }
"""

_LIST_STYLE = """
    QListWidget {
        border: 1px solid #D1D1D6; border-radius: 6px;
        background-color: #FFFFFF; font-size: 12px;
    }
    QListWidget::item { padding: 3px 8px; }
    QListWidget::item:selected {
        background-color: #0071E3; color: #FFFFFF;
    }
"""

_TABLE_STYLE = """
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
        text-align: left;
    }
"""

# Subtle column tints so the two parts are visually distinct.
_COL_A_TINT = QColor("#F0F4FF")   # faint blue
_COL_B_TINT = QColor("#FFF7EE")   # faint warm

_SECTION_LABEL_STYLE = "color: #6E6E73; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;"

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

_AB_BTN_STYLE = """
    QPushButton {
        border: 1px solid #D1D1D6; border-radius: 4px;
        padding: 2px 8px; font-size: 11px; font-weight: 600;
        min-width: 28px; max-width: 28px;
        background-color: #FAFAFA; color: #6E6E73;
    }
    QPushButton:hover { background-color: #E8E8ED; }
    QPushButton:checked { background-color: #0071E3; color: #FFFFFF; border-color: #0071E3; }
"""


def _thin_rule() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #E5E5EA;")
    f.setFixedHeight(1)
    return f


def _fmt(val: object) -> str:
    """Format a value for display, turning None into empty string."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return f"{val:g}"
    if isinstance(val, tuple):
        return ", ".join(str(v) for v in val)
    return str(val)


def _sig_rows(sig: PartSignature) -> list[tuple[str, str]]:
    """Extract non-empty signature fields as (label, value) pairs."""
    rows: list[tuple[str, str]] = []
    rows.append(("Family", sig.component_family.value.replace("_", " ").title()))

    _fields = [
        ("Value (ohms)", "value_ohms"),
        ("Value (pF)", "value_pf"),
        ("Mounting", "mounting"),
        ("Package", "package"),
        ("Wattage", "wattage"),
        ("Tolerance", "tolerance"),
        ("Voltage Rating", "voltage_rating"),
        ("Polarized", "polarized"),
        ("Dielectric", "dielectric"),
        ("Connector Type", "connector_subtype"),
        ("Pin Count", "pin_count"),
        ("Row Count", "row_count"),
        ("Pitch", "pitch_um"),
        ("Gender", "gender"),
        ("Shrouded", "shrouded"),
        ("Taper", "taper"),
        ("Body Size (mm)", "body_size_mm"),
        ("Shaft Style", "shaft_style"),
        ("Pole/Throw", "pole_throw"),
        ("Action Pattern", "action_pattern"),
        ("Momentary", "momentary_positions"),
        ("Base Device", "base_device"),
        ("Packing Suffix", "packing_suffix"),
        ("Orderable MPN", "orderable_mpn"),
    ]
    for label, attr in _fields:
        val = getattr(sig, attr, None)
        if val is not None:
            display = _fmt(val)
            if attr == "pitch_um" and isinstance(val, int):
                display = f"{val / 1000:.2f}mm"
            if attr == "connector_subtype":
                display = val.replace("_", " ")
            rows.append((label, display))
    return rows


class _PartPicker(QWidget):
    """A search field + results list that resolves to a single Part."""

    def __init__(self, context: AppContext, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._selected_part: Part | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel(label)
        hf = QFont()
        hf.setWeight(QFont.Weight.DemiBold)
        header.setFont(hf)
        header.setStyleSheet("color: #3A3A3C; font-size: 12px;")
        layout.addWidget(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name, alias, or SKU...")
        self._search.setStyleSheet(_SEARCH_STYLE)
        self._search.textChanged.connect(self._on_search)
        layout.addWidget(self._search)

        self._results = QListWidget()
        self._results.setStyleSheet(_LIST_STYLE)
        self._results.setMaximumHeight(150)
        self._results.currentItemChanged.connect(self._on_selected)
        layout.addWidget(self._results)

        self._selected_label = QLabel("")
        self._selected_label.setStyleSheet("color: #0071E3; font-size: 12px; font-weight: 600;")
        layout.addWidget(self._selected_label)

    @property
    def selected_part(self) -> Part | None:
        return self._selected_part

    def set_part(self, part: Part) -> None:
        """Programmatically set the selected part (e.g. from inventory selection)."""
        self._selected_part = part
        self._search.blockSignals(True)
        self._search.setText(part.name)
        self._search.blockSignals(False)
        self._results.clear()
        self._results.setVisible(False)
        self._selected_label.setText(f"#{part.id}  {part.name}")

    def _on_search(self, text: str) -> None:
        self._results.clear()
        self._results.setVisible(True)
        self._selected_part = None
        self._selected_label.setText("")
        query = text.strip()
        if len(query) < 2:
            return
        ids = self.context.search_service.search(query)
        if not ids:
            return
        for pid in ids[:20]:
            part = self.context.part_repo.get_part_by_id(pid)
            if part is None:
                continue
            cat = f"  [{part.category}]" if part.category else ""
            item = QListWidgetItem(f"{part.name}{cat}")
            item.setData(Qt.ItemDataRole.UserRole, part)
            self._results.addItem(item)

    def _on_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            self._selected_part = None
            self._selected_label.setText("")
            return
        part: Part = current.data(Qt.ItemDataRole.UserRole)
        self._selected_part = part
        self._selected_label.setText(f"#{part.id}  {part.name}")


class ManualMergeDialog(QDialog):
    """Pick any two parts and merge them directly."""

    def __init__(
        self,
        context: AppContext,
        preselected: list[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Manual Merge")
        self.setMinimumSize(860, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Title
        title = QLabel("Merge Two Parts")
        tf = QFont()
        tf.setPointSize(15)
        tf.setWeight(QFont.Weight.DemiBold)
        title.setFont(tf)
        root.addWidget(title)

        subtitle = QLabel("Select two parts to merge. All quantities, aliases, and BOM references will be combined.")
        subtitle.setStyleSheet("color: #6E6E73; font-size: 12px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Part pickers
        pickers = QHBoxLayout()
        pickers.setSpacing(16)
        self._picker_a = _PartPicker(context, "Part A (keep)")
        self._picker_b = _PartPicker(context, "Part B (remove)")
        pickers.addWidget(self._picker_a)
        pickers.addWidget(self._picker_b)
        root.addLayout(pickers)

        # Compare button
        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setStyleSheet(_BTN_PRIMARY)
        self._compare_btn.setFixedWidth(100)
        self._compare_btn.clicked.connect(self._do_compare)
        root.addWidget(self._compare_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addWidget(_thin_rule())

        # ── Detail container (hidden until compare) ──
        self._detail_container = QWidget()
        dl = QVBoxLayout(self._detail_container)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)

        # Chips (warnings / hard rejects)
        self._chips_label = QLabel("")
        self._chips_label.setWordWrap(True)
        self._chips_label.setStyleSheet("font-size: 11px; color: #6E6E73;")
        dl.addWidget(self._chips_label)

        # Scrollable comparison area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        self._tables_layout = QVBoxLayout(scroll_content)
        self._tables_layout.setContentsMargins(0, 0, 0, 0)
        self._tables_layout.setSpacing(12)
        scroll.setWidget(scroll_content)
        dl.addWidget(scroll)

        # Keep radios
        keep_row = QHBoxLayout()
        keep_row.setSpacing(14)
        kl = QLabel("Keep:")
        kl.setStyleSheet("font-weight: 600; color: #3A3A3C;")
        self._keep_group = QButtonGroup(self)
        self._keep_a_radio = QRadioButton("Part A")
        self._keep_b_radio = QRadioButton("Part B")
        self._keep_a_radio.setChecked(True)
        self._keep_group.addButton(self._keep_a_radio, 0)
        self._keep_group.addButton(self._keep_b_radio, 1)
        keep_row.addWidget(kl)
        keep_row.addWidget(self._keep_a_radio)
        keep_row.addWidget(self._keep_b_radio)
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
        of.setSpacing(6)
        self._override_rows: dict[str, tuple[QPushButton, QPushButton, QLineEdit]] = {}
        for field_name, label in _OVERRIDE_FIELD_DEFS:
            btn_a = QPushButton("A")
            btn_a.setCheckable(True)
            btn_a.setStyleSheet(_AB_BTN_STYLE)
            btn_b = QPushButton("B")
            btn_b.setCheckable(True)
            btn_b.setStyleSheet(_AB_BTN_STYLE)
            le = QLineEdit()
            le.setStyleSheet(_SEARCH_STYLE)
            # Wire A/B buttons to fill the field from the respective part
            btn_a.clicked.connect(lambda checked, fn=field_name: self._pick_field(fn, "a"))
            btn_b.clicked.connect(lambda checked, fn=field_name: self._pick_field(fn, "b"))
            # Un-check both buttons when user edits manually
            le.textEdited.connect(lambda text, fn=field_name: self._on_field_edited(fn))
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(btn_a)
            row_layout.addWidget(btn_b)
            row_layout.addWidget(le, 1)
            self._override_rows[field_name] = (btn_a, btn_b, le)
            of.addRow(label, row_widget)
        og_layout.addLayout(of)
        self._overrides_group.setLayout(og_layout)
        self._overrides_group.setVisible(False)
        dl.addWidget(self._overrides_group)

        # Update overrides when keep radio changes
        self._keep_group.buttonToggled.connect(self._refresh_overrides)

        dl.addWidget(_thin_rule())

        # Action buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._merge_btn = QPushButton("Merge")
        self._merge_btn.setStyleSheet(_BTN_PRIMARY)
        self._merge_btn.clicked.connect(self._do_merge)
        self._merge_btn.setEnabled(False)
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(self._merge_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        dl.addLayout(btns)

        self._detail_container.setVisible(False)
        root.addWidget(self._detail_container)

        # Pre-select parts and auto-compare if both provided
        if preselected and len(preselected) >= 2:
            pa = context.part_repo.get_part_by_id(preselected[0])
            pb = context.part_repo.get_part_by_id(preselected[1])
            if pa:
                self._picker_a.set_part(pa)
            if pb:
                self._picker_b.set_part(pb)
            if pa and pb:
                self._do_compare()

    # ── Compare ──────────────────────────────────────────────────────────

    def _do_compare(self) -> None:
        pa = self._picker_a.selected_part
        pb = self._picker_b.selected_part
        if pa is None or pb is None:
            QMessageBox.information(self, "Select Parts", "Please select both Part A and Part B.")
            return
        if pa.id == pb.id:
            QMessageBox.information(self, "Same Part", "Part A and Part B are the same part.")
            return

        self._part_a = pa
        self._part_b = pb

        sig_a = self.context.dedup_service.get_signature(pa)
        sig_b = self.context.dedup_service.get_signature(pb)
        self._sig_a = sig_a
        self._sig_b = sig_b

        from eurorack_inventory.services.dedup_conflicts import check_conflicts
        hard_rejects, warnings = check_conflicts(pa, pb, sig_a, sig_b)
        self._hard_rejects = hard_rejects
        self._warnings = warnings

        self._populate_comparison(pa, pb, sig_a, sig_b, hard_rejects, warnings)
        self._detail_container.setVisible(True)
        self._overrides_group.setVisible(True)
        self._merge_btn.setEnabled(True)
        self._refresh_overrides()

    # ── Override helpers ──────────────────────────────────────────────────

    def _pick_field(self, field_name: str, source: str) -> None:
        """Fill a field from Part A or Part B and highlight the chosen button."""
        btn_a, btn_b, le = self._override_rows[field_name]
        part = self._part_a if source == "a" else self._part_b
        val = getattr(part, field_name, None)
        le.setText(str(val) if val is not None else "")
        btn_a.setChecked(source == "a")
        btn_b.setChecked(source == "b")

    def _on_field_edited(self, field_name: str) -> None:
        """Un-check A/B buttons when user types a custom value."""
        btn_a, btn_b, _le = self._override_rows[field_name]
        btn_a.setChecked(False)
        btn_b.setChecked(False)

    def _refresh_overrides(self, *_args) -> None:
        """Pre-populate all override fields from the kept part."""
        if not hasattr(self, "_part_a"):
            return
        keep_a = self._keep_a_radio.isChecked()
        keep = self._part_a if keep_a else self._part_b
        remove = self._part_b if keep_a else self._part_a
        for field_name, _label in _OVERRIDE_FIELD_DEFS:
            btn_a, btn_b, le = self._override_rows[field_name]
            # Mirror the merge adopt-blank logic: use keeper's value, fall back to removed
            keeper_val = getattr(keep, field_name, None)
            remove_val = getattr(remove, field_name, None)
            if keeper_val is not None:
                le.setText(str(keeper_val))
                btn_a.setChecked(keep_a)
                btn_b.setChecked(not keep_a)
            elif remove_val is not None:
                le.setText(str(remove_val))
                btn_a.setChecked(not keep_a)
                btn_b.setChecked(keep_a)
            else:
                le.setText("")
                btn_a.setChecked(False)
                btn_b.setChecked(False)

    def _collect_overrides(self) -> dict[str, str | None] | None:
        """Collect override values that differ from what merge would produce."""
        keep_a = self._keep_a_radio.isChecked()
        keep = self._part_a if keep_a else self._part_b
        remove = self._part_b if keep_a else self._part_a
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

    # ── Build comparison tables ──────────────────────────────────────────

    def _populate_comparison(
        self, pa: Part, pb: Part,
        sig_a: PartSignature, sig_b: PartSignature,
        hard_rejects: list[str], warnings: list[str],
    ) -> None:
        from eurorack_inventory.ui.dedup_dialog import _CONFLICT_FIELD_MAP, _humanize

        # Clear previous tables
        while self._tables_layout.count():
            item = self._tables_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # ── Gather all data ──
        loc_a = self.context.part_repo.get_part_location(pa.id)
        loc_b = self.context.part_repo.get_part_location(pb.id)
        aliases_a = self.context.part_repo.list_aliases_for_part(pa.id)
        aliases_b = self.context.part_repo.list_aliases_for_part(pb.id)
        bom_a = self._get_bom_source_names(pa.id)
        bom_b = self._get_bom_source_names(pb.id)

        # Conflict field sets
        hard_fields: set[str] = set()
        warn_fields: set[str] = set()
        for r in hard_rejects:
            hard_fields.update(_CONFLICT_FIELD_MAP.get(r, []))
        for w in warnings:
            warn_fields.update(_CONFLICT_FIELD_MAP.get(w, []))

        # ── Section 1: Identity ──
        identity_rows = [
            ("ID", str(pa.id), str(pb.id)),
            ("Name", pa.name, pb.name),
            ("Category", pa.category or "", pb.category or ""),
            ("Fingerprint", pa.fingerprint or "", pb.fingerprint or ""),
        ]
        self._add_section("IDENTITY", identity_rows, hard_fields, warn_fields)

        # ── Section 2: Inventory ──
        inventory_rows = [
            ("Qty", str(pa.qty), str(pb.qty)),
            ("Location", loc_a or "", loc_b or ""),
            ("Storage Class", pa.storage_class_override or "", pb.storage_class_override or ""),
        ]
        self._add_section("INVENTORY", inventory_rows, hard_fields, warn_fields)

        # ── Section 3: Supplier & Sourcing ──
        sourcing_rows = [
            ("SKU", pa.supplier_sku or "", pb.supplier_sku or ""),
            ("MPN", pa.mpn or "", pb.mpn or ""),
            ("Manufacturer", pa.manufacturer or "", pb.manufacturer or ""),
            ("Supplier", pa.supplier_name or "", pb.supplier_name or ""),
            ("Package", pa.default_package or "", pb.default_package or ""),
            ("URL", pa.purchase_url or "", pb.purchase_url or ""),
        ]
        self._add_section("SUPPLIER & SOURCING", sourcing_rows, hard_fields, warn_fields)

        # ── Section 4: References ──
        alias_str_a = ", ".join(a.alias for a in aliases_a) if aliases_a else ""
        alias_str_b = ", ".join(a.alias for a in aliases_b) if aliases_b else ""
        bom_str_a = ", ".join(bom_a) if bom_a else ""
        bom_str_b = ", ".join(bom_b) if bom_b else ""
        ref_rows = [
            ("Aliases", alias_str_a, alias_str_b),
            ("BOM Sources", bom_str_a, bom_str_b),
        ]
        self._add_section("REFERENCES", ref_rows, hard_fields, warn_fields)

        # ── Section 5: Parsed Signature ──
        sig_rows_a = _sig_rows(sig_a)
        sig_rows_b = _sig_rows(sig_b)
        # Merge into aligned rows by label
        all_labels: list[str] = []
        seen: set[str] = set()
        for label, _ in sig_rows_a + sig_rows_b:
            if label not in seen:
                all_labels.append(label)
                seen.add(label)
        dict_a = dict(sig_rows_a)
        dict_b = dict(sig_rows_b)
        sig_rows = [(label, dict_a.get(label, ""), dict_b.get(label, "")) for label in all_labels]
        self._add_section("PARSED SIGNATURE", sig_rows, hard_fields, warn_fields)

        # ── Section 6: Notes & Dates ──
        meta_rows = [
            ("Notes", pa.notes or "", pb.notes or ""),
            ("Created", pa.created_at or "", pb.created_at or ""),
            ("Updated", pa.updated_at or "", pb.updated_at or ""),
        ]
        self._add_section("NOTES & DATES", meta_rows, hard_fields, warn_fields)

        # ── Slot conflict ──
        conflict = (pa.slot_id and pb.slot_id and pa.slot_id != pb.slot_id)
        self._slot_container.setVisible(bool(conflict))
        if conflict:
            self._slot_a_radio.setText(loc_a or f"#{pa.slot_id}")
            self._slot_b_radio.setText(loc_b or f"#{pb.slot_id}")
            self._slot_a_radio.setChecked(True)

        # ── Chips ──
        parts: list[str] = []
        for r in hard_rejects:
            parts.append(f'<span style="color:#C62828">{_humanize(r)}</span>')
        for w in warnings:
            parts.append(f'<span style="color:#E65100">{_humanize(w)}</span>')
        self._chips_label.setText(" \u00b7 ".join(parts) if parts else "")

    def _add_section(
        self,
        title: str,
        rows: list[tuple[str, str, str]],
        hard_fields: set[str],
        warn_fields: set[str],
    ) -> None:
        """Add a labelled section with a comparison table."""
        label = QLabel(title)
        label.setStyleSheet(_SECTION_LABEL_STYLE)
        self._tables_layout.addWidget(label)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["", "Part A", "Part B"])
        hh = table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setStyleSheet(_TABLE_STYLE)

        table.setRowCount(len(rows))
        lbl_font = QFont()
        lbl_font.setWeight(QFont.Weight.DemiBold)

        for i, (field_label, va, vb) in enumerate(rows):
            li = QTableWidgetItem(field_label)
            li.setFont(lbl_font)
            li.setForeground(QColor("#6E6E73"))
            table.setItem(i, 0, li)

            ia = QTableWidgetItem(va)
            ib = QTableWidgetItem(vb)

            # Default column tints
            bg_a = _COL_A_TINT
            bg_b = _COL_B_TINT

            if field_label in hard_fields:
                bg_a = _RED; bg_b = _RED
            elif field_label in warn_fields:
                bg_a = _AMBER; bg_b = _AMBER
            elif va and vb and va == vb:
                bg_a = _GREEN; bg_b = _GREEN
            elif va and vb:
                bg_a = _GRAY_DIFF; bg_b = _GRAY_DIFF

            ia.setBackground(bg_a)
            ib.setBackground(bg_b)

            table.setItem(i, 1, ia)
            table.setItem(i, 2, ib)

        # Label column fixed, data columns split evenly
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 120)
        # Fixed height: header + rows, no scrollbar inside individual tables
        row_h = table.verticalHeader().defaultSectionSize()
        header_h = table.horizontalHeader().height()
        table.setFixedHeight(header_h + row_h * len(rows) + 4)

        self._tables_layout.addWidget(table)

    def _get_bom_source_names(self, part_id: int) -> list[str]:
        """Get BOM source names that reference this part."""
        rows = self.context.db.query_all(
            """
            SELECT DISTINCT bs.module_name
            FROM bom_lines bl
            JOIN bom_sources bs ON bs.id = bl.module_id
            WHERE bl.part_id = ?
            ORDER BY bs.module_name
            """,
            (part_id,),
        )
        return [r["module_name"] for r in rows]

    # ── Merge ────────────────────────────────────────────────────────────

    def _do_merge(self) -> None:
        pa = self._part_a
        pb = self._part_b

        keep_a = self._keep_a_radio.isChecked()
        keep = pa if keep_a else pb
        remove = pb if keep_a else pa

        slot_id = None
        if pa.slot_id and pb.slot_id and pa.slot_id != pb.slot_id:
            slot_id = pa.slot_id if self._slot_a_radio.isChecked() else pb.slot_id

        # Build warning text
        warning_lines = f'Merge "{remove.name}" into "{keep.name}"?\n\n'
        warning_lines += "Quantities, aliases, and BOM references will be combined.\n"
        if self._hard_rejects:
            warning_lines += (
                "\nThe dedup system flagged conflicts between these parts:\n"
                + ", ".join(r.replace("_", " ") for r in self._hard_rejects)
                + "\n\nAre you sure you want to override and merge anyway?"
            )

        reply = QMessageBox.question(
            self, "Confirm Merge",
            warning_lines,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.context.dedup_service.merge_parts(
                keep.id, remove.id, keep_slot_id=slot_id,
                sig_a=self._sig_a, sig_b=self._sig_b,
                overrides=self._collect_overrides(),
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Merge Failed", str(exc))
            return

        QMessageBox.information(
            self, "Merged",
            f'Successfully merged "{remove.name}" into "{keep.name}".',
        )
        self.accept()
