from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.services.bom_extractor import (
    format_pdf_runtime_error,
    get_pdf_runtime_status,
)
from eurorack_inventory.ui.bom_match_dialog import BomMatchDialog
from eurorack_inventory.ui.bom_models import (
    BomSourceListModel,
    NormalizedBomTableModel,
    RawBomTableModel,
)
from eurorack_inventory.ui.shopping_list_dialog import ShoppingListDialog

logger = logging.getLogger(__name__)


class BomsScreen(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_source_id: int | None = None
        self._last_loaded_source_id: int | None = None
        self._all_norm_items: list = []

        # Left panel: source list
        self.source_model = BomSourceListModel()
        self.source_list = QListView()
        self.source_list.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.source_list.setModel(self.source_model)
        self.source_list.clicked.connect(self._on_source_clicked)
        self.source_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.source_list.customContextMenuRequested.connect(self._source_context_menu)

        self.import_csv_btn = QPushButton("Import CSV...")
        self.import_csv_btn.clicked.connect(self._import_csv)

        self.import_pdf_btn = QPushButton("Import PDF...")
        self.import_pdf_btn.clicked.connect(self._import_pdf)

        self.import_dir_btn = QPushButton("Import Directory...")
        self.import_dir_btn.clicked.connect(self._import_dir)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_source)

        # Right panel: side-by-side tables
        self.raw_model = RawBomTableModel()
        self.raw_table = QTableView()
        self.raw_table.setModel(self.raw_model)
        self.raw_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.raw_table.horizontalHeader().setStretchLastSection(True)
        self.raw_table.verticalHeader().setVisible(False)

        self.norm_model = NormalizedBomTableModel()
        self.norm_table = QTableView()
        self.norm_table.setModel(self.norm_model)
        self.norm_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.norm_table.horizontalHeader().setStretchLastSection(True)
        self.norm_table.verticalHeader().setVisible(False)
        self.norm_table.doubleClicked.connect(self._on_norm_double_click)
        self.norm_model.cell_edited.connect(self._on_cell_edited)

        # Context menu on normalized table
        self.norm_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.norm_table.customContextMenuRequested.connect(self._norm_context_menu)

        # Filter combo for parts list
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Matched", "Unmatched"])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)

        # Action buttons
        self.auto_match_btn = QPushButton("Auto-Match All")
        self.auto_match_btn.clicked.connect(self._auto_match)
        self.shopping_btn = QPushButton("Shopping List...")
        self.shopping_btn.clicked.connect(self._shopping_list)
        self.promote_btn = QPushButton("Promote to Project")
        self.promote_btn.clicked.connect(self._promote)
        self.re_normalize_btn = QPushButton("Re-Normalize")
        self.re_normalize_btn.clicked.connect(self._re_normalize)

        # PDF viewer (lazy-initialized)
        self._pdf_doc = None
        self._pdf_view = None

        # Source tabs: "As Imported" table + "Source PDF" viewer
        self.source_tabs = QTabWidget()
        self.source_tabs.addTab(self.raw_table, "As Imported")
        self._pdf_placeholder = QLabel("No PDF available")
        self._pdf_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_tabs.addTab(self._pdf_placeholder, "Source PDF")
        self.source_tabs.setTabEnabled(1, False)

        # Issues banner
        self.issues_label = QLabel()
        self.issues_label.setWordWrap(True)
        self.issues_label.setMaximumHeight(40)
        self.issues_label.setStyleSheet(
            "background-color: #FFF3CD; color: #856404; "
            "border: 1px solid #FFEEBA; border-radius: 4px; "
            "padding: 4px 10px; font-size: 12px;"
        )
        self.issues_label.setVisible(False)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        # Left panel
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("BOM Sources"))
        left_layout.addWidget(self.source_list)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.import_csv_btn)
        btn_row.addWidget(self.import_pdf_btn)
        left_layout.addLayout(btn_row)
        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(self.import_dir_btn)
        btn_row2.addWidget(self.delete_btn)
        left_layout.addLayout(btn_row2)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        # Right panel: source tabs + parts list side by side
        table_splitter = QSplitter(Qt.Orientation.Horizontal)

        norm_container = QWidget()
        norm_layout = QVBoxLayout()
        norm_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Parts List"))
        filter_row.addStretch()
        filter_row.addWidget(QLabel("Show:"))
        filter_row.addWidget(self.filter_combo)
        norm_layout.addLayout(filter_row)
        norm_layout.addWidget(self.norm_table)
        norm_container.setLayout(norm_layout)

        table_splitter.addWidget(self.source_tabs)
        table_splitter.addWidget(norm_container)
        table_splitter.setSizes([400, 500])

        # Action bar
        action_layout = QHBoxLayout()
        action_layout.addWidget(self.auto_match_btn)
        action_layout.addWidget(self.re_normalize_btn)
        action_layout.addStretch()
        action_layout.addWidget(self.shopping_btn)
        action_layout.addWidget(self.promote_btn)

        right_layout = QVBoxLayout()
        right_layout.addWidget(table_splitter)
        right_layout.addWidget(self.issues_label)
        right_layout.addLayout(action_layout)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([250, 750])

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def refresh(self) -> None:
        sources = self.context.bom_service.list_bom_sources()
        counts = self.context.bom_repo.get_confirmation_counts()
        self.source_model.update_rows(sources, counts)
        if not sources:
            self.current_source_id = None
            self._clear_loaded_source()
            return
        if self.current_source_id is not None:
            row_index = self.source_model.row_for_source_id(self.current_source_id)
            if row_index >= 0:
                self._load_source(self.current_source_id)
                self._select_source(self.current_source_id)
                return
        self._load_source(sources[0].id)
        self._select_source(sources[0].id)

    def _on_source_clicked(self, index) -> None:
        source = self.source_model.source_at(index.row())
        if source is not None:
            self._load_source(source.id)

    def _load_source(self, source_id: int) -> None:
        source_changed = source_id != self._last_loaded_source_id
        self.current_source_id = source_id
        self._last_loaded_source_id = source_id
        source = self.context.bom_repo.get_bom_source(source_id)
        raw_items = self.context.bom_repo.list_raw_items(source_id)
        self._all_norm_items = self.context.bom_repo.list_normalized_items(source_id)
        self.raw_model.update_rows(raw_items)
        self._apply_filter()
        self._update_pdf_tab(source, switch_tab=source_changed)
        self._update_issues_banner(source, raw_items, self._all_norm_items)

    def _apply_filter(self) -> None:
        idx = self.filter_combo.currentIndex()
        if idx == 0:  # All
            filtered = self._all_norm_items
        elif idx == 1:  # Matched
            filtered = [
                i for i in self._all_norm_items
                if i.match_status in ("auto_matched", "manually_matched")
            ]
        else:  # Unmatched
            filtered = [
                i for i in self._all_norm_items
                if i.match_status == "unmatched"
            ]
        self.norm_model.update_rows(filtered)

    def _clear_loaded_source(self) -> None:
        self.raw_model.update_rows([])
        self.norm_model.update_rows([])
        self._all_norm_items = []
        self.source_tabs.setTabEnabled(1, False)
        self.issues_label.setVisible(False)
        if self._pdf_doc is not None:
            self._pdf_doc.close()

    # ── PDF viewer ───────────────────────────────────────────────────

    def _ensure_pdf_viewer(self) -> None:
        if self._pdf_view is not None:
            return
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView

            self._pdf_doc = QPdfDocument(self)
            self._pdf_view = QPdfView(self)
            self._pdf_view.setDocument(self._pdf_doc)
            self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except ImportError:
            logger.warning("QtPdf/QtPdfWidgets not available for PDF viewing")
            return

    def _update_pdf_tab(self, source, *, switch_tab: bool = False) -> None:
        if source is None:
            self.source_tabs.setTabEnabled(1, False)
            return
        if source.source_kind == "pdf" and Path(source.file_path).exists():
            self._ensure_pdf_viewer()
            if self._pdf_view is not None:
                self.source_tabs.removeTab(1)
                self.source_tabs.insertTab(1, self._pdf_view, "Source PDF")
                self.source_tabs.setTabEnabled(1, True)
                self._pdf_doc.load(source.file_path)
                if switch_tab:
                    self.source_tabs.setCurrentIndex(1)
            else:
                self.source_tabs.setTabEnabled(1, False)
        else:
            self.source_tabs.setTabEnabled(1, False)
            if self._pdf_doc is not None:
                self._pdf_doc.close()
            if switch_tab:
                self.source_tabs.setCurrentIndex(0)

    # ── Issues banner ────────────────────────────────────────────────

    def _update_issues_banner(self, source, raw_items, norm_items) -> None:
        flags = []
        raw_count = len(raw_items)
        norm_count = len(norm_items)

        # High dropout rate
        if raw_count > 5 and norm_count < raw_count:
            dropout_pct = int((raw_count - norm_count) / raw_count * 100)
            if dropout_pct > 40:
                flags.append(
                    f"{raw_count - norm_count} of {raw_count} imported lines "
                    f"were not recognized ({dropout_pct}% filtered)"
                )

        # Unmatched items
        unmatched = sum(1 for i in norm_items if i.match_status == "unmatched")
        if unmatched > 0:
            flags.append(f"{unmatched} item(s) have no inventory match")

        # Unclassified items
        other_type = sum(1 for i in norm_items if i.component_type == "other")
        if other_type > 0:
            flags.append(f"{other_type} item(s) could not be classified")

        # Source file missing
        if source is not None and not Path(source.file_path).exists():
            flags.append("Original source file not found on disk")

        if flags:
            self.issues_label.setText(" | ".join(flags))
            self.issues_label.setVisible(True)
        else:
            self.issues_label.setVisible(False)

    def _select_source(self, source_id: int) -> None:
        row_index = self.source_model.row_for_source_id(source_id)
        if row_index < 0:
            return
        model_index = self.source_model.index(row_index, 0)
        selection_model = self.source_list.selectionModel()
        if selection_model is not None:
            selection_model.setCurrentIndex(
                model_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        self.source_list.scrollTo(model_index)

    # ── Import ──────────────────────────────────────────────────────

    def _import_csv(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import BOM CSV", "", "CSV Files (*.csv)"
        )
        if not paths:
            return
        self._run_import([Path(p) for p in paths], "csv")

    def _import_pdf(self) -> None:
        runtime_status = get_pdf_runtime_status()
        if not runtime_status.available:
            QMessageBox.warning(
                self,
                "PDF Import Unavailable",
                format_pdf_runtime_error(runtime_status),
            )
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import BOM PDFs", "", "PDF Files (*.pdf *.PDF)"
        )
        if not paths:
            return
        self._run_import([Path(p) for p in paths], "pdf")

    def _import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Import BOM Directory")
        if not path:
            return
        self._run_import([Path(path)], "dir")

    def _run_import(self, paths: list[Path], mode: str) -> None:
        total = len(paths)
        progress = QProgressDialog(
            "Preparing import…", "Cancel", 0, total, self
        )
        progress.setWindowTitle("Importing BOMs")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        sources = []
        errors = []
        for i, path in enumerate(paths):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"Importing {i + 1} of {total}: {path.name}")
            progress.setValue(i)
            QApplication.processEvents()
            try:
                if mode == "csv":
                    sources.extend(self.context.bom_service.import_csv(path))
                elif mode == "pdf":
                    sources.append(self.context.bom_service.import_pdf(path))
                elif mode == "dir":
                    sources.extend(self.context.bom_service.import_directory(path))
            except Exception as e:
                errors.append(f"{path.name}: {e}")
                logger.warning("Failed to import %s: %s", path.name, e)

        progress.setValue(total)
        progress.close()

        if not sources and not errors:
            QMessageBox.warning(self, "Import", "No BOM data found.")
            return

        if sources:
            imported_source_id = sources[0].id
            self.context.search_service.rebuild()
            self.current_source_id = imported_source_id
            self._last_loaded_source_id = None  # Force tab switch on next load
            self.refresh()
            self._select_source(imported_source_id)
        elif self.current_source_id is not None:
            self._load_source(self.current_source_id)

        msg = f"Imported {len(sources)} BOM source(s)."
        if errors:
            msg += f"\n\n{len(errors)} failed:\n" + "\n".join(errors)
            QMessageBox.warning(self, "Import", msg)
        else:
            QMessageBox.information(self, "Import", msg)

    # ── Delete ──────────────────────────────────────────────────────

    def _delete_source(self) -> None:
        selection = self.source_list.selectionModel()
        if selection is None:
            return
        selected_indexes = selection.selectedRows()
        if not selected_indexes:
            return

        sources = []
        for idx in selected_indexes:
            source = self.source_model.source_at(idx.row())
            if source is not None:
                sources.append(source)
        if not sources:
            return

        if len(sources) == 1:
            msg = (
                f"Delete BOM source '{sources[0].module_name}'?\n\n"
                "This will remove all raw and normalized items."
            )
        else:
            names = "\n".join(f"  - {s.module_name}" for s in sources)
            msg = (
                f"Delete {len(sources)} BOM sources?\n\n"
                f"{names}\n\n"
                "This will remove all raw and normalized items."
            )

        reply = QMessageBox.question(
            self,
            "Delete BOM",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for source in sources:
            self.context.bom_service.delete_source(source.id)
        self.current_source_id = None
        self.refresh()

    # ── Rename ─────────────────────────────────────────────────────

    def _source_context_menu(self, pos) -> None:
        index = self.source_list.indexAt(pos)
        if not index.isValid():
            return
        source = self.source_model.source_at(index.row())
        if source is None:
            return
        menu = QMenu(self)
        rename_action = menu.addAction("Rename...")
        relink_action = None
        if not Path(source.file_path).exists():
            relink_action = menu.addAction("Relink File...")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.source_list.viewport().mapToGlobal(pos))
        if action == rename_action:
            self._rename_source(source)
        elif action is not None and action == relink_action:
            self._relink_source(source)
        elif action == delete_action:
            self._delete_source()

    def _relink_source(self, source) -> None:
        ext_filter = (
            "PDF Files (*.pdf *.PDF)"
            if source.source_kind == "pdf"
            else "CSV Files (*.csv)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Locate file for '{source.module_name}'",
            "",
            ext_filter,
        )
        if not path:
            return
        self.context.bom_service.relink_source_file(source.id, Path(path))
        self._load_source(source.id)

    def _rename_source(self, source) -> None:
        new_name, ok = QInputDialog.getText(
            self, "Rename BOM Source", "New name:", text=source.module_name
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == source.module_name:
            return
        self.context.bom_service.rename_source(source.id, new_name)
        self.refresh()

    # ── Matching ────────────────────────────────────────────────────

    def _auto_match(self) -> None:
        if self.current_source_id is None:
            return
        self.context.search_service.rebuild()
        matched = self.context.bom_service.auto_match_bom(self.current_source_id)
        self._load_source(self.current_source_id)
        QMessageBox.information(self, "Auto-Match", f"Matched {matched} item(s).")

    def _on_norm_double_click(self, index) -> None:
        item = self.norm_model.item_at(index.row())
        if item is None or item.id is None:
            return
        # If double-clicking on an editable column, let default editing happen
        if index.column() in self.norm_model._EDITABLE_COLUMNS:
            return
        # Otherwise, open match dialog
        self._open_match_dialog(item)

    def _norm_context_menu(self, pos) -> None:
        index = self.norm_table.indexAt(pos)
        if not index.isValid():
            return
        item = self.norm_model.item_at(index.row())
        if item is None or item.id is None:
            return
        menu = QMenu(self)
        match_action = menu.addAction("Match / Edit Part...")
        action = menu.exec(self.norm_table.viewport().mapToGlobal(pos))
        if action == match_action:
            self._open_match_dialog(item)

    def _open_match_dialog(self, item) -> None:
        dialog = BomMatchDialog(
            self,
            item=item,
            matching_service=self.context.bom_service.matching,
            bom_repo=self.context.bom_repo,
            part_repo=self.context.part_repo,
            bom_service=self.context.bom_service,
        )
        if dialog.exec():
            self.context.search_service.rebuild()
            self._load_source(self.current_source_id)

    # ── Cell editing ────────────────────────────────────────────────

    def _on_cell_edited(self, item_id: int, column: int, value) -> None:
        field_map = {0: "component_type", 1: "normalized_value", 2: "qty", 3: "package_hint"}
        field = field_map.get(column)
        if field is None:
            return
        if field == "qty":
            try:
                value = int(value)
            except (ValueError, TypeError):
                return
        elif isinstance(value, str):
            value = value.strip()
            if not value:
                value = None
        with self.context.db.transaction():
            self.context.bom_repo.update_normalized_item(item_id, **{field: value})
            self.context.bom_repo.update_normalized_item(item_id, is_verified=False)
        self._load_source(self.current_source_id)

    # ── Shopping list ───────────────────────────────────────────────

    def _shopping_list(self) -> None:
        sources = self.context.bom_service.list_bom_sources()
        if not sources:
            QMessageBox.information(self, "Shopping List", "No BOM sources available.")
            return
        dialog = ShoppingListDialog(
            self,
            bom_service=self.context.bom_service,
            sources=sources,
        )
        dialog.exec()

    # ── Promote ─────────────────────────────────────────────────────

    def _promote(self) -> None:
        if self.current_source_id is None:
            return
        try:
            project = self.context.bom_service.promote_to_project(self.current_source_id)
            main_window = self.window()
            if hasattr(main_window, "refresh_all"):
                main_window.refresh_all()
            else:
                self.refresh()
            QMessageBox.information(
                self,
                "Promoted",
                f"Created project '{project.name}' (ID {project.id}).",
            )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot Promote", str(e))

    # ── Re-normalize ────────────────────────────────────────────────

    def _re_normalize(self) -> None:
        if self.current_source_id is None:
            return
        count = self.context.bom_service.re_normalize(self.current_source_id)
        self._load_source(self.current_source_id)
        QMessageBox.information(self, "Re-Normalize", f"Re-normalized {count} item(s).")
