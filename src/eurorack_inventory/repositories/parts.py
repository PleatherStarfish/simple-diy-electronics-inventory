from __future__ import annotations

import logging
from typing import Iterable

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import InventorySummary, Part, PartAlias, utc_now_iso

logger = logging.getLogger(__name__)


def _row_to_part(row) -> Part:
    return Part(
        id=row["id"],
        fingerprint=row["fingerprint"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        category=row["category"],
        manufacturer=row["manufacturer"],
        mpn=row["mpn"],
        supplier_name=row["supplier_name"],
        supplier_sku=row["supplier_sku"],
        purchase_url=row["purchase_url"],
        default_package=row["default_package"],
        notes=row["notes"],
        qty=row["qty"],
        slot_id=row["slot_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_alias(row) -> PartAlias:
    return PartAlias(
        id=row["id"],
        part_id=row["part_id"],
        alias=row["alias"],
        normalized_alias=row["normalized_alias"],
    )


class PartRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_part(self, part: Part) -> Part:
        existing = self.db.query_one(
            "SELECT * FROM parts WHERE fingerprint = ?",
            (part.fingerprint,),
        )
        now = utc_now_iso()
        if existing:
            self.db.execute(
                """
                UPDATE parts
                SET name = ?, normalized_name = ?, category = ?, manufacturer = ?, mpn = ?,
                    supplier_name = ?, supplier_sku = ?, purchase_url = ?, default_package = ?,
                    notes = ?, qty = ?, slot_id = ?, updated_at = ?
                WHERE fingerprint = ?
                """,
                (
                    part.name,
                    part.normalized_name,
                    part.category,
                    part.manufacturer,
                    part.mpn,
                    part.supplier_name,
                    part.supplier_sku,
                    part.purchase_url,
                    part.default_package,
                    part.notes,
                    part.qty,
                    part.slot_id,
                    now,
                    part.fingerprint,
                ),
            )
            updated = self.db.query_one("SELECT * FROM parts WHERE fingerprint = ?", (part.fingerprint,))
            assert updated is not None
            return _row_to_part(updated)

        cursor = self.db.execute(
            """
            INSERT INTO parts (
                fingerprint, name, normalized_name, category, manufacturer, mpn,
                supplier_name, supplier_sku, purchase_url, default_package, notes,
                qty, slot_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                part.fingerprint,
                part.name,
                part.normalized_name,
                part.category,
                part.manufacturer,
                part.mpn,
                part.supplier_name,
                part.supplier_sku,
                part.purchase_url,
                part.default_package,
                part.notes,
                part.qty,
                part.slot_id,
                now,
                now,
            ),
        )
        created = self.get_part_by_id(int(cursor.lastrowid))
        assert created is not None
        return created

    def update_part(self, part_id: int, **fields) -> Part:
        """Update specific fields on a part by ID."""
        allowed = {
            "name", "normalized_name", "category", "manufacturer", "mpn",
            "supplier_name", "supplier_sku", "purchase_url", "default_package",
            "notes", "qty", "slot_id",
        }
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            raise ValueError("No valid fields to update")
        to_set["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        params = list(to_set.values()) + [part_id]
        self.db.execute(f"UPDATE parts SET {set_clause} WHERE id = ?", tuple(params))
        updated = self.get_part_by_id(part_id)
        assert updated is not None
        return updated

    def delete_part(self, part_id: int) -> None:
        """Delete a part by ID. Cascades to aliases. Raises on BOM FK violation."""
        self.db.execute("DELETE FROM parts WHERE id = ?", (part_id,))

    def adjust_qty(self, part_id: int, delta: int) -> int:
        """Adjust quantity by delta, return new qty. Prevents going negative."""
        self.db.execute(
            "UPDATE parts SET qty = MAX(0, qty + ?), updated_at = ? WHERE id = ?",
            (delta, utc_now_iso(), part_id),
        )
        new_qty = self.db.scalar("SELECT qty FROM parts WHERE id = ?", (part_id,))
        return int(new_qty or 0)

    def list_parts(self) -> list[Part]:
        rows = self.db.query_all("SELECT * FROM parts ORDER BY category, name")
        return [_row_to_part(row) for row in rows]

    def get_part_by_id(self, part_id: int) -> Part | None:
        row = self.db.query_one("SELECT * FROM parts WHERE id = ?", (part_id,))
        return _row_to_part(row) if row else None

    def add_alias(self, part_id: int, alias: str, normalized_alias: str) -> PartAlias:
        self.db.execute(
            """
            INSERT OR IGNORE INTO part_aliases (part_id, alias, normalized_alias)
            VALUES (?, ?, ?)
            """,
            (part_id, alias, normalized_alias),
        )
        row = self.db.query_one(
            """
            SELECT * FROM part_aliases
            WHERE part_id = ? AND normalized_alias = ?
            """,
            (part_id, normalized_alias),
        )
        assert row is not None
        return _row_to_alias(row)

    def list_aliases_for_part(self, part_id: int) -> list[PartAlias]:
        rows = self.db.query_all(
            "SELECT * FROM part_aliases WHERE part_id = ? ORDER BY alias",
            (part_id,),
        )
        return [_row_to_alias(row) for row in rows]

    def list_all_aliases(self) -> list[PartAlias]:
        rows = self.db.query_all("SELECT * FROM part_aliases ORDER BY alias")
        return [_row_to_alias(row) for row in rows]

    def update_part_notes(self, part_id: int, notes: str | None) -> None:
        self.db.execute(
            "UPDATE parts SET notes = ?, updated_at = ? WHERE id = ?",
            (notes, utc_now_iso(), part_id),
        )

    def list_inventory_summaries(self, part_ids: Iterable[int] | None = None) -> list[InventorySummary]:
        sql = "SELECT * FROM part_inventory_summary"
        params: tuple = ()
        if part_ids is not None:
            ids = list(part_ids)
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            sql += f" WHERE part_id IN ({placeholders})"
            params = tuple(ids)
        sql += " ORDER BY category, name"
        rows = self.db.query_all(sql, params)
        return [
            InventorySummary(
                part_id=row["part_id"],
                name=row["name"],
                category=row["category"],
                supplier_sku=row["supplier_sku"],
                total_qty=row["total_qty"],
                locations=row["locations"],
                notes=row["notes"],
            )
            for row in rows
        ]

    def get_part_location(self, part_id: int) -> str:
        """Return formatted location string for a part."""
        row = self.db.query_one(
            """
            SELECT sc.name || ' / ' || ss.label AS location
            FROM parts p
            JOIN storage_slots ss ON ss.id = p.slot_id
            JOIN storage_containers sc ON sc.id = ss.container_id
            WHERE p.id = ?
            """,
            (part_id,),
        )
        return row["location"] if row else ""

    def count_parts(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM parts") or 0)
