from __future__ import annotations

import json
import random
import string

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDrag, QPen, QPixmap, QPainter, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QLineEdit,
)

from eurorack_inventory.app import AppContext
from eurorack_inventory.domain.enums import CellLength, CellSize, ContainerType, SlotType
from eurorack_inventory.domain.models import Part, StorageSlot
from eurorack_inventory.ui.models import ContainerListModel
from eurorack_inventory.ui.storage_config_dialog import StorageConfigDialog

_DRAG_MIME_TYPE = "application/x-synth-inventory-part"

# Color scheme for cell properties — empty cells
_CELL_COLORS_EMPTY = {
    (CellSize.SMALL.value, CellLength.SHORT.value): QColor(230, 230, 230),      # light gray
    (CellSize.LARGE.value, CellLength.SHORT.value): QColor(198, 226, 236),      # pale blue
    (CellSize.SMALL.value, CellLength.LONG.value): QColor(206, 236, 206),       # pale green
    (CellSize.LARGE.value, CellLength.LONG.value): QColor(255, 221, 170),       # pale orange
}
# Color scheme for cell properties — filled cells (slightly more saturated)
_CELL_COLORS_FILLED = {
    (CellSize.SMALL.value, CellLength.SHORT.value): QColor(200, 200, 200),      # medium gray
    (CellSize.LARGE.value, CellLength.SHORT.value): QColor(145, 200, 220),      # blue
    (CellSize.SMALL.value, CellLength.LONG.value): QColor(150, 215, 150),       # green
    (CellSize.LARGE.value, CellLength.LONG.value): QColor(240, 180, 100),       # orange
}
_DEFAULT_CELL_COLOR = QColor(240, 240, 240)
# Binder card colors by fill state
_BINDER_CARD_EMPTY_COLOR = QColor(230, 230, 230)       # light gray
_BINDER_CARD_PARTIAL_COLOR = QColor(178, 215, 225)     # soft teal — in use, has room
_BINDER_CARD_FULL_COLOR = QColor(240, 195, 120)        # warm amber — full
_GRID_CELL_MIN_HEIGHT = 52
_GRID_CELL_PADDING = 6
_GRID_CELL_CORNER_RADIUS = 7
_GRID_CELL_SELECTION_ROLE = Qt.ItemDataRole.UserRole + 1
_GRID_CELL_SLOT_LABEL_ROLE = Qt.ItemDataRole.UserRole + 2
_GRID_CELL_OCCUPIED_ROLE = Qt.ItemDataRole.UserRole + 3
_GRID_CELL_DROP_TARGET_ROLE = Qt.ItemDataRole.UserRole + 4
_GRID_CELL_BORDER_COLOR = QColor(29, 29, 31, 28)
_GRID_CELL_SELECTION_BORDER_COLOR = QColor(0, 113, 227)
_GRID_CELL_SELECTION_FILL_COLOR = QColor(0, 113, 227, 32)
_GRID_CELL_DROP_BORDER_COLOR = QColor(46, 174, 52)
_GRID_CELL_DROP_FILL_COLOR = QColor(46, 174, 52, 40)


class StorageGridDelegate(QStyledItemDelegate):
    """Paint grid cells directly so spans and selection stay slot-based."""

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if "\n" in text:
            # Multi-line content (e.g. binder cards): measure actual text height
            fm = option.fontMetrics
            padding = _GRID_CELL_PADDING * 2 + 4  # top/bottom padding + card margin
            text_width = option.rect.width() - padding if option.rect.width() > 0 else 200
            br = fm.boundingRect(0, 0, text_width, 0,
                                 Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                                 text)
            return QSize(option.rect.width(), max(br.height() + padding, _GRID_CELL_MIN_HEIGHT))
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), _GRID_CELL_MIN_HEIGHT))
        return hint

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(bg, QBrush):
            bg_color = bg.color()
        elif isinstance(bg, QColor):
            bg_color = bg
        else:
            bg_color = _DEFAULT_CELL_COLOR

        is_selected = bool(index.data(_GRID_CELL_SELECTION_ROLE))
        is_drop_target = bool(index.data(_GRID_CELL_DROP_TARGET_ROLE))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)

        card_rect = option.rect.adjusted(2, 2, -2, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(card_rect, _GRID_CELL_CORNER_RADIUS, _GRID_CELL_CORNER_RADIUS)

        # Border: drop target > selection > default
        if is_drop_target:
            border_color = _GRID_CELL_DROP_BORDER_COLOR
            border_width = 2
            fill_brush = _GRID_CELL_DROP_FILL_COLOR
        elif is_selected:
            border_color = _GRID_CELL_SELECTION_BORDER_COLOR
            border_width = 2
            fill_brush = _GRID_CELL_SELECTION_FILL_COLOR
        else:
            border_color = _GRID_CELL_BORDER_COLOR
            border_width = 1
            fill_brush = Qt.BrushStyle.NoBrush

        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(fill_brush)
        painter.drawRoundedRect(card_rect, _GRID_CELL_CORNER_RADIUS, _GRID_CELL_CORNER_RADIUS)

        if text:
            text_rect = card_rect.adjusted(
                _GRID_CELL_PADDING,
                _GRID_CELL_PADDING - 1,
                -_GRID_CELL_PADDING,
                -_GRID_CELL_PADDING,
            )
            font = option.font
            font.setBold(is_selected)
            painter.setFont(font)
            painter.setPen(QColor(29, 29, 31))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                text,
            )

        painter.restore()


