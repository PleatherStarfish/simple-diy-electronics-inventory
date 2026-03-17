from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.assignment import AssignmentScope, AssignmentService


class AssignmentDialog(QDialog):
    def __init__(
        self,
        assignment_service: AssignmentService,
        categories: list[str],
        selected_part_ids: list[int] | None = None,
        parent: QWidget | None = None,
        part_repo: PartRepository | None = None,
        storage_repo: StorageRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self.assignment_service = assignment_service
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self._initial_part_ids: set[int] = set(selected_part_ids or [])
        self.setWindowTitle("Auto-Assign Parts to Storage")
        self.setMinimumWidth(520)
        self._build_ui(categories)

    def _build_ui(self, categories: list[str]) -> None:
        layout = QVBoxLayout(self)

        # Mode group
        mode_box = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_box)
        self._mode_group = QButtonGroup(self)
        self._radio_incremental = QRadioButton("Incremental (unassigned only)")
        self._radio_rebuild = QRadioButton("Full rebuild (reassign everything)")
        self._radio_incremental.setChecked(True)
        self._mode_group.addButton(self._radio_incremental, 0)
        self._mode_group.addButton(self._radio_rebuild, 1)
        mode_layout.addWidget(self._radio_incremental)
        mode_layout.addWidget(self._radio_rebuild)
        layout.addWidget(mode_box)

        # Scope group
        scope_box = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_box)
        self._scope_group = QButtonGroup(self)
        self._radio_all = QRadioButton("All parts")
        self._radio_selected = QRadioButton("Selected parts (0)")
        self._radio_selected.setEnabled(True)  # always enabled — dialog has its own picker
        self._radio_category = QRadioButton("By category:")
        self._radio_all.setChecked(True)
        self._scope_group.addButton(self._radio_all, 0)
        self._scope_group.addButton(self._radio_selected, 1)
        self._scope_group.addButton(self._radio_category, 2)
        scope_layout.addWidget(self._radio_all)
        scope_layout.addWidget(self._radio_selected)

        scope_layout.addWidget(self._radio_category)
        self._category_list = QListWidget()
        self._category_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for cat in categories:
            item = QListWidgetItem(cat)
            self._category_list.addItem(item)
        self._category_list.setMaximumHeight(120)
        self._category_list.setEnabled(False)
        self._category_list.hide()
        scope_layout.addWidget(self._category_list)

        # Part selection table (shown when "Selected parts" is active)
        self._part_table = QTableWidget()
        self._part_table.setColumnCount(4)
        self._part_table.setHorizontalHeaderLabels(["Name", "Category", "Qty", "Location"])
        self._part_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._part_table.verticalHeader().setVisible(False)
        self._part_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._part_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self._part_table.setMaximumHeight(200)
        self._part_table.hide()
        self._part_table_hint = QLabel("Select parts in the table above, then click Preview or Run.")
        self._part_table_hint.setWordWrap(True)
        self._part_table_hint.hide()
        scope_layout.addWidget(self._part_table)
        scope_layout.addWidget(self._part_table_hint)

        # Scope match count
        self._scope_count_label = QLabel("")
        self._scope_count_label.setWordWrap(True)
        scope_layout.addWidget(self._scope_count_label)

        layout.addWidget(scope_box)

        self._scope_group.idToggled.connect(self._on_scope_changed)
        self._part_table.itemSelectionChanged.connect(self._on_part_selection_changed)
        self._category_list.itemSelectionChanged.connect(self._update_scope_count)

        # Populate part table and cache parts for counting
        self._all_parts: list = []
        self._part_ids_by_row: list[int] = []
        self._populate_part_table()

        # Target container group
        target_box = QGroupBox("Target Container")
        target_layout = QVBoxLayout(target_box)

        self._target_combo = QComboBox()
        self._target_combo.addItem("Any (all containers)", userData=None)
        if self.storage_repo:
            for c in self.storage_repo.list_containers():
                if c.name != "Unassigned":
                    self._target_combo.addItem(c.name, userData=c.id)
        target_layout.addWidget(self._target_combo)

        # Soft quantity filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Prioritize parts with qty"))
        self._qty_op_combo = QComboBox()
        self._qty_op_combo.addItems(["<", "<=", ">", ">="])
        self._qty_op_combo.setFixedWidth(60)
        filter_row.addWidget(self._qty_op_combo)
        self._qty_threshold_spin = QSpinBox()
        self._qty_threshold_spin.setRange(0, 999999)
        self._qty_threshold_spin.setValue(20)
        filter_row.addWidget(self._qty_threshold_spin)
        self._qty_filter_widget = QWidget()
        self._qty_filter_widget.setLayout(filter_row)
        self._qty_filter_widget.setEnabled(False)
        self._qty_filter_widget.setToolTip(
            "Parts matching this filter get first pick of slots in the target container.\n"
            "Remaining slots are still filled by other parts."
        )
        target_layout.addWidget(self._qty_filter_widget)

        layout.addWidget(target_box)

        self._target_combo.currentIndexChanged.connect(self._on_target_changed)

        # Action buttons row
        btn_row = QHBoxLayout()
        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setToolTip("Show what would happen without making changes")
        self._preview_btn.clicked.connect(self._preview_assignment)
        btn_row.addWidget(self._preview_btn)

        self._run_btn = QPushButton("Run Assignment")
        self._run_btn.clicked.connect(self._run_assignment)
        btn_row.addWidget(self._run_btn)

        self._undo_btn = QPushButton("Undo Last")
        self._undo_btn.setToolTip("Undo the most recent assignment run")
        self._undo_btn.clicked.connect(self._undo_last)
        btn_row.addWidget(self._undo_btn)
        layout.addLayout(btn_row)

        # Results
        self._results_label = QLabel("Results will appear here after running.")
        self._results_label.setWordWrap(True)
        layout.addWidget(self._results_label)

        self._results_text = QTextEdit()
        self._results_text.setReadOnly(True)
        self._results_text.setMaximumHeight(180)
        self._results_text.hide()
        layout.addWidget(self._results_text)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._update_undo_state()

    def _populate_part_table(self) -> None:
        """Fill the part selection table with all parts from the repo."""
        if self.part_repo is None:
            return

        parts = self.part_repo.list_parts()
        self._all_parts = parts
        self._part_ids_by_row.clear()
        self._part_table.setRowCount(len(parts))

        for row, part in enumerate(parts):
            self._part_ids_by_row.append(part.id)

            name_item = QTableWidgetItem(part.name or "")
            name_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._part_table.setItem(row, 0, name_item)

            cat_item = QTableWidgetItem(part.category or "")
            cat_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._part_table.setItem(row, 1, cat_item)

            qty_item = QTableWidgetItem(str(part.qty))
            qty_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._part_table.setItem(row, 2, qty_item)

            location = ""
            if part.slot_id is not None and self.storage_repo is not None:
                slot = self.storage_repo.get_slot(part.slot_id)
                if slot is not None:
                    container = self.storage_repo.get_container(slot.container_id)
                    if container is not None:
                        location = f"{container.name} / {slot.label}"
            loc_item = QTableWidgetItem(location)
            loc_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._part_table.setItem(row, 3, loc_item)

        # Pre-select rows matching initial selection
        if self._initial_part_ids:
            self._part_table.blockSignals(True)
            for row, pid in enumerate(self._part_ids_by_row):
                if pid in self._initial_part_ids:
                    self._part_table.selectRow(row)
            self._part_table.blockSignals(False)

        self._update_selected_label()
        self._update_scope_count()

    def _get_selected_part_ids(self) -> list[int]:
        """Return part IDs for currently selected rows in the part table."""
        selected_rows = {idx.row() for idx in self._part_table.selectionModel().selectedRows()}
        return [
            self._part_ids_by_row[row]
            for row in sorted(selected_rows)
            if row < len(self._part_ids_by_row)
        ]

    def _update_selected_label(self) -> None:
        """Update the radio button label with current selection count."""
        count = len(self._get_selected_part_ids())
        self._radio_selected.setText(f"Selected parts ({count})")

    def _on_scope_changed(self, button_id: int, checked: bool) -> None:
        if checked:
            self._category_list.setEnabled(button_id == 2)
            self._category_list.setVisible(button_id == 2)
            show_table = button_id == 1
            self._part_table.setVisible(show_table)
            self._part_table_hint.setVisible(show_table)
            self._update_scope_count()

    def _on_target_changed(self, index: int) -> None:
        has_target = self._target_combo.currentData() is not None
        self._qty_filter_widget.setEnabled(has_target)
        # Full rebuild + specific target is dangerous — disable it
        if has_target:
            if self._radio_rebuild.isChecked():
                self._radio_incremental.setChecked(True)
            self._radio_rebuild.setEnabled(False)
        else:
            self._radio_rebuild.setEnabled(True)

    def _on_part_selection_changed(self) -> None:
        self._update_selected_label()
        self._update_scope_count()

    def _update_scope_count(self) -> None:
        """Update the label showing how many parts match the current scope."""
        scope_id = self._scope_group.checkedId()
        if scope_id == 0:  # All parts
            count = len(self._all_parts)
        elif scope_id == 1:  # Selected parts
            count = len(self._get_selected_part_ids())
        elif scope_id == 2:  # By category
            cats = {item.text().lower() for item in self._category_list.selectedItems()}
            count = sum(1 for p in self._all_parts if (p.category or "").lower() in cats)
        else:
            count = 0
        self._scope_count_label.setText(f"{count} parts match current scope")

    def _validate_scope(self) -> bool:
        """Check scope is valid. Shows a warning and returns False if not."""
        scope_id = self._scope_group.checkedId()
        if scope_id == 1 and not self._get_selected_part_ids():
            QMessageBox.warning(
                self, "No parts selected",
                "Select at least one part in the table, or choose a different scope.",
            )
            return False
        if scope_id == 2 and not self._category_list.selectedItems():
            QMessageBox.warning(
                self, "No categories selected",
                "Select at least one category, or choose a different scope.",
            )
            return False
        return True

    def _update_undo_state(self) -> None:
        latest = self.assignment_service.get_latest_run()
        self._undo_btn.setEnabled(latest is not None)

    def _preview_assignment(self) -> None:
        if not self._validate_scope():
            return
        mode = "full_rebuild" if self._radio_rebuild.isChecked() else "incremental"
        scope = self._build_scope()
        plan = self.assignment_service.plan(mode, scope)

        lines = [
            f"Preview ({mode}):",
            f"  Would assign: {len(plan.assignments)} parts",
            f"  Would remain unassigned: {len(plan.unassigned_part_ids)} parts",
            "",
        ]

        # Resolve assignments to human-readable names
        if plan.assignments and self.part_repo and self.storage_repo:
            lines.append("Assignments:")
            for part_id, slot_id in plan.assignments[:20]:
                p = self.part_repo.get_part_by_id(part_id)
                s = self.storage_repo.get_slot(slot_id)
                c = self.storage_repo.get_container(s.container_id) if s else None
                part_name = p.name if p else f"#{part_id}"
                loc = f"{c.name} / {s.label}" if c and s else f"slot #{slot_id}"
                lines.append(f"  {part_name} -> {loc}")
            if len(plan.assignments) > 20:
                lines.append(f"  ... and {len(plan.assignments) - 20} more")
            lines.append("")

        if plan.unassigned_part_ids:
            lines.append("Unassigned parts:")
            for pid in plan.unassigned_part_ids[:20]:
                p = self.part_repo.get_part_by_id(pid) if self.part_repo else None
                reason = plan.reason_for(pid)
                name = p.name if p else f"#{pid}"
                lines.append(f"  {name}: {reason}")
            if len(plan.unassigned_part_ids) > 20:
                lines.append(f"  ... and {len(plan.unassigned_part_ids) - 20} more")
            lines.append("")
            lines.append("Additional storage needed:")
            lines.append(f"  Small cells: {plan.estimate.small_short_cells_needed}")
            lines.append(f"  Large cells: {plan.estimate.large_cells_needed}")
            lines.append(f"  Long cells: {plan.estimate.long_cells_needed}")
            lines.append(f"  Binder cards: {plan.estimate.binder_cards_needed}")

        self._results_label.setText(
            f"Preview: {len(plan.assignments)} would be assigned, "
            f"{len(plan.unassigned_part_ids)} unassigned"
        )
        self._results_text.setPlainText("\n".join(lines))
        self._results_text.show()

    def _run_assignment(self) -> None:
        if not self._validate_scope():
            return
        mode = "full_rebuild" if self._radio_rebuild.isChecked() else "incremental"

        if mode == "full_rebuild":
            reply = QMessageBox.warning(
                self,
                "Confirm Full Rebuild",
                "This will clear ALL existing storage assignments and reassign from scratch.\n\n"
                "Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        scope = self._build_scope()
        result = self.assignment_service.assign(mode, scope)

        lines = [
            f"Assigned: {result.assigned_count} parts",
            f"Unassigned: {result.unassigned_count} parts",
            "",
            "Additional storage needed:",
            f"  Small cells: {result.estimate.small_short_cells_needed}",
            f"  Large cells: {result.estimate.large_cells_needed}",
            f"  Long cells: {result.estimate.long_cells_needed}",
            f"  Binder cards: {result.estimate.binder_cards_needed}",
        ]
        self._results_label.setText(
            f"Done: {result.assigned_count} assigned, {result.unassigned_count} unassigned"
        )
        self._results_text.setPlainText("\n".join(lines))
        self._results_text.show()
        self._update_undo_state()

    def _undo_last(self) -> None:
        latest = self.assignment_service.get_latest_run()
        if latest is None:
            QMessageBox.information(self, "Undo", "No assignment runs to undo.")
            return

        reply = QMessageBox.question(
            self,
            "Undo Assignment",
            f"Undo assignment run #{latest['id']} ({latest['mode']})?\n\n"
            "Parts will be restored to their previous locations.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        restored, conflicts = self.assignment_service.undo_run(latest["id"])

        if conflicts:
            conflict_text = "\n".join(conflicts)
            QMessageBox.warning(
                self,
                "Undo Conflicts",
                f"Restored {restored} parts, but {len(conflicts)} conflicts found:\n\n"
                f"{conflict_text}\n\n"
                "These parts were moved since the assignment and were not restored.",
            )
        else:
            self._results_label.setText(f"Undo complete: {restored} parts restored.")
            self._results_text.hide()

        self._update_undo_state()

    def _build_scope(self) -> AssignmentScope:
        scope_id = self._scope_group.checkedId()
        if scope_id == 1:
            part_ids = self._get_selected_part_ids()
            scope = AssignmentScope(all_parts=False, part_ids=part_ids)
        elif scope_id == 2:
            cats = [item.text() for item in self._category_list.selectedItems()]
            scope = AssignmentScope(all_parts=False, categories=cats)
        else:
            scope = AssignmentScope(all_parts=True)

        # Target container
        scope.target_container_id = self._target_combo.currentData()

        # Soft quantity filter (only when a target container is selected)
        if scope.target_container_id is not None:
            scope.qty_filter_op = self._qty_op_combo.currentText()
            scope.qty_filter_threshold = self._qty_threshold_spin.value()

        return scope
