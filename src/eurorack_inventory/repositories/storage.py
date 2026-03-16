from __future__ import annotations

import json

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import StorageContainer, StorageSlot


def _row_to_container(row) -> StorageContainer:
    return StorageContainer(
        id=row["id"],
        name=row["name"],
        container_type=row["container_type"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        notes=row["notes"],
        sort_order=row["sort_order"],
    )


def _row_to_slot(row) -> StorageSlot:
    return StorageSlot(
        id=row["id"],
        container_id=row["container_id"],
        label=row["label"],
        slot_type=row["slot_type"],
        ordinal=row["ordinal"],
        x1=row["x1"],
        y1=row["y1"],
        x2=row["x2"],
        y2=row["y2"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        notes=row["notes"],
    )


def _slot_sort_key(slot: StorageSlot) -> tuple[int, int, int, int, int, str]:
    """Sort grid slots by coordinates, then fall back to ordinal/label for other slot types."""
    if None not in (slot.y1, slot.x1, slot.y2, slot.x2):
        return (slot.y1, slot.x1, slot.y2, slot.x2, slot.ordinal or 0, slot.label)
    return (999999, 999999, 999999, 999999, slot.ordinal or 999999, slot.label)


class StorageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_container(self, container: StorageContainer) -> StorageContainer:
        cursor = self.db.execute(
            """
            INSERT INTO storage_containers (name, container_type, metadata_json, notes, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                container.name,
                container.container_type,
                json.dumps(container.metadata, ensure_ascii=False, sort_keys=True),
                container.notes,
                container.sort_order,
            ),
        )
        created = self.get_container(int(cursor.lastrowid))
        assert created is not None
        return created

    def get_container(self, container_id: int) -> StorageContainer | None:
        row = self.db.query_one("SELECT * FROM storage_containers WHERE id = ?", (container_id,))
        return _row_to_container(row) if row else None

    def get_container_by_name(self, name: str) -> StorageContainer | None:
        row = self.db.query_one("SELECT * FROM storage_containers WHERE name = ?", (name,))
        return _row_to_container(row) if row else None

    def list_containers(self) -> list[StorageContainer]:
        rows = self.db.query_all(
            "SELECT * FROM storage_containers ORDER BY sort_order, name"
        )
        return [_row_to_container(row) for row in rows]

    def create_slot(self, slot: StorageSlot) -> StorageSlot:
        cursor = self.db.execute(
            """
            INSERT INTO storage_slots (
                container_id, label, slot_type, ordinal, x1, y1, x2, y2, metadata_json, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot.container_id,
                slot.label,
                slot.slot_type,
                slot.ordinal,
                slot.x1,
                slot.y1,
                slot.x2,
                slot.y2,
                json.dumps(slot.metadata, ensure_ascii=False, sort_keys=True),
                slot.notes,
            ),
        )
        created = self.get_slot(int(cursor.lastrowid))
        assert created is not None
        return created

    def get_slot(self, slot_id: int) -> StorageSlot | None:
        row = self.db.query_one("SELECT * FROM storage_slots WHERE id = ?", (slot_id,))
        return _row_to_slot(row) if row else None

    def get_slot_by_label(self, container_id: int, label: str) -> StorageSlot | None:
        row = self.db.query_one(
            "SELECT * FROM storage_slots WHERE container_id = ? AND label = ?",
            (container_id, label),
        )
        return _row_to_slot(row) if row else None

    def list_slots_for_container(self, container_id: int) -> list[StorageSlot]:
        rows = self.db.query_all(
            """
            SELECT * FROM storage_slots
            WHERE container_id = ?
            ORDER BY id
            """,
            (container_id,),
        )
        return sorted((_row_to_slot(row) for row in rows), key=_slot_sort_key)

    def update_slot(self, slot: StorageSlot) -> StorageSlot:
        self.db.execute(
            """
            UPDATE storage_slots
            SET label = ?, slot_type = ?, ordinal = ?,
                x1 = ?, y1 = ?, x2 = ?, y2 = ?,
                metadata_json = ?, notes = ?
            WHERE id = ?
            """,
            (
                slot.label,
                slot.slot_type,
                slot.ordinal,
                slot.x1,
                slot.y1,
                slot.x2,
                slot.y2,
                json.dumps(slot.metadata, ensure_ascii=False, sort_keys=True),
                slot.notes,
                slot.id,
            ),
        )
        updated = self.get_slot(slot.id)
        assert updated is not None
        return updated

    def delete_slot(self, slot_id: int) -> None:
        self.db.execute("DELETE FROM storage_slots WHERE id = ?", (slot_id,))

    def update_container(self, container: StorageContainer) -> StorageContainer:
        self.db.execute(
            """
            UPDATE storage_containers
            SET name = ?, container_type = ?, metadata_json = ?, notes = ?, sort_order = ?
            WHERE id = ?
            """,
            (
                container.name,
                container.container_type,
                json.dumps(container.metadata, ensure_ascii=False, sort_keys=True),
                container.notes,
                container.sort_order,
                container.id,
            ),
        )
        updated = self.get_container(container.id)
        assert updated is not None
        return updated

    def delete_container(self, container_id: int) -> None:
        self.db.execute("DELETE FROM storage_containers WHERE id = ?", (container_id,))

    def count_containers(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM storage_containers") or 0)

    def count_slots(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM storage_slots") or 0)

    def count_slots_per_container(self) -> dict[int, int]:
        """Return container_id → total slot count."""
        rows = self.db.query_all(
            "SELECT container_id, COUNT(*) AS cnt FROM storage_slots GROUP BY container_id"
        )
        return {row["container_id"]: row["cnt"] for row in rows}
