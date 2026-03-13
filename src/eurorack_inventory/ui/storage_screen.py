from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QInputDialog,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.domain.enums import ContainerType
from eurorack_inventory.ui.models import ContainerListModel


class StorageScreen(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_container_id: int | None = None

        self.container_model = ContainerListModel([])
        self.container_list = QListView()
        self.container_list.setModel(self.container_model)
        self.container_list.clicked.connect(self._on_container_clicked)

        self.container_name = QLabel("")
        self.container_type = QLabel("")
        self.container_meta = QLabel("")
        self.grid_table = QTableWidget()
        self.grid_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grid_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.slot_table = QTableWidget()
        self.slot_table.setColumnCount(3)
        self.slot_table.setHorizontalHeaderLabels(["Label", "Type", "Notes"])
        self.slot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.new_slot_edit = QLineEdit()
        self.new_slot_edit.setPlaceholderText("Compartment label, e.g. A0, Card 17")
        self.create_slot_btn = QPushButton("Add Compartment")
        self.create_slot_btn.setToolTip("Create a named compartment within this container")
        self.create_slot_btn.clicked.connect(self._create_slot)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Containers"))
        left_layout.addWidget(self.container_list)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        detail_group = QGroupBox("Container Details")
        detail_layout = QFormLayout()
        detail_layout.addRow("Name", self.container_name)
        detail_layout.addRow("Type", self.container_type)
        detail_layout.addRow("Metadata", self.container_meta)
        detail_group.setLayout(detail_layout)

        new_slot_row = QHBoxLayout()
        new_slot_row.addWidget(self.new_slot_edit)
        new_slot_row.addWidget(self.create_slot_btn)

        right_layout = QVBoxLayout()
        right_layout.addWidget(detail_group)
        right_layout.addWidget(QLabel("Visual Layout"))
        right_layout.addWidget(self.grid_table)
        right_layout.addWidget(QLabel("Compartments"))
        right_layout.addLayout(new_slot_row)
        right_layout.addWidget(self.slot_table)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([220, 900])

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def refresh(self) -> None:
        containers = self.context.storage_service.list_containers()
        self.container_model.update_rows(containers)
        if containers and self.current_container_id is None:
            self.load_container(containers[0].id)

    def _on_container_clicked(self, index) -> None:
        container = self.container_model.container_at(index.row())
        if container is not None:
            self.load_container(container.id)

    def load_container(self, container_id: int) -> None:
        container = self.context.storage_repo.get_container(container_id)
        if container is None:
            return
        self.current_container_id = container_id
        self.container_name.setText(container.name)
        self.container_type.setText(container.container_type)
        self.container_meta.setText(str(container.metadata))
        slots = self.context.storage_service.list_slots(container_id)

        self.slot_table.setRowCount(len(slots))
        for row_idx, slot in enumerate(slots):
            self.slot_table.setItem(row_idx, 0, QTableWidgetItem(slot.label))
            self.slot_table.setItem(row_idx, 1, QTableWidgetItem(slot.slot_type))
            self.slot_table.setItem(row_idx, 2, QTableWidgetItem(slot.notes or ""))

        if container.container_type == ContainerType.GRID_BOX.value:
            self._render_grid_container(container, slots)
        else:
            self._render_non_grid_container(container, slots)

    def _render_grid_container(self, container, slots) -> None:
        rows = int(container.metadata.get("rows", 0))
        cols = int(container.metadata.get("cols", 0))
        self.grid_table.clear()
        self.grid_table.setRowCount(rows)
        self.grid_table.setColumnCount(cols)
        self.grid_table.setHorizontalHeaderLabels([str(i) for i in range(cols)])
        self.grid_table.setVerticalHeaderLabels(
            [self._row_label(i) for i in range(rows)]
        )

        occupancy = defaultdict(list)
        for slot in slots:
            if None in (slot.x1, slot.y1, slot.x2, slot.y2):
                continue
            for row in range(slot.y1, slot.y2 + 1):
                for col in range(slot.x1, slot.x2 + 1):
                    occupancy[(row, col)].append(slot.label)

        for row in range(rows):
            for col in range(cols):
                labels = occupancy.get((row, col), [])
                item = QTableWidgetItem("\n".join(labels))
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.grid_table.setItem(row, col, item)

    def _render_non_grid_container(self, container, slots) -> None:
        self.grid_table.clear()
        self.grid_table.setRowCount(max(1, len(slots)))
        self.grid_table.setColumnCount(1)
        self.grid_table.setHorizontalHeaderLabels(["Slots"])
        self.grid_table.setVerticalHeaderLabels([""] * max(1, len(slots)))
        if slots:
            for row, slot in enumerate(slots):
                item = QTableWidgetItem(slot.label)
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.grid_table.setItem(row, 0, item)
        else:
            self.grid_table.setItem(0, 0, QTableWidgetItem("No slots yet"))

    @staticmethod
    def _row_label(index: int) -> str:
        index += 1
        chars: list[str] = []
        while index:
            index, remainder = divmod(index - 1, 26)
            chars.append(chr(ord("A") + remainder))
        return "".join(reversed(chars))

    def _create_slot(self) -> None:
        if self.current_container_id is None:
            return
        label = self.new_slot_edit.text().strip()
        if not label:
            return
        try:
            self.context.storage_service.get_or_create_slot(
                container_id=self.current_container_id,
                label=label,
            )
            self.new_slot_edit.clear()
            self.load_container(self.current_container_id)
        except Exception as exc:
            QMessageBox.critical(self, "Create slot failed", str(exc))
