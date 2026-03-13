from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, Qt

from eurorack_inventory.domain.models import InventorySummary, StorageContainer, StorageSlot
from eurorack_inventory.repositories.audit import AuditRepository


class InventoryTableModel(QAbstractTableModel):
    HEADERS = ["Component", "Category", "Qty", "Locations", "SKU"]

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
                    return row.locations
                case 4:
                    return row.supplier_sku or ""
        return None

    def part_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self.rows):
            return self.rows[row].part_id
        return None


class ContainerListModel(QAbstractListModel):
    def __init__(self, rows: list[StorageContainer] | None = None) -> None:
        super().__init__()
        self.rows = rows or []

    def update_rows(self, rows: list[StorageContainer]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        container = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return container.name
        return None

    def container_at(self, row: int) -> StorageContainer | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


class ModuleTableModel(QAbstractTableModel):
    HEADERS = ["Module", "Maker", "Revision"]

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

    def module_id_at(self, row: int) -> int | None:
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
