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
from eurorack_inventory.ui.projects_screen import ProjectsScreen
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
        self.projects_screen = ProjectsScreen(context)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.inventory_screen, "Inventory")
        self.tabs.addTab(self.storage_screen, "Storage")
        self.tabs.addTab(self.projects_screen, "Projects")
        self.setCentralWidget(self.tabs)

        # Wire find-in-storage
        self.inventory_screen.find_in_storage_requested.connect(self._on_find_in_storage)

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

        export_backup_action = QAction("Export &Backup...", self)
        export_backup_action.setToolTip("Export a full database backup")
        export_backup_action.triggered.connect(self._export_backup)
        file_menu.addAction(export_backup_action)

        restore_backup_action = QAction("&Restore Backup...", self)
        restore_backup_action.setToolTip("Restore the database from a backup file")
        restore_backup_action.triggered.connect(self._restore_backup)
        file_menu.addAction(restore_backup_action)

        file_menu.addSeparator()

        export_csv_action = QAction("Export as &CSV...", self)
        export_csv_action.setToolTip("Export all data as CSV files in a zip archive")
        export_csv_action.triggered.connect(self._export_csv)
        file_menu.addAction(export_csv_action)

        import_csv_action = QAction("Import from CS&V...", self)
        import_csv_action.setToolTip("Import data from a CSV zip archive")
        import_csv_action.triggered.connect(self._import_csv)
        file_menu.addAction(import_csv_action)

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

        undo_action = QAction("&Undo Last Assignment", self)
        undo_action.setToolTip("Undo the most recent auto-assignment run")
        undo_action.triggered.connect(self._undo_last_assignment)
        tools_menu.addAction(undo_action)

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
        self.projects_screen.refresh()
        snapshot = self.context.dashboard_service.snapshot()
        self.status_label.setText(
            f"DB: {self.db_path} | parts={snapshot['parts']} "
            f"| containers={snapshot['containers']} | projects={snapshot['projects']}"
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
            part_repo=self.context.part_repo,
            storage_repo=self.context.storage_repo,
        )
        dialog.exec()
        self.refresh_all()

    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(
            settings_repo=self.context.settings_repo,
            parent=self,
        )
        dialog.exec()

    def _on_find_in_storage(self, slot_id: int) -> None:
        self.tabs.setCurrentWidget(self.storage_screen)
        self.storage_screen.highlight_slot(slot_id)

    def _undo_last_assignment(self) -> None:
        latest = self.context.assignment_service.get_latest_run()
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
        restored, conflicts = self.context.assignment_service.undo_run(latest["id"])
        if conflicts:
            QMessageBox.warning(
                self, "Undo Conflicts",
                f"Restored {restored} parts, but {len(conflicts)} conflicts:\n\n"
                + "\n".join(conflicts),
            )
        else:
            QMessageBox.information(self, "Undo", f"Restored {restored} parts.")
        self.refresh_all()

    def _export_csv(self) -> None:
        from eurorack_inventory.services.csv_backup import (
            CSVBackupError,
            default_csv_backup_filename,
            export_csv,
        )

        default_path = str(self.db_path.parent / default_csv_backup_filename())
        dest, _filter = QFileDialog.getSaveFileName(
            self,
            "Export as CSV",
            default_path,
            "Zip Archive (*.zip)",
        )
        if not dest:
            return

        try:
            result = export_csv(self.context.db.conn, Path(dest))
            QMessageBox.information(
                self, "CSV Export complete", f"CSV archive saved to:\n{result}"
            )
        except CSVBackupError as exc:
            QMessageBox.critical(self, "CSV Export failed", str(exc))

    def _import_csv(self) -> None:
        from eurorack_inventory.services.csv_backup import (
            CSVBackupError,
            import_csv,
            validate_csv_archive,
        )

        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Import from CSV",
            str(self.db_path.parent),
            "Zip Archive (*.zip)",
        )
        if not filename:
            return

        archive_path = Path(filename).resolve()

        # Validate first
        try:
            validate_csv_archive(archive_path)
        except CSVBackupError as exc:
            QMessageBox.critical(self, "Invalid CSV archive", str(exc))
            return

        reply = QMessageBox.warning(
            self,
            "Confirm CSV Import",
            f"This will REPLACE all current data with the contents of:\n"
            f"{archive_path}\n\n"
            "This operation cannot be undone.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            counts = import_csv(archive_path, self.context.db.conn)
            total = sum(counts.values())
            self.context.search_service.rebuild()
            self.refresh_all()
            QMessageBox.information(
                self,
                "CSV Import complete",
                f"Imported {total} rows across {len(counts)} tables.",
            )
        except CSVBackupError as exc:
            QMessageBox.critical(self, "CSV Import failed", str(exc))

    def _export_backup(self) -> None:
        from eurorack_inventory.services.backup import (
            BackupError,
            default_backup_filename,
            export_backup,
        )

        default_path = str(self.db_path.parent / default_backup_filename())
        dest, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Backup",
            default_path,
            "SQLite Database (*.db)",
        )
        if not dest:
            return

        dest_path = Path(dest).resolve()
        if dest_path == self.db_path.resolve():
            QMessageBox.critical(
                self,
                "Export failed",
                "Cannot export over the live database file.\nChoose a different location.",
            )
            return

        try:
            result = export_backup(self.context.db.conn, dest_path)
            QMessageBox.information(
                self, "Export complete", f"Backup saved to:\n{result}"
            )
        except BackupError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _restore_backup(self) -> None:
        from eurorack_inventory.services.backup import (
            BackupError,
            restore_backup,
            validate_backup,
        )

        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Restore Backup",
            str(self.db_path.parent),
            "SQLite Database (*.db)",
        )
        if not filename:
            return

        backup_path = Path(filename).resolve()
        if backup_path == self.db_path.resolve():
            QMessageBox.critical(
                self,
                "Restore failed",
                "Cannot restore from the live database file itself.\n"
                "Choose a different backup file.",
            )
            return

        # Validate first so we can show errors before the scary dialog
        try:
            validate_backup(backup_path)
        except BackupError as exc:
            QMessageBox.critical(self, "Invalid backup", str(exc))
            return

        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            f"This will REPLACE all current data with the backup:\n"
            f"{backup_path}\n\n"
            "A safety copy of the current database will be created first.\n\n"
            "The application will close after restoring. "
            "Relaunch to use the restored data.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            safety = restore_backup(
                backup_path,
                self.db_path,
                live_conn=self.context.db.conn,
            )
            QMessageBox.information(
                self,
                "Restore complete",
                f"Database restored from:\n{backup_path}\n\n"
                f"Safety copy saved at:\n{safety}\n\n"
                "The application will now close.",
            )
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()
        except BackupError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))

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