class StorageGridTable(QTableWidget):
    """Grid table with click signals and drag-and-drop for parts."""

    left_clicked = Signal(QPoint)
    part_dropped = Signal(int, int, int)  # part_id, source_slot_id, target_slot_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_start_pos: QPoint | None = None
        self._drag_initiated: bool = False
        self._drop_target_row: int = -1
        self._drop_target_col: int = -1
        # Lookup callbacks set by StorageScreen
        self._slot_at_pos = None  # callable(QPoint) -> StorageSlot | None
        self._parts_for_slot = None  # callable(int) -> list[Part]
        self._pick_part_for_drag = None  # callable(list[Part], QPoint) -> Part | None

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._drag_initiated:
            self.left_clicked.emit(event.position().toPoint())
        self._drag_start_pos = None
        self._drag_initiated = False
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self._drag_initiated = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start_pos is None
            or not (event.buttons() & Qt.MouseButton.LeftButton)
            or self._slot_at_pos is None
            or self._parts_for_slot is None
        ):
            super().mouseMoveEvent(event)
            return

        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < 12:
            super().mouseMoveEvent(event)
            return

        # Past the drag threshold — this is a drag, not a click
        self._drag_initiated = True

        slot = self._slot_at_pos(self._drag_start_pos)
        if slot is None or slot.id is None:
            return

        parts = self._parts_for_slot(slot.id)
        if not parts:
            return

        # Pick which part to drag
        if len(parts) == 1:
            part = parts[0]
        elif self._pick_part_for_drag is not None:
            part = self._pick_part_for_drag(parts, self.mapToGlobal(self._drag_start_pos))
            if part is None:
                return
        else:
            part = parts[0]

        self._drag_start_pos = None

        # Build drag
        mime = QMimeData()
        payload = {"part_id": part.id, "source_slot_id": slot.id, "part_name": part.name}
        mime.setData(_DRAG_MIME_TYPE, json.dumps(payload).encode())

        drag = QDrag(self)
        drag.setMimeData(mime)

        # Build a small pixmap label
        pixmap = QPixmap(160, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(255, 255, 255, 220))
        p.setPen(QPen(QColor(80, 80, 80), 1))
        p.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 6, 6)
        p.setPen(QColor(29, 29, 31))
        f = QFont()
        f.setPointSize(11)
        p.setFont(f)
        p.drawText(pixmap.rect().adjusted(8, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, part.name)
        p.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 16))

        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_DRAG_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_DRAG_MIME_TYPE):
            event.ignore()
            return

        pos = event.position().toPoint()
        row = self.rowAt(pos.y())
        col = self.columnAt(pos.x())

        # Clear old highlight
        if (row != self._drop_target_row or col != self._drop_target_col):
            self._clear_drop_highlight()
            if row >= 0 and col >= 0:
                item = self.item(row, col)
                if item is not None:
                    item.setData(_GRID_CELL_DROP_TARGET_ROLE, True)
                    self.viewport().update(self.visualItemRect(item))
            self._drop_target_row = row
            self._drop_target_col = col

        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_highlight()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._clear_drop_highlight()

        if not event.mimeData().hasFormat(_DRAG_MIME_TYPE):
            event.ignore()
            return

        pos = event.position().toPoint()
        if self._slot_at_pos is None:
            event.ignore()
            return

        target_slot = self._slot_at_pos(pos)
        if target_slot is None or target_slot.id is None:
            event.ignore()
            return

        data = json.loads(bytes(event.mimeData().data(_DRAG_MIME_TYPE)).decode())
        part_id = data["part_id"]
        source_slot_id = data["source_slot_id"]

        if source_slot_id == target_slot.id:
            event.ignore()
            return

        self.part_dropped.emit(part_id, source_slot_id, target_slot.id)
        event.acceptProposedAction()

    def _clear_drop_highlight(self) -> None:
        if self._drop_target_row >= 0 and self._drop_target_col >= 0:
            item = self.item(self._drop_target_row, self._drop_target_col)
            if item is not None:
                item.setData(_GRID_CELL_DROP_TARGET_ROLE, False)
                self.viewport().update(self.visualItemRect(item))
        self._drop_target_row = -1
        self._drop_target_col = -1


_CHALLENGE_LENGTH = 6


class DeleteContainerDialog(QDialog):
    """Confirmation dialog that requires typing a random challenge string."""

    def __init__(self, container_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete Container")
        self.setMinimumWidth(400)

        self._challenge = "".join(
            random.choices(string.ascii_uppercase + string.digits, k=_CHALLENGE_LENGTH)
        )

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"You are about to permanently delete <b>{container_name}</b> "
            f"and all of its compartments.\n\n"
            f"Any parts assigned to this container will become unassigned.\n\n"
            f"This cannot be undone."
        ))
        layout.addWidget(QLabel(f"Type <b>{self._challenge}</b> to confirm:"))

        self._input = QLineEdit()
        self._input.setPlaceholderText(self._challenge)
        layout.addWidget(self._input)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("Delete")
        self._ok_btn.setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._input.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text: str) -> None:
        self._ok_btn.setEnabled(text.strip() == self._challenge)

    @property
    def challenge(self) -> str:
        return self._challenge


