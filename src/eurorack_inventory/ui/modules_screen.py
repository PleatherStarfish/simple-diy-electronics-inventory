from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QInputDialog,
)
from PySide6.QtCore import Qt

from eurorack_inventory.app import AppContext
from eurorack_inventory.ui.models import ModuleTableModel
from PySide6.QtWidgets import QTableView


class ModulesScreen(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_module_id: int | None = None

        self.module_model = ModuleTableModel([])
        self.module_table = QTableView()
        self.module_table.setModel(self.module_model)
        self.module_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.module_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.module_table.horizontalHeader().setStretchLastSection(True)
        self.module_table.verticalHeader().setVisible(False)
        self.module_table.clicked.connect(self._on_module_clicked)

        self.module_name = QLabel("Select a module")
        self.module_meta = QLabel("")
        self.build_list = QListWidget()
        self.availability_table = QTableWidget()
        self.availability_table.setColumnCount(4)
        self.availability_table.setHorizontalHeaderLabels(["Part ID", "Need", "Have", "Enough"])
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.create_build_btn = QPushButton("Start New Build")
        self.create_build_btn.setToolTip("Create a new build instance and check part availability")
        self.create_build_btn.clicked.connect(self._create_build)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.module_table)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.module_name)
        right_layout.addWidget(self.module_meta)
        right_layout.addWidget(QLabel("Availability"))
        right_layout.addWidget(self.availability_table)
        right_layout.addWidget(QLabel("Builds"))
        right_layout.addWidget(self.build_list)
        right_layout.addWidget(self.create_build_btn)
        right_layout.addWidget(QLabel("Notes"))
        right_layout.addWidget(self.notes_text)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([450, 650])

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def refresh(self) -> None:
        rows = self.context.module_service.list_modules()
        self.module_model.update_rows(rows)
        if rows and self.current_module_id is None:
            self.load_module(rows[0].id)

    def _on_module_clicked(self, index) -> None:
        module_id = self.module_model.module_id_at(index.row())
        if module_id is not None:
            self.load_module(module_id)

    def load_module(self, module_id: int) -> None:
        module = self.context.module_repo.get_module(module_id)
        if module is None:
            return
        self.current_module_id = module_id
        self.module_name.setText(module.name)
        self.module_meta.setText(f"{module.maker} | revision {module.revision or 'n/a'}")
        self.notes_text.setPlainText(module.notes or "")
        availability = self.context.module_service.get_module_availability(module_id)
        self.availability_table.setRowCount(len(availability))
        for row_idx, row in enumerate(availability):
            self.availability_table.setItem(row_idx, 0, QTableWidgetItem(str(row["part_id"])))
            self.availability_table.setItem(row_idx, 1, QTableWidgetItem(str(row["qty_required"])))
            self.availability_table.setItem(row_idx, 2, QTableWidgetItem(str(row["qty_available"])))
            self.availability_table.setItem(row_idx, 3, QTableWidgetItem("Yes" if row["enough_stock"] else "No"))
        builds = self.context.module_service.list_builds(module_id)
        self.build_list.clear()
        for build in builds:
            self.build_list.addItem(f"{build.status} | {build.nickname or '(unnamed)'}")

    def _create_build(self) -> None:
        if self.current_module_id is None:
            QMessageBox.information(self, "Select a module", "Select a module first.")
            return
        nickname, ok = QInputDialog.getText(self, "Create build", "Build nickname:")
        if not ok:
            return
        try:
            self.context.module_service.create_build(
                module_id=self.current_module_id,
                nickname=nickname.strip() or None,
            )
            self.load_module(self.current_module_id)
        except Exception as exc:
            QMessageBox.critical(self, "Create build failed", str(exc))
