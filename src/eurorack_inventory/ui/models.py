from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QMimeData, QModelIndex, Qt, Signal

from eurorack_inventory.domain.models import InventorySummary, StorageContainer, StorageSlot
from eurorack_inventory.repositories.audit import AuditRepository


class InventoryTableModel(QAbstractTableModel):
    HEADERS = ["Component", "Category", "Qty", "Package", "Locations", "SKU"]
    _EDITABLE_COLUMNS = {0, 1, 2, 3, 4, 5}  # All columns editable

    # Emitted when a cell is edited: (part_id, column, new_value)
    cell_edited = Signal(int, int, object)

    def __init__(self, rows: list[InventorySummary] | None = None) -> None:
        super().__init__()
        self.rows = rows or []

    def update_rows(self, rows: list[InventorySummary]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    MIME_TYPE = "application/x-inventory-part-id"

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid():
            base |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
            if index.column() in self._EDITABLE_COLUMNS:
                base |= Qt.ItemFlag.ItemIsEditable
        else:
            base |= Qt.ItemFlag.ItemIsDropEnabled
        return base

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [self.MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        rows = {idx.row() for idx in indexes if idx.isValid()}
        if rows:
            row = min(rows)
            pid = self.part_id_at(row)
            if pid is not None:
                mime.setData(self.MIME_TYPE, str(pid).encode())
        return mime

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            match index.column():
                case 0:
                    return row.name
                case 1:
                    return row.category or ""
                case 2:
                    return row.total_qty
                case 3:
                    return row.default_package or ""
                case 4:
                    return row.locations
                case 5:
                    return row.supplier_sku or ""
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        if index.column() not in self._EDITABLE_COLUMNS:
            return False
        part_id = self.part_id_at(index.row())
        if part_id is None:
            return False
        self.cell_edited.emit(part_id, index.column(), value)
        return True

    def part_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self.rows):
            return self.rows[row].part_id
        return None


class ContainerListModel(QAbstractListModel):
    def __init__(self, rows: list[StorageContainer] | None = None) -> None:
        super().__init__()
        self.rows = rows or []
        self._utilization: dict[int, tuple[int, int]] = {}

    def update_rows(self, rows: list[StorageContainer]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_utilization(self, util: dict[int, tuple[int, int]]) -> None:
        self._utilization = util
        if self.rows:
            self.dataChanged.emit(
                self.index(0), self.index(len(self.rows) - 1)
            )

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        container = self.rows[index.row()]
        if role == Qt.DisplayRole:
            util = self._utilization.get(container.id)
            if util is not None:
                occupied, total = util
                return f"{container.name} ({occupied}/{total})"
            return container.name
        return None

    def container_at(self, row: int) -> StorageContainer | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


class ProjectTableModel(QAbstractTableModel):
    HEADERS = ["Project", "Maker", "Revision"]

    def __init__(self, rows: list | None = None) -> None:
        super().__init__()
        self.rows = rows or []

    def update_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return [row.name, row.maker, row.revision or ""][index.column()]
        return None

    def project_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self.rows):
            return self.rows[row].id
        return None


class AuditTableModel(QAbstractTableModel):
    HEADERS = ["When", "Event", "Entity", "Message"]

    def __init__(self, rows: list[dict] | None = None) -> None:
        super().__init__()
        self.rows = rows or []

    def update_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return [
                row["created_at"],
                row["event_type"],
                f"{row['entity_type']}:{row['entity_id'] or ''}",
                row["message"],
            ][index.column()]
        return None