class StorageScreen(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_container_id: int | None = None
        self._slot_map: dict[tuple[int, int], StorageSlot] = {}
        self._slot_label_map: dict[str, StorageSlot] = {}
        self._slot_parts: dict[int, list[Part]] = {}
        self._selected_slot_labels: set[str] = set()
        self._slot_grid_pos: dict[str, tuple[int, int]] = {}
        self._grid_refresh_pending = False

        # --- Left panel: container list ---
        self.container_model = ContainerListModel([])
        self.container_list = QListView()
        self.container_list.setModel(self.container_model)
        self.container_list.clicked.connect(self._on_container_clicked)

        self.add_container_btn = QPushButton("Add Container")
        self.add_container_btn.clicked.connect(self._add_container)
        self.clone_container_btn = QPushButton("Clone Container")
        self.clone_container_btn.clicked.connect(self._clone_container)
        self.clone_container_btn.setEnabled(False)
        self.delete_container_btn = QPushButton("Delete Container")
        self.delete_container_btn.clicked.connect(self._delete_container)
        self.delete_container_btn.setEnabled(False)

        # --- Right panel: container details ---
        self.container_name = QLineEdit("")
        self.container_name.setPlaceholderText("Container name")
        self.container_name.editingFinished.connect(self._on_name_edited)
        self.container_type = QLabel("")
        self.container_meta = QLabel("")
        self.container_notes = QLineEdit("")
        self.container_notes.setPlaceholderText("Notes (optional)")
        self.container_notes.editingFinished.connect(self._on_notes_edited)

        # Grid visualization — selection disabled; we track clicks ourselves
        self.grid_table = StorageGridTable()
        self.grid_table.setItemDelegate(StorageGridDelegate(self.grid_table))
        self.grid_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grid_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grid_table.verticalHeader().setMinimumSectionSize(_GRID_CELL_MIN_HEIGHT)
        self.grid_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.grid_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_table.customContextMenuRequested.connect(self._on_grid_context_menu)
        self.grid_table.left_clicked.connect(self._on_grid_left_click)
        self.grid_table.part_dropped.connect(self._on_part_dropped)
        # Wire drag-and-drop callbacks
        self.grid_table._slot_at_pos = self._slot_at_grid_pos
        self.grid_table._parts_for_slot = lambda sid: self._slot_parts.get(sid, [])
        self.grid_table._pick_part_for_drag = self._pick_part_for_drag

        # Merge / unmerge / clear buttons
        self.merge_btn = QPushButton("Merge Selected")
        self.merge_btn.setToolTip("Merge selected cells into one region")
        self.merge_btn.clicked.connect(self._merge_selected)
        self.unmerge_btn = QPushButton("Unmerge")
        self.unmerge_btn.setToolTip("Split a merged cell back into individual cells")
        self.unmerge_btn.clicked.connect(self._unmerge_selected)
        self.clear_sel_btn = QPushButton("Clear Selection")
        self.clear_sel_btn.clicked.connect(self._clear_selection)

        # Resize controls
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 26)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 26)
        self.resize_btn = QPushButton("Resize")
        self.resize_btn.setToolTip("Change the number of rows/columns in this grid box")
        self.resize_btn.clicked.connect(self._resize_grid)
        self.resize_row = QHBoxLayout()
        self.resize_row.addWidget(QLabel("Rows:"))
        self.resize_row.addWidget(self.rows_spin)
        self.resize_row.addWidget(QLabel("Cols:"))
        self.resize_row.addWidget(self.cols_spin)
        self.resize_row.addWidget(self.resize_btn)
        self.resize_widget = QWidget()
        self.resize_widget.setLayout(self.resize_row)

        # Binder resize controls
        self.binder_cards_spin = QSpinBox()
        self.binder_cards_spin.setRange(1, 100)
        self.binder_resize_btn = QPushButton("Resize")
        self.binder_resize_btn.setToolTip("Change the number of cards in this binder")
        self.binder_resize_btn.clicked.connect(self._resize_binder)
        self.binder_resize_row = QHBoxLayout()
        self.binder_resize_row.addWidget(QLabel("Cards:"))
        self.binder_resize_row.addWidget(self.binder_cards_spin)
        self.binder_resize_row.addWidget(self.binder_resize_btn)
        self.binder_resize_widget = QWidget()
        self.binder_resize_widget.setLayout(self.binder_resize_row)

        # Slot table — columns are set dynamically per container type in load_container
        self.slot_table = QTableWidget()
        self.slot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Manual compartment creation
        self.new_slot_edit = QLineEdit()
        self.new_slot_edit.setPlaceholderText("Compartment label, e.g. A0, Card 17")
        self.create_slot_btn = QPushButton("Add Compartment")
        self.create_slot_btn.setToolTip("Create a named compartment within this container")
        self.create_slot_btn.clicked.connect(self._create_slot)

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Containers"))
        left_layout.addWidget(self.container_list)
        left_layout.addWidget(self.add_container_btn)
        left_layout.addWidget(self.clone_container_btn)
        left_layout.addWidget(self.delete_container_btn)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        detail_group = QGroupBox("Container Details")
        detail_layout = QFormLayout()
        detail_layout.addRow("Name", self.container_name)
        detail_layout.addRow("Type", self.container_type)
        detail_layout.addRow("Metadata", self.container_meta)
        detail_layout.addRow("Notes", self.container_notes)
        detail_group.setLayout(detail_layout)

        merge_row = QHBoxLayout()
        merge_row.addWidget(self.merge_btn)
        merge_row.addWidget(self.unmerge_btn)
        merge_row.addWidget(self.clear_sel_btn)

        new_slot_row = QHBoxLayout()
        new_slot_row.addWidget(self.new_slot_edit)
        new_slot_row.addWidget(self.create_slot_btn)

        right_layout = QVBoxLayout()
        right_layout.addWidget(detail_group)
        right_layout.addWidget(QLabel("Visual Layout"))
        right_layout.addWidget(self.grid_table)
        right_layout.addLayout(merge_row)
        right_layout.addWidget(self.resize_widget)
        right_layout.addWidget(self.binder_resize_widget)
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

    # --------------------------------------------------------- container list

    def refresh(self) -> None:
        containers = self.context.storage_service.list_containers()
        self.container_model.update_rows(containers)
        self._refresh_utilization()

        if not containers:
            self.current_container_id = None
            return

        if self.current_container_id is None:
            self.load_container(containers[0].id)
            return

        current_ids = {container.id for container in containers}
        if self.current_container_id in current_ids:
            self.load_container(self.current_container_id)
        else:
            self.load_container(containers[0].id)

    def _refresh_utilization(self) -> None:
        """Recompute and display utilization counts for all containers."""
        total_per_container = self.context.storage_repo.count_slots_per_container()
        occupied_per_container = self.context.part_repo.count_occupied_slots_per_container()
        util: dict[int, tuple[int, int]] = {
            cid: (occupied_per_container.get(cid, 0), total)
            for cid, total in total_per_container.items()
        }
        # For binder containers, show bag-level utilization instead of card-level
        containers = self.context.storage_service.list_containers()
        parts_per_slot = self.context.part_repo.count_parts_per_slot()
        for container in containers:
            if container.container_type != ContainerType.BINDER.value:
                continue
            slots = self.context.storage_repo.list_slots_for_container(container.id)
            total_bags = sum(s.metadata.get("bag_count", 4) for s in slots)
            occupied_bags = sum(parts_per_slot.get(s.id, 0) for s in slots)
            util[container.id] = (occupied_bags, total_bags)
        # For Unassigned container, show part count instead of slot occupancy
        unassigned_container = self.context.storage_repo.get_container_by_name("Unassigned")
        if unassigned_container is not None:
            unassigned_slot = self.context.storage_repo.get_slot_by_label(
                unassigned_container.id, "Main"
            )
            slot_parts = 0
            if unassigned_slot is not None:
                parts_map = self.context.part_repo.list_parts_by_slot_ids([unassigned_slot.id])
                slot_parts = len(parts_map.get(unassigned_slot.id, []))
            null_parts = len(self.context.part_repo.list_null_slot_parts())
            total_unassigned = slot_parts + null_parts
            total_parts = self.context.part_repo.count_parts()
            util[unassigned_container.id] = (total_unassigned, total_parts)
        self.container_model.set_utilization(util)

    def _on_container_clicked(self, index) -> None:
        container = self.container_model.container_at(index.row())
        if container is not None:
            self.load_container(container.id)

    def _add_container(self) -> None:
        dialog = StorageConfigDialog(self)
        if dialog.exec() != StorageConfigDialog.DialogCode.Accepted:
            return
        fields = dialog.get_fields()
        try:
            if fields["container_type"] == "grid_box":
                container = self.context.storage_service.configure_grid_box(
                    name=fields["name"],
                    rows=fields["rows"],
                    cols=fields["cols"],
                    notes=fields["notes"],
                )
            else:
                container = self.context.storage_service.configure_binder(
                    name=fields["name"],
                    num_cards=fields["num_cards"],
                    bags_per_card=fields["bags_per_card"],
                    notes=fields["notes"],
                )
            self.refresh()
            self.load_container(container.id)
        except Exception as exc:
            QMessageBox.critical(self, "Create container failed", str(exc))

    def _clone_container(self) -> None:
        if self.current_container_id is None:
            return
        suggested = self.context.storage_service.suggest_clone_name(self.current_container_id)
        name, ok = QInputDialog.getText(
            self, "Clone Container", "Name for the new container:", text=suggested,
        )
        if not ok or not name.strip():
            return
        try:
            clone = self.context.storage_service.clone_container(
                self.current_container_id, name.strip(),
            )
            self.refresh()
            self.load_container(clone.id)
        except Exception as exc:
            QMessageBox.critical(self, "Clone failed", str(exc))

    def _delete_container(self) -> None:
        if self.current_container_id is None:
            return
        container = self.context.storage_repo.get_container(self.current_container_id)
        if container is None:
            return
        dialog = DeleteContainerDialog(container.name, self)
        if dialog.exec() != DeleteContainerDialog.DialogCode.Accepted:
            return
        try:
            self.context.storage_service.delete_container(self.current_container_id)
            self.current_container_id = None
            self.clone_container_btn.setEnabled(False)
            self.delete_container_btn.setEnabled(False)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))

    # -------------------------------------------------- inline editing

    def _on_name_edited(self) -> None:
        if self.current_container_id is None:
            return
        new_name = self.container_name.text().strip()
        if not new_name:
            # Revert to current name
            container = self.context.storage_repo.get_container(self.current_container_id)
            if container:
                self.container_name.setText(container.name)
            return
        try:
            self.context.storage_service.rename_container(self.current_container_id, new_name)
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            container = self.context.storage_repo.get_container(self.current_container_id)
            if container:
                self.container_name.setText(container.name)

    def _on_notes_edited(self) -> None:
        if self.current_container_id is None:
            return
        try:
            self.context.storage_service.update_container_notes(
                self.current_container_id, self.container_notes.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Update failed", str(exc))

    # --------------------------------------------------- container detail view

    def load_container(self, container_id: int) -> None:
        container = self.context.storage_repo.get_container(container_id)
        if container is None:
            return
        self.current_container_id = container_id
        self.clone_container_btn.setEnabled(True)
        self.delete_container_btn.setEnabled(True)
        self._selected_slot_labels.clear()
        self.container_name.setText(container.name)
        self.container_type.setText(container.container_type)
        self.container_meta.setText(str(container.metadata))
        self.container_notes.setText(container.notes or "")
        is_system = container.name == "Unassigned"
        self.container_name.setReadOnly(is_system)
        self.container_notes.setReadOnly(is_system)
        slots = self.context.storage_service.list_slots(container_id)
        slot_ids = [s.id for s in slots if s.id is not None]
        self._slot_parts = self.context.part_repo.list_parts_by_slot_ids(slot_ids)

        # Populate slot table with context-appropriate columns
        is_grid = container.container_type == ContainerType.GRID_BOX.value
        is_binder = container.container_type == ContainerType.BINDER.value
        is_unassigned = container.name == "Unassigned"

        if is_unassigned:
            # Collect all unassigned parts: those on the Unassigned/Main slot + NULL slot_id
            all_unassigned: list[Part] = []
            for sid, parts_list in self._slot_parts.items():
                all_unassigned.extend(parts_list)
            null_parts = self.context.part_repo.list_null_slot_parts()
            all_unassigned.extend(null_parts)
            all_unassigned.sort(key=lambda p: (p.category or "", p.name or ""))

            self.slot_table.setColumnCount(3)
            self.slot_table.setHorizontalHeaderLabels(["Name", "Category", "Qty"])
            self.slot_table.setRowCount(len(all_unassigned))
            for row_idx, part in enumerate(all_unassigned):
                self.slot_table.setItem(row_idx, 0, QTableWidgetItem(part.name or ""))
                self.slot_table.setItem(row_idx, 1, QTableWidgetItem(part.category or ""))
                self.slot_table.setItem(row_idx, 2, QTableWidgetItem(str(part.qty)))
        elif is_binder:
            self.slot_table.setColumnCount(4)
            self.slot_table.setHorizontalHeaderLabels(["Card", "Capacity", "Available", "Parts"])
            self.slot_table.setRowCount(len(slots))
            for row_idx, slot in enumerate(slots):
                bag_count = slot.metadata.get("bag_count", 4)
                used = len(self._slot_parts.get(slot.id, []))
                available = max(0, bag_count - used)
                self.slot_table.setItem(row_idx, 0, QTableWidgetItem(slot.label))
                self.slot_table.setItem(row_idx, 1, QTableWidgetItem(f"{used}/{bag_count}"))
                self.slot_table.setItem(row_idx, 2, QTableWidgetItem(str(available)))
                self.slot_table.setItem(row_idx, 3, QTableWidgetItem(
                    self._parts_summary(slot.id)
                ))
        elif is_grid:
            self.slot_table.setColumnCount(6)
            self.slot_table.setHorizontalHeaderLabels(["Label", "Type", "Size", "Length", "Part", "Notes"])
            self.slot_table.setRowCount(len(slots))
            for row_idx, slot in enumerate(slots):
                self.slot_table.setItem(row_idx, 0, QTableWidgetItem(slot.label))
                self.slot_table.setItem(row_idx, 1, QTableWidgetItem(slot.slot_type))
                self.slot_table.setItem(row_idx, 2, QTableWidgetItem(
                    slot.metadata.get("cell_size", "")
                ))
                self.slot_table.setItem(row_idx, 3, QTableWidgetItem(
                    slot.metadata.get("cell_length", "")
                ))
                self.slot_table.setItem(row_idx, 4, QTableWidgetItem(
                    self._parts_summary(slot.id)
                ))
                self.slot_table.setItem(row_idx, 5, QTableWidgetItem(slot.notes or ""))
        else:
            self.slot_table.setColumnCount(4)
            self.slot_table.setHorizontalHeaderLabels(["Label", "Type", "Parts", "Notes"])
            self.slot_table.setRowCount(len(slots))
            for row_idx, slot in enumerate(slots):
                self.slot_table.setItem(row_idx, 0, QTableWidgetItem(slot.label))
                self.slot_table.setItem(row_idx, 1, QTableWidgetItem(slot.slot_type))
                self.slot_table.setItem(row_idx, 2, QTableWidgetItem(
                    self._parts_summary(slot.id)
                ))
                self.slot_table.setItem(row_idx, 3, QTableWidgetItem(slot.notes or ""))
        self.merge_btn.setVisible(is_grid)
        self.unmerge_btn.setVisible(is_grid)
        self.clear_sel_btn.setVisible(is_grid)
        self.resize_widget.setVisible(is_grid)
        self.binder_resize_widget.setVisible(is_binder)

        is_unassigned = container.name == "Unassigned"

        if is_unassigned:
            self._render_unassigned(slots)
        elif is_grid:
            rows = int(container.metadata.get("rows", 0))
            cols = int(container.metadata.get("cols", 0))
            self.rows_spin.setValue(rows)
            self.cols_spin.setValue(cols)
            self._render_grid(rows, cols, slots)
            self._schedule_grid_layout_refresh()
        elif is_binder:
            card_count = sum(1 for s in slots if s.slot_type == SlotType.CARD.value)
            self.binder_cards_spin.setValue(card_count)
            self._render_binder(slots)
            self._schedule_grid_layout_refresh()
        else:
            self._render_non_grid(slots)

    # -------------------------------------------------------- grid rendering

    def _render_grid(self, rows: int, cols: int, slots: list[StorageSlot]) -> None:
        # Full reset
        self.grid_table.clearSpans()
        self.grid_table.setRowCount(0)
        self.grid_table.setColumnCount(0)
        self.grid_table.setRowCount(rows)
        self.grid_table.setColumnCount(cols)
        self.grid_table.setHorizontalHeaderLabels([str(i) for i in range(cols)])
        self.grid_table.setVerticalHeaderLabels(
            [self._row_label(i) for i in range(rows)]
        )
        self.grid_table.horizontalHeader().setVisible(True)
        self.grid_table.verticalHeader().setVisible(True)
        self.grid_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        # Build slot map and collect layout info
        self._slot_map.clear()
        self._slot_label_map.clear()
        self._slot_grid_pos.clear()
        occupied: set[tuple[int, int]] = set()
        pending_spans: list[tuple[int, int, int, int]] = []

        for slot in slots:
            if None in (slot.x1, slot.y1, slot.x2, slot.y2):
                continue

            row_span = slot.y2 - slot.y1 + 1
            col_span = slot.x2 - slot.x1 + 1

            for r in range(slot.y1, slot.y2 + 1):
                for c in range(slot.x1, slot.x2 + 1):
                    self._slot_map[(r, c)] = slot
                    occupied.add((r, c))
            self._slot_label_map[slot.label] = slot
            self._slot_grid_pos[slot.label] = (slot.y1, slot.x1)

            is_occupied = bool(self._slot_parts.get(slot.id))
            item = QTableWidgetItem(self._slot_display_text(slot))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setBackground(self._cell_color(slot))
            item.setData(_GRID_CELL_SELECTION_ROLE, slot.label in self._selected_slot_labels)
            item.setData(_GRID_CELL_SLOT_LABEL_ROLE, slot.label)
            item.setData(_GRID_CELL_OCCUPIED_ROLE, is_occupied)
            item.setData(_GRID_CELL_DROP_TARGET_ROLE, False)
            item.setToolTip(self._slot_tooltip(slot))
            self.grid_table.setItem(slot.y1, slot.x1, item)

            if row_span > 1 or col_span > 1:
                pending_spans.append((slot.y1, slot.x1, row_span, col_span))

        # Fill unoccupied cells
        for row in range(rows):
            for col in range(cols):
                if (row, col) not in occupied:
                    item = QTableWidgetItem("")
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    item.setBackground(_DEFAULT_CELL_COLOR)
                    self.grid_table.setItem(row, col, item)

        # Apply spans after the slot items are in place.
        for row, col, rs, cs in pending_spans:
            self.grid_table.setSpan(row, col, rs, cs)
        self.grid_table.viewport().update()

    def _render_binder(self, slots: list[StorageSlot]) -> None:
        self._slot_map.clear()
        self._slot_label_map.clear()
        self._selected_slot_labels.clear()
        self._slot_grid_pos.clear()
        self.grid_table.clearSpans()
        self.grid_table.setRowCount(0)
        self.grid_table.setColumnCount(0)

        card_slots = [s for s in slots if s.slot_type == SlotType.CARD.value]
        card_slots.sort(key=lambda s: s.ordinal or 0)

        if not card_slots:
            self.grid_table.setRowCount(1)
            self.grid_table.setColumnCount(1)
            self.grid_table.setHorizontalHeaderLabels([""])
            self.grid_table.setVerticalHeaderLabels([""])
            self.grid_table.setItem(0, 0, QTableWidgetItem("No cards yet"))
            return

        num_cols = 2
        num_rows = (len(card_slots) + num_cols - 1) // num_cols

        self.grid_table.setRowCount(num_rows)
        self.grid_table.setColumnCount(num_cols)
        self.grid_table.setHorizontalHeaderLabels([""] * num_cols)
        self.grid_table.setVerticalHeaderLabels([""] * num_rows)
        self.grid_table.horizontalHeader().setVisible(False)
        self.grid_table.verticalHeader().setVisible(False)

        for idx, slot in enumerate(card_slots):
            row = idx // num_cols
            col = idx % num_cols
            self._slot_map[(row, col)] = slot
            self._slot_label_map[slot.label] = slot
            self._slot_grid_pos[slot.label] = (row, col)

            is_occupied = bool(self._slot_parts.get(slot.id))
            item = QTableWidgetItem(self._binder_card_display_text(slot))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setBackground(self._binder_card_color(slot))
            item.setData(_GRID_CELL_SELECTION_ROLE, slot.label in self._selected_slot_labels)
            item.setData(_GRID_CELL_SLOT_LABEL_ROLE, slot.label)
            item.setData(_GRID_CELL_OCCUPIED_ROLE, is_occupied)
            item.setData(_GRID_CELL_DROP_TARGET_ROLE, False)
            item.setToolTip(self._binder_card_tooltip(slot))
            self.grid_table.setItem(row, col, item)

        # Fill trailing empty cells if odd number of cards
        if len(card_slots) % num_cols != 0:
            last_row = num_rows - 1
            for c in range(len(card_slots) % num_cols, num_cols):
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setBackground(_DEFAULT_CELL_COLOR)
                self.grid_table.setItem(last_row, c, item)

        # Let rows grow to fit multi-line card content
        self.grid_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.grid_table.viewport().update()

    def _render_unassigned(self, slots) -> None:
        """Render the Unassigned container as a per-part list in the visual area."""
        self._slot_map.clear()
        self._slot_label_map.clear()
        self._selected_slot_labels.clear()
        self.grid_table.clearSpans()
        self.grid_table.setRowCount(0)
        self.grid_table.setColumnCount(0)
        self.grid_table.horizontalHeader().setVisible(True)
        self.grid_table.verticalHeader().setVisible(True)

        # Gather all unassigned parts
        all_unassigned: list[Part] = []
        for sid, parts_list in self._slot_parts.items():
            all_unassigned.extend(parts_list)
        null_parts = self.context.part_repo.list_null_slot_parts()
        all_unassigned.extend(null_parts)
        all_unassigned.sort(key=lambda p: (p.category or "", p.name or ""))

        if not all_unassigned:
            self.grid_table.setRowCount(1)
            self.grid_table.setColumnCount(1)
            self.grid_table.setHorizontalHeaderLabels(["Unassigned Parts"])
            self.grid_table.setVerticalHeaderLabels([""])
            self.grid_table.setItem(0, 0, QTableWidgetItem("No unassigned parts"))
            return

        self.grid_table.setRowCount(len(all_unassigned))
        self.grid_table.setColumnCount(3)
        self.grid_table.setHorizontalHeaderLabels(["Name", "Category", "Qty"])
        self.grid_table.setVerticalHeaderLabels([""] * len(all_unassigned))
        for row, part in enumerate(all_unassigned):
            name_item = QTableWidgetItem(part.name or "")
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.grid_table.setItem(row, 0, name_item)
            cat_item = QTableWidgetItem(part.category or "")
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.grid_table.setItem(row, 1, cat_item)
            qty_item = QTableWidgetItem(str(part.qty))
            qty_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.grid_table.setItem(row, 2, qty_item)

    def _render_non_grid(self, slots) -> None:
        self._slot_map.clear()
        self._slot_label_map.clear()
        self._selected_slot_labels.clear()
        self.grid_table.clearSpans()
        self.grid_table.setRowCount(0)
        self.grid_table.setColumnCount(0)
        self.grid_table.horizontalHeader().setVisible(True)
        self.grid_table.verticalHeader().setVisible(True)
        self.grid_table.setRowCount(max(1, len(slots)))
        self.grid_table.setColumnCount(1)
        self.grid_table.setHorizontalHeaderLabels(["Slots"])
        self.grid_table.setVerticalHeaderLabels([""] * max(1, len(slots)))
        if slots:
            for row, slot in enumerate(slots):
                item = QTableWidgetItem(slot.label)
                self.grid_table.setItem(row, 0, item)
        else:
            self.grid_table.setItem(0, 0, QTableWidgetItem("No slots yet"))

    # ---------------------------------------------------------- slot selection

    def _slot_display_text(self, slot: StorageSlot) -> str:
        cell_size = slot.metadata.get("cell_size", "")
        cell_length = slot.metadata.get("cell_length", "")
        size_abbr = "S" if cell_size == CellSize.SMALL.value else "L"
        length_abbr = "short" if cell_length == CellLength.SHORT.value else "long"
        parts = self._slot_parts.get(slot.id, [])
        if parts:
            part_names = "\n".join(p.name for p in parts)
            return f"{slot.label}\n{part_names}"
        return f"{slot.label}\n{size_abbr} / {length_abbr}"

    def _slot_tooltip(self, slot: StorageSlot) -> str:
        parts = self._slot_parts.get(slot.id, [])
        lines = [
            f"{slot.label} | "
            f"{slot.metadata.get('cell_size', CellSize.SMALL.value)} | "
            f"{slot.metadata.get('cell_length', CellLength.SHORT.value)}"
        ]
        for p in parts:
            lines.append(f"  {p.name} (qty {p.qty})")
        return "\n".join(lines)

    def _parts_summary(self, slot_id: int | None) -> str:
        """Return a short summary of parts assigned to a slot."""
        if slot_id is None:
            return ""
        parts = self._slot_parts.get(slot_id, [])
        if not parts:
            return ""
        names = [f"{p.name} ({p.qty})" for p in parts]
        return ", ".join(names)

    def _binder_card_display_text(self, slot: StorageSlot) -> str:
        bag_count = slot.metadata.get("bag_count", 4)
        parts = self._slot_parts.get(slot.id, [])
        used = len(parts)
        header = f"{slot.label}  ({used}/{bag_count})"
        if not parts:
            return header
        names = [p.name for p in parts]
        return header + "\n" + "\n".join(names)

    def _binder_card_tooltip(self, slot: StorageSlot) -> str:
        bag_count = slot.metadata.get("bag_count", 4)
        parts = self._slot_parts.get(slot.id, [])
        used = len(parts)
        available = max(0, bag_count - used)
        lines = [f"{slot.label}  |  {used}/{bag_count} used  |  {available} available"]
        for p in parts:
            lines.append(f"  {p.name} (qty {p.qty})")
        if not parts:
            lines.append("  (empty)")
        return "\n".join(lines)

    def _binder_card_color(self, slot: StorageSlot) -> QColor:
        bag_count = slot.metadata.get("bag_count", 4)
        used = len(self._slot_parts.get(slot.id, []))
        if used == 0:
            return _BINDER_CARD_EMPTY_COLOR
        if used >= bag_count:
            return _BINDER_CARD_FULL_COLOR
        return _BINDER_CARD_PARTIAL_COLOR

    def _cell_color(self, slot: StorageSlot) -> QColor:
        is_filled = bool(self._slot_parts.get(slot.id))
        is_merged = (slot.x1 != slot.x2) or (slot.y1 != slot.y2)
        if is_merged:
            # Merged cells use neutral gray regardless of size/length
            return _CELL_COLORS_FILLED[(CellSize.SMALL.value, CellLength.SHORT.value)] if is_filled else _CELL_COLORS_EMPTY[(CellSize.SMALL.value, CellLength.SHORT.value)]
        key = (slot.metadata.get("cell_size", ""), slot.metadata.get("cell_length", ""))
        palette = _CELL_COLORS_FILLED if is_filled else _CELL_COLORS_EMPTY
        return palette.get(key, _DEFAULT_CELL_COLOR)

    def _get_selected_slots(self) -> list[tuple[str, StorageSlot | None]]:
        results = [
            (label, self._slot_label_map.get(label))
            for label in self._selected_slot_labels
        ]
        return sorted(
            results,
            key=lambda item: (
                item[1].y1 if item[1] is not None and item[1].y1 is not None else 999,
                item[1].x1 if item[1] is not None and item[1].x1 is not None else 999,
                item[0],
            ),
        )

    def _set_slot_selected(self, slot: StorageSlot, selected: bool) -> None:
        if selected:
            self._selected_slot_labels.add(slot.label)
        else:
            self._selected_slot_labels.discard(slot.label)

        pos = self._slot_grid_pos.get(slot.label)
        if pos is None:
            return
        row, col = pos
        item = self.grid_table.item(row, col)
        if item is not None:
            item.setData(_GRID_CELL_SELECTION_ROLE, selected)
            self.grid_table.viewport().update(self.grid_table.visualItemRect(item))

    def _clear_selection(self) -> None:
        for label in list(self._selected_slot_labels):
            slot = self._slot_label_map.get(label)
            if slot is not None:
                self._set_slot_selected(slot, False)
        self._selected_slot_labels.clear()

    def highlight_slot(self, slot_id: int) -> None:
        """Select the container and highlight the slot with the given ID."""
        slot = self.context.storage_repo.get_slot(slot_id)
        if slot is None:
            return
        # Switch to the correct container
        self.load_container(slot.container_id)
        # Select the container in the list
        for i, c in enumerate(self.container_model.rows):
            if c.id == slot.container_id:
                self.container_list.setCurrentIndex(self.container_model.index(i))
                break
        # Highlight the slot
        self._clear_selection()
        self._set_slot_selected(slot, True)
        # Scroll to the slot
        pos = self._slot_grid_pos.get(slot.label)
        if pos is not None:
            item = self.grid_table.item(pos[0], pos[1])
            if item is not None:
                self.grid_table.scrollToItem(item)
        # Remove highlight after 2 seconds
        QTimer.singleShot(2000, self._clear_selection)

    def _toggle_selection_at_grid_pos(self, pos: QPoint) -> bool:
        slot = self._slot_at_grid_pos(pos)
        if slot is None:
            return False
        self._set_slot_selected(slot, slot.label not in self._selected_slot_labels)
        return True

    # ---------------------------------------------------------- merge / unmerge

    def _merge_selected(self) -> None:
        if self.current_container_id is None:
            return
        selected = self._get_selected_slots()
        labels = [label for label, _slot in selected]
        if len(labels) < 2:
            QMessageBox.information(self, "Merge", "Select at least two cells to merge.")
            return
        try:
            self.context.storage_service.merge_cells(
                container_id=self.current_container_id,
                labels=labels,
            )
            self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Merge failed", str(exc))

    def _unmerge_selected(self) -> None:
        if self.current_container_id is None:
            return
        selected = self._get_selected_slots()
        if len(selected) != 1:
            QMessageBox.information(self, "Unmerge", "Select exactly one merged cell to unmerge.")
            return
        _label, slot = selected[0]
        if slot is None:
            return
        if slot.x1 == slot.x2 and slot.y1 == slot.y2:
            QMessageBox.information(self, "Unmerge", "This cell is not merged.")
            return
        try:
            self.context.storage_service.unmerge_cell(
                container_id=self.current_container_id,
                slot_id=slot.id,
            )
            self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Unmerge failed", str(exc))

    # -------------------------------------------------------------- resize

    def _resize_grid(self) -> None:
        if self.current_container_id is None:
            return
        try:
            self.context.storage_service.resize_grid_box(
                container_id=self.current_container_id,
                new_rows=self.rows_spin.value(),
                new_cols=self.cols_spin.value(),
            )
            self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Resize failed", str(exc))

    def _resize_binder(self) -> None:
        if self.current_container_id is None:
            return
        try:
            self.context.storage_service.resize_binder(
                container_id=self.current_container_id,
                new_num_cards=self.binder_cards_spin.value(),
            )
            self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Resize failed", str(exc))

    # --------------------------------------------------------- context menu

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_grid_layout_refresh()

    def _on_grid_left_click(self, pos: QPoint) -> None:
        self._toggle_selection_at_grid_pos(pos)

    def _on_grid_context_menu(self, pos: QPoint) -> None:
        # Try grid slot first, then fall back to label lookup for binder cards
        slot = self._slot_at_grid_pos(pos)
        if slot is None:
            row = self.grid_table.rowAt(pos.y())
            col = self.grid_table.columnAt(pos.x())
            if row >= 0 and col >= 0:
                item = self.grid_table.item(row, col)
                if item is not None:
                    label = item.data(_GRID_CELL_SLOT_LABEL_ROLE)
                    if label:
                        slot = self._slot_label_map.get(label)
        if slot is None:
            return
        global_pos = self.grid_table.viewport().mapToGlobal(pos)
        if slot.slot_type == SlotType.CARD.value:
            self._show_card_context_menu(slot, global_pos)
        else:
            self._show_slot_context_menu(slot, global_pos)

    def _slot_at_grid_pos(self, pos: QPoint) -> StorageSlot | None:
        row = self.grid_table.rowAt(pos.y())
        col = self.grid_table.columnAt(pos.x())
        if row < 0 or col < 0:
            return None
        return self._slot_map.get((row, col))

    def _show_slot_context_menu(self, slot: StorageSlot, global_pos) -> None:
        menu = QMenu(self)
        current_size = slot.metadata.get("cell_size", CellSize.SMALL.value)
        current_length = slot.metadata.get("cell_length", CellLength.SHORT.value)

        if current_size == CellSize.SMALL.value:
            size_action = QAction("Set size: Large", self)
            size_action.triggered.connect(
                lambda: self._set_cell_property(slot.id, cell_size=CellSize.LARGE.value)
            )
        else:
            size_action = QAction("Set size: Small", self)
            size_action.triggered.connect(
                lambda: self._set_cell_property(slot.id, cell_size=CellSize.SMALL.value)
            )
        menu.addAction(size_action)

        if current_length == CellLength.SHORT.value:
            length_action = QAction("Set length: Long", self)
            length_action.triggered.connect(
                lambda: self._set_cell_property(slot.id, cell_length=CellLength.LONG.value)
            )
        else:
            length_action = QAction("Set length: Short", self)
            length_action.triggered.connect(
                lambda: self._set_cell_property(slot.id, cell_length=CellLength.SHORT.value)
            )
        menu.addAction(length_action)

        # Unassign parts from this cell
        parts = self._slot_parts.get(slot.id, [])
        if parts:
            menu.addSeparator()
            if len(parts) == 1:
                p = parts[0]
                unassign_action = QAction(f"Unassign \"{p.name}\"", self)
                unassign_action.triggered.connect(
                    lambda checked, ids=[p.id]: self._unassign_parts(ids)
                )
                menu.addAction(unassign_action)
            else:
                for p in parts:
                    action = QAction(f"Unassign \"{p.name}\"", self)
                    action.triggered.connect(
                        lambda checked, ids=[p.id]: self._unassign_parts(ids)
                    )
                    menu.addAction(action)
                all_action = QAction(f"Unassign all ({len(parts)} parts)", self)
                all_action.triggered.connect(
                    lambda checked, ids=[p.id for p in parts]: self._unassign_parts(ids)
                )
                menu.addAction(all_action)

        menu.exec(global_pos)

    def _show_card_context_menu(self, slot: StorageSlot, global_pos) -> None:
        menu = QMenu(self)
        current_bags = int(slot.metadata.get("bag_count", 4))
        for count in [1, 2, 3, 4, 6, 8, 10]:
            action = QAction(f"{count} bags", self)
            action.setCheckable(True)
            action.setChecked(count == current_bags)
            action.triggered.connect(
                lambda checked, c=count: self._set_card_bag_count(slot.id, c)
            )
            menu.addAction(action)

        # Unassign parts from this card
        parts = self._slot_parts.get(slot.id, [])
        if parts:
            menu.addSeparator()
            for p in parts:
                unassign_action = QAction(f"Unassign \"{p.name}\"", self)
                unassign_action.triggered.connect(
                    lambda checked, ids=[p.id]: self._unassign_parts(ids)
                )
                menu.addAction(unassign_action)
            if len(parts) > 1:
                all_action = QAction(f"Unassign all ({len(parts)} parts)", self)
                all_action.triggered.connect(
                    lambda checked, ids=[p.id for p in parts]: self._unassign_parts(ids)
                )
                menu.addAction(all_action)

        menu.exec(global_pos)

    def _unassign_parts(self, part_ids: list[int]) -> None:
        try:
            self.context.inventory_service.unassign_parts(part_ids)
            if self.current_container_id is not None:
                self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Unassign failed", str(exc))

    def _set_card_bag_count(self, slot_id: int, bag_count: int) -> None:
        try:
            self.context.storage_service.update_card_bag_count(
                slot_id=slot_id,
                bag_count=bag_count,
            )
            if self.current_container_id is not None:
                self.load_container(self.current_container_id)
        except Exception as exc:
            QMessageBox.critical(self, "Update failed", str(exc))

    def _set_cell_property(
        self,
        slot_id: int,
        cell_size: str | None = None,
        cell_length: str | None = None,
    ) -> None:
        try:
            self.context.storage_service.update_cell_properties(
                slot_id=slot_id,
                cell_size=cell_size,
                cell_length=cell_length,
            )
            if self.current_container_id is not None:
                self.load_container(self.current_container_id)
        except Exception as exc:
            QMessageBox.critical(self, "Update failed", str(exc))

    # ---------------------------------------------------------- drag and drop

    def _pick_part_for_drag(self, parts: list[Part], global_pos) -> Part | None:
        """Show a menu to pick which part to drag when a cell has multiple parts."""
        menu = QMenu(self)
        chosen: list[Part | None] = [None]
        for p in parts:
            action = QAction(p.name, self)
            action.triggered.connect(lambda checked, part=p: chosen.__setitem__(0, part))
            menu.addAction(action)
        menu.exec(global_pos)
        return chosen[0]

    def _on_part_dropped(self, part_id: int, source_slot_id: int, target_slot_id: int) -> None:
        """Handle a drag-and-drop part move."""
        try:
            self.context.inventory_service.reassign_part_slot(part_id, target_slot_id)
            if self.current_container_id is not None:
                self.load_container(self.current_container_id)
            self._refresh_utilization()
        except Exception as exc:
            QMessageBox.critical(self, "Move failed", str(exc))

    # ----------------------------------------------------------- slot creation

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

    # --------------------------------------------------------------- helpers

    def _schedule_grid_layout_refresh(self) -> None:
        if self._grid_refresh_pending or self.grid_table.rowCount() == 0:
            return
        self._grid_refresh_pending = True
        QTimer.singleShot(0, self._force_grid_layout_refresh)

    def _force_grid_layout_refresh(self) -> None:
        self._grid_refresh_pending = False
        if self.grid_table.rowCount() == 0:
            return

        self.grid_table.doItemsLayout()
        self.grid_table.updateGeometry()

        width = self.grid_table.width()
        height = self.grid_table.height()
        if width > 1 and height > 1:
            self.grid_table.setUpdatesEnabled(False)
            self.grid_table.resize(width + 1, height)
            self.grid_table.resize(width, height)
            self.grid_table.setUpdatesEnabled(True)

        self.grid_table.viewport().update()

    @staticmethod
    def _row_label(index: int) -> str:
        index += 1
        chars: list[str] = []
        while index:
            index, remainder = divmod(index - 1, 26)
            chars.append(chr(ord("A") + remainder))
        return "".join(reversed(chars))
