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
            ORDER BY COALESCE(ordinal, 999999), label
            """,
            (container_id,),
        )
        return [_row_to_slot(row) for row in rows]

    def count_containers(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM storage_containers") or 0)

    def count_slots(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM storage_slots") or 0)
