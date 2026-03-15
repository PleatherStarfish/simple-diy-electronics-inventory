from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStatusBar,
    QTabWidget,
    QTableView,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.ui.assignment_dialog import AssignmentDialog
from eurorack_inventory.ui.inventory_screen import InventoryScreen
from eurorack_inventory.ui.modules_screen import ModulesScreen
from eurorack_inventory.ui.settings_dialog import SettingsDialog
from eurorack_inventory.ui.storage_screen import StorageScreen
from eurorack_inventory.ui.models import AuditTableModel


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, db_path: Path) -> None:
        super().__init__()
        self.context = context
        self.db_path = db_path
        self.setWindowTitle("Simple DIY Synth Inventory")
        self.resize(1400, 900)

        self.inventory_screen = InventoryScreen(context)
        self.storage_screen = StorageScreen(context)
        self.modules_screen = ModulesScreen(context)

        tabs = QTabWidget()
        tabs.addTab(self.inventory_screen, "Inventory")
        tabs.addTab(self.storage_screen, "Storage")
        tabs.addTab(self.modules_screen, "Modules")
        self.setCentralWidget(tabs)

        self._build_log_dock()
        self._build_audit_dock()
        self._build_menu_bar()
        self._build_status_bar()
        self.refresh_all()

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        import_action = QAction("&Import Parts...", self)
        import_action.setToolTip("Import parts from an Excel spreadsheet (.xlsx)")
        import_action.triggered.connect(self.import_spreadsheet)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.audit_dock.toggleViewAction())
        view_menu.addAction(self.log_dock.toggleViewAction())

        # Tools menu
        tools_menu = menu_bar.addMenu("&Tools")

        reindex_action = QAction("&Reindex Search", self)
        reindex_action.setToolTip("Rebuild the search index")
        reindex_action.triggered.connect(self.rebuild_search)
        tools_menu.addAction(reindex_action)

        bootstrap_action = QAction("&Load Sample Data", self)
        bootstrap_action.setToolTip("Create example storage containers")
        bootstrap_action.triggered.connect(self.bootstrap_demo_storage)
        tools_menu.addAction(bootstrap_action)

        assign_action = QAction("&Auto-Assign Storage...", self)
        assign_action.setToolTip("Automatically assign parts to storage locations")
        assign_action.triggered.connect(self.open_assignment_dialog)
        tools_menu.addAction(assign_action)

        settings_action = QAction("&Settings...", self)
        settings_action.setToolTip("Configure classifier thresholds and assignment targets")
        settings_action.triggered.connect(self.open_settings_dialog)
        tools_menu.addAction(settings_action)

        tools_menu.addSeparator()

        refresh_action = QAction("Re&fresh", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(self.refresh_all)
        tools_menu.addAction(refresh_action)

    def _build_log_dock(self) -> None:
        self.log_dock = QDockWidget("Runtime Log", self)
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_dock.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        for message in self.context.log_handler.get_messages():
            self.log_view.appendPlainText(message)
        self.context.log_handler.add_listener(self.log_view.appendPlainText)

    def _build_audit_dock(self) -> None:
        self.audit_dock = QDockWidget("Audit Events", self)
        self.audit_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.audit_table = QTableView()
        self.audit_model = AuditTableModel([])
        self.audit_table.setModel(self.audit_model)
        self.audit_table.horizontalHeader().setStretchLastSection(True)
        self.audit_dock.setWidget(self.audit_table)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.audit_dock)
        self.audit_dock.hide()

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.status_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)

    def refresh_all(self) -> None:
        self.inventory_screen.refresh_inventory()
        self.inventory_screen.refresh_current_detail()
        self.storage_screen.refresh()
        self.modules_screen.refresh()
        snapshot = self.context.dashboard_service.snapshot()
        self.status_label.setText(
            f"DB: {self.db_path} | parts={snapshot['parts']} "
            f"| containers={snapshot['containers']} | modules={snapshot['modules']}"
        )
        self.audit_model.update_rows(snapshot["recent_events"])

    def rebuild_search(self) -> None:
        self.context.search_service.rebuild()
        self.refresh_all()

    def bootstrap_demo_storage(self) -> None:
        self.context.storage_service.bootstrap_demo_storage()
        self.refresh_all()

    def open_assignment_dialog(self) -> None:
        categories = self.context.part_repo.list_distinct_categories()
        selected_ids = self.inventory_screen.selected_part_ids()
        dialog = AssignmentDialog(
            assignment_service=self.context.assignment_service,
            categories=categories,
            selected_part_ids=selected_ids,
            parent=self,
        )
        dialog.exec()
        self.refresh_all()

    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(
            settings_repo=self.context.settings_repo,
            parent=self,
        )
        dialog.exec()

    def import_spreadsheet(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Import spreadsheet",
            str(self.db_path.parent),
            "Excel Files (*.xlsx *.xls)",
        )
        if not filename:
            return
        try:
            report = self.context.import_service.import_file(filename, mode="replace_snapshot")
            self.context.search_service.rebuild()
            self.refresh_all()
            QMessageBox.information(self, "Import complete", report.summary())
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
