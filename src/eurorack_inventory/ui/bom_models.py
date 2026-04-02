from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from eurorack_inventory.domain.models import BomSource, NormalizedBomItem, RawBomItem


class BomSourceListModel(QAbstractListModel):
    def __init__(self, rows: list[BomSource] | None = None) -> None:
        super().__init__()
        self.rows: list[BomSource] = rows or []
        self._counts: dict[int, tuple[int, int]] = {}  # source_id -> (confirmed, total)

    def update_rows(
        self,
        rows: list[BomSource],
        counts: dict[int, tuple[int, int]] | None = None,
    ) -> None:
        self.beginResetModel()
        self.rows = rows
        self._counts = counts or {}
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        source = self.rows[index.row()]
        confirmed, total = self._counts.get(source.id, (0, 0))
        if role == Qt.DisplayRole:
            label = source.module_name
            if source.promoted_project_id is not None:
                label += " [promoted]"
            if total > 0:
                label += f"  ({confirmed}/{total})"
            return label
        if role == Qt.ForegroundRole:
            if total > 0 and confirmed == total:
                return QBrush(QColor(30, 130, 50))  # green — fully confirmed
            if confirmed > 0:
                return QBrush(QColor(180, 130, 0))  # amber — partially confirmed
            return None
        if role == Qt.ToolTipRole:
            tip = f"{source.filename} ({source.source_kind})"
            if total > 0:
                tip += f"\n{confirmed} of {total} components confirmed"
            return tip
        return None

    def source_at(self, row: int) -> BomSource | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None

    def row_for_source_id(self, source_id: int) -> int:
        for row_index, source in enumerate(self.rows):
            if source.id == source_id:
                return row_index
        return -1


class RawBomTableModel(QAbstractTableModel):
    HEADERS = ["#", "Description", "Qty", "Notes"]

    def __init__(self, rows: list[RawBomItem] | None = None) -> None:
        super().__init__()
        self.rows: list[RawBomItem] = rows or []

    def update_rows(self, rows: list[RawBomItem]) -> None:
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
        item = self.rows[index.row()]
        if role == Qt.DisplayRole:
            match index.column():
                case 0:
                    return item.line_number
                case 1:
                    return item.raw_description
                case 2:
                    return item.raw_qty
                case 3:
                    return item.raw_notes or ""
        return None

    def raw_item_at(self, row: int) -> RawBomItem | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


# Color constants for match status
_COLOR_VERIFIED = QColor(200, 240, 200)     # green - verified+matched
_COLOR_AUTO = QColor(255, 255, 200)         # yellow - auto-matched unverified
_COLOR_SKIPPED = QColor(220, 220, 220)      # gray - skipped
# white = unmatched (default)


class NormalizedBomTableModel(QAbstractTableModel):
    HEADERS = ["Type", "Value", "Qty", "Package", "Match", "Verified"]
    _EDITABLE_COLUMNS = {0, 1, 2, 3}  # Type, Value, Qty, Package

    cell_edited = Signal(int, int, object)  # (item_id, column, new_value)

    def __init__(self, rows: list[NormalizedBomItem] | None = None) -> None:
        super().__init__()
        self.rows: list[NormalizedBomItem] = rows or []

    def update_rows(self, rows: list[NormalizedBomItem]) -> None:
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

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid() and index.column() in self._EDITABLE_COLUMNS:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            match index.column():
                case 0:
                    return item.component_type or ""
                case 1:
                    return item.normalized_value
                case 2:
                    return item.qty
                case 3:
                    return item.package_hint or ""
                case 4:
                    return item.match_status
                case 5:
                    return "Yes" if item.is_verified else ""
        if role == Qt.BackgroundRole:
            if item.match_status == "skipped":
                return QBrush(_COLOR_SKIPPED)
            if item.is_verified and item.part_id is not None:
                return QBrush(_COLOR_VERIFIED)
            if item.match_status in ("auto_matched", "manually_matched") and not item.is_verified:
                return QBrush(_COLOR_AUTO)
        if role == Qt.ToolTipRole:
            tips = []
            if item.component_type == "other":
                tips.append("Component type could not be determined")
            if item.match_status == "unmatched":
                tips.append("No matching part in inventory")
            if tips:
                return "\n".join(tips)
        if role == Qt.ForegroundRole and index.column() == 0:
            if item.component_type == "other":
                return QBrush(QColor(180, 130, 0))
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        if index.column() not in self._EDITABLE_COLUMNS:
            return False
        item = self.rows[index.row()]
        if item.id is None:
            return False
        self.cell_edited.emit(item.id, index.column(), value)
        return True

    def item_at(self, row: int) -> NormalizedBomItem | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None
