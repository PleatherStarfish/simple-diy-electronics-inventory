from __future__ import annotations

import logging
from typing import Iterable

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import (
    InventorySummary,
    Part,
    PartAlias,
    PartLocation,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_UNASSIGNED_CONTAINER_NAME = "Unassigned"
_UNASSIGNED_SLOT_LABEL = "Main"
_SLOT_SENTINEL = object()


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
        storage_class_override=row["storage_class_override"],
    )


def _row_to_alias(row) -> PartAlias:
    return PartAlias(
        id=row["id"],
        part_id=row["part_id"],
        alias=row["alias"],
        normalized_alias=row["normalized_alias"],
    )


def _row_to_part_location(row) -> PartLocation:
    keys = set(row.keys())
    return PartLocation(
        id=row["id"],
        part_id=row["part_id"],
        slot_id=row["slot_id"],
        qty=row["qty"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        container_name=row["container_name"] if "container_name" in keys else None,
        slot_label=row["slot_label"] if "slot_label" in keys else None,
    )


def _sort_location_key(location: PartLocation) -> tuple[int, str, str, int]:
    return (
        1 if location.is_unassigned else 0,
        location.container_name or "",
        location.slot_label or "",
        location.slot_id,
    )


def _format_location(location: PartLocation) -> str:
    return f"{location.location_label} ({location.qty})"


def _format_full_location_summary(locations: list[PartLocation]) -> str:
    ordered = sorted(locations, key=_sort_location_key)
    if len(ordered) == 1 and ordered[0].is_unassigned:
        return ""
    return "; ".join(_format_location(location) for location in ordered)


def _format_compact_location_summary(locations: list[PartLocation]) -> str:
    ordered = sorted(locations, key=_sort_location_key)
    if not ordered:
        return ""
    if len(ordered) == 1 and ordered[0].is_unassigned:
        return ""

    primary = next((location for location in ordered if not location.is_unassigned), ordered[0])
    if len(ordered) == 1:
        return _format_location(primary)
    return f"{_format_location(primary)} +{len(ordered) - 1} more"


class PartRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_part(self, part: Part) -> Part:
        with self.db.transaction():
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
                part_id = existing["id"]
                old_qty = int(existing["qty"] or 0)
                if part.slot_id is not None:
                    self._set_single_location_state(part_id, part.slot_id, part.qty)
                elif self.list_part_locations(part_id):
                    self._adjust_locations_for_qty_change(part_id, old_qty, part.qty)
                else:
                    self._set_single_location_state(part_id, None, part.qty)
            else:
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
                part_id = int(cursor.lastrowid)
                self._set_single_location_state(part_id, part.slot_id, part.qty)

        created = self.get_part_by_id(part_id)
        assert created is not None
        return created

    def update_part(self, part_id: int, **fields) -> Part:
        """Update specific fields on a part by ID."""
        allowed = {
            "name", "normalized_name", "category", "manufacturer", "mpn",
            "supplier_name", "supplier_sku", "purchase_url", "default_package",
            "notes", "qty", "slot_id", "storage_class_override",
        }
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            raise ValueError("No valid fields to update")

        with self.db.transaction():
            current = self.get_part_by_id(part_id)
            if current is None:
                raise ValueError(f"Unknown part_id={part_id}")

            to_set["updated_at"] = utc_now_iso()
            set_clause = ", ".join(f"{k} = ?" for k in to_set)
            params = list(to_set.values()) + [part_id]
            self.db.execute(f"UPDATE parts SET {set_clause} WHERE id = ?", tuple(params))

            if "slot_id" in fields:
                new_qty = int(fields.get("qty", current.qty))
                self._set_single_location_state(part_id, fields["slot_id"], new_qty)
            elif "qty" in fields:
                self._adjust_locations_for_qty_change(part_id, current.qty, int(fields["qty"]))

        updated = self.get_part_by_id(part_id)
        assert updated is not None
        return updated

    def delete_part(self, part_id: int) -> None:
        """Delete a part by ID. Cascades to aliases and placements."""
        self.db.execute("DELETE FROM parts WHERE id = ?", (part_id,))

    def adjust_qty(self, part_id: int, delta: int) -> int:
        """Adjust quantity by delta, return new qty. Prevents going negative."""
        with self.db.transaction():
            current = self.get_part_by_id(part_id)
            if current is None:
                raise ValueError(f"Unknown part_id={part_id}")
            new_qty = max(0, current.qty + delta)
            self.db.execute(
                "UPDATE parts SET qty = ?, updated_at = ? WHERE id = ?",
                (new_qty, utc_now_iso(), part_id),
            )
            self._adjust_locations_for_qty_change(part_id, current.qty, new_qty)
        return new_qty

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
        params: tuple = ()
        sql = (
            "SELECT id, name, category, default_package, supplier_sku, qty, notes "
            "FROM parts"
        )
        ids: list[int] | None = None
        if part_ids is not None:
            ids = list(part_ids)
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            sql += f" WHERE id IN ({placeholders})"
            params = tuple(ids)
        else:
            sql += " ORDER BY category, name"

        rows = self.db.query_all(sql, params)
        row_ids = [row["id"] for row in rows]
        locations_by_part = self.list_part_locations_for_parts(row_ids)
        summaries = [
            InventorySummary(
                part_id=row["id"],
                name=row["name"],
                category=row["category"],
                default_package=row["default_package"],
                supplier_sku=row["supplier_sku"],
                total_qty=row["qty"],
                locations=_format_compact_location_summary(locations_by_part.get(row["id"], [])),
                notes=row["notes"],
            )
            for row in rows
        ]
        if ids is not None:
            order = {pid: i for i, pid in enumerate(ids)}
            summaries.sort(key=lambda summary: order.get(summary.part_id, len(ids)))
        return summaries

    def list_part_locations(self, part_id: int) -> list[PartLocation]:
        rows = self.db.query_all(
            """
            SELECT
                pl.*,
                sc.name AS container_name,
                ss.label AS slot_label
            FROM part_locations pl
            JOIN storage_slots ss ON ss.id = pl.slot_id
            JOIN storage_containers sc ON sc.id = ss.container_id
            WHERE pl.part_id = ?
              AND pl.qty > 0
            ORDER BY
                CASE WHEN sc.name = ? THEN 1 ELSE 0 END,
                sc.name,
                ss.label
            """,
            (part_id, _UNASSIGNED_CONTAINER_NAME),
        )
        return [_row_to_part_location(row) for row in rows]

    def list_part_locations_for_parts(self, part_ids: list[int]) -> dict[int, list[PartLocation]]:
        if not part_ids:
            return {}
        placeholders = ",".join("?" for _ in part_ids)
        rows = self.db.query_all(
            f"""
            SELECT
                pl.*,
                sc.name AS container_name,
                ss.label AS slot_label
            FROM part_locations pl
            JOIN storage_slots ss ON ss.id = pl.slot_id
            JOIN storage_containers sc ON sc.id = ss.container_id
            WHERE pl.part_id IN ({placeholders})
              AND pl.qty > 0
            ORDER BY
                pl.part_id,
                CASE WHEN sc.name = ? THEN 1 ELSE 0 END,
                sc.name,
                ss.label
            """,
            tuple(part_ids) + (_UNASSIGNED_CONTAINER_NAME,),
        )
        result: dict[int, list[PartLocation]] = {}
        for row in rows:
            location = _row_to_part_location(row)
            result.setdefault(location.part_id, []).append(location)
        return result

    def list_location_counts(self, part_ids: list[int] | None = None) -> dict[int, int]:
        params: tuple = ()
        sql = (
            "SELECT part_id, COUNT(*) AS cnt "
            "FROM part_locations WHERE qty > 0"
        )
        if part_ids is not None:
            if not part_ids:
                return {}
            placeholders = ",".join("?" for _ in part_ids)
            sql += f" AND part_id IN ({placeholders})"
            params = tuple(part_ids)
        sql += " GROUP BY part_id"
        rows = self.db.query_all(sql, params)
        return {row["part_id"]: row["cnt"] for row in rows}

    def get_part_location(self, part_id: int) -> str:
        """Return formatted location string for a part."""
        return _format_full_location_summary(self.list_part_locations(part_id))

    def replace_part_locations(self, part_id: int, locations: list[tuple[int | None, int]]) -> None:
        part = self.get_part_by_id(part_id)
        if part is None:
            raise ValueError(f"Unknown part_id={part_id}")
        normalized = self._normalize_location_inputs(locations)
        if sum(qty for _slot_id, qty in normalized) != part.qty:
            raise ValueError("Location quantities must sum to the part's total quantity")
        with self.db.transaction():
            self._store_part_locations(part_id, normalized)

    def move_part_location(self, part_id: int, source_slot_id: int, target_slot_id: int | None) -> None:
        locations = self.list_part_locations(part_id)
        merged = {location.slot_id: location.qty for location in locations}
        if source_slot_id not in merged:
            raise ValueError(f"Part #{part_id} is not stored in slot #{source_slot_id}")

        resolved_target = target_slot_id if target_slot_id is not None else self._get_unassigned_slot_id()
        if resolved_target is None:
            raise ValueError("Unassigned slot is not configured")
        if resolved_target == source_slot_id:
            return

        qty = merged.pop(source_slot_id)
        merged[resolved_target] = merged.get(resolved_target, 0) + qty
        self.replace_part_locations(part_id, list(merged.items()))

    def list_parts_by_slot_ids(self, slot_ids: list[int]) -> dict[int, list[Part]]:
        """Return a mapping of slot_id -> list of parts assigned to that slot."""
        if not slot_ids:
            return {}
        placeholders = ",".join("?" * len(slot_ids))
        rows = self.db.query_all(
            f"""
            SELECT
                p.*,
                pl.slot_id AS location_slot_id,
                pl.qty AS location_qty
            FROM part_locations pl
            JOIN parts p ON p.id = pl.part_id
            WHERE pl.slot_id IN ({placeholders})
              AND pl.qty > 0
            ORDER BY p.category, p.name
            """,
            tuple(slot_ids),
        )
        result: dict[int, list[Part]] = {}
        for row in rows:
            part = _row_to_part(row)
            slot_id = row["location_slot_id"]
            part.slot_id = slot_id
            part.qty = row["location_qty"]
            result.setdefault(slot_id, []).append(part)
        return result

    def bulk_update_slot_ids(self, assignments: list[tuple[int, int]]) -> None:
        """Set a single assigned slot for multiple parts."""
        if not assignments:
            return
        with self.db.transaction():
            for part_id, slot_id in assignments:
                part = self.get_part_by_id(part_id)
                if part is None:
                    continue
                self.db.execute(
                    "UPDATE parts SET updated_at = ? WHERE id = ?",
                    (utc_now_iso(), part_id),
                )
                self._set_single_location_state(part_id, slot_id, part.qty)

    def list_distinct_categories(self) -> list[str]:
        rows = self.db.query_all(
            "SELECT DISTINCT category FROM parts WHERE category IS NOT NULL ORDER BY category"
        )
        return [row["category"] for row in rows]

    def list_distinct_packages(self) -> list[str]:
        rows = self.db.query_all(
            "SELECT DISTINCT default_package FROM parts WHERE default_package IS NOT NULL ORDER BY default_package"
        )
        return [row["default_package"] for row in rows]

    def count_bom_references(self, part_id: int) -> int:
        """Count how many bom_lines reference this part."""
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM bom_lines WHERE part_id = ?", (part_id,)
            )
            or 0
        )

    def list_occupied_slot_ids(self) -> set[int]:
        """Return set of slot_ids that have at least one part assigned."""
        rows = self.db.query_all(
            "SELECT DISTINCT slot_id FROM part_locations WHERE qty > 0"
        )
        return {row["slot_id"] for row in rows}

    def count_parts_per_slot(self) -> dict[int, int]:
        """Return {slot_id: count} for all occupied slots."""
        rows = self.db.query_all(
            "SELECT slot_id, COUNT(*) AS cnt FROM part_locations "
            "WHERE qty > 0 GROUP BY slot_id"
        )
        return {row["slot_id"]: row["cnt"] for row in rows}

    def bulk_clear_slot_ids(self, part_ids: list[int]) -> None:
        """Move the given parts to the Unassigned/Main slot."""
        if not part_ids:
            return
        with self.db.transaction():
            for part_id in part_ids:
                part = self.get_part_by_id(part_id)
                if part is None:
                    continue
                self.db.execute(
                    "UPDATE parts SET updated_at = ? WHERE id = ?",
                    (utc_now_iso(), part_id),
                )
                self._set_single_location_state(part_id, None, part.qty)

    def count_occupied_slots_per_container(self) -> dict[int, int]:
        """Return container_id -> count of distinct occupied slots."""
        rows = self.db.query_all(
            """
            SELECT ss.container_id, COUNT(DISTINCT pl.slot_id) AS cnt
            FROM part_locations pl
            JOIN storage_slots ss ON ss.id = pl.slot_id
            WHERE pl.qty > 0
            GROUP BY ss.container_id
            """
        )
        return {row["container_id"]: row["cnt"] for row in rows}

    def list_null_slot_parts(self) -> list[Part]:
        """Return parts with no effective placement rows."""
        rows = self.db.query_all(
            """
            SELECT p.*
            FROM parts p
            LEFT JOIN part_locations pl
                ON pl.part_id = p.id AND pl.qty > 0
            WHERE pl.id IS NULL
            ORDER BY p.category, p.name
            """
        )
        return [_row_to_part(row) for row in rows]

    def count_parts(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM parts") or 0)

    def _get_unassigned_slot_id(self) -> int | None:
        row = self.db.query_one(
            """
            SELECT ss.id
            FROM storage_slots ss
            JOIN storage_containers sc ON sc.id = ss.container_id
            WHERE sc.name = ? AND ss.label = ?
            """,
            (_UNASSIGNED_CONTAINER_NAME, _UNASSIGNED_SLOT_LABEL),
        )
        return int(row["id"]) if row else None

    def _normalize_location_inputs(self, locations: list[tuple[int | None, int]]) -> list[tuple[int, int]]:
        merged: dict[int, int] = {}
        unassigned_slot_id = self._get_unassigned_slot_id()
        for slot_id, qty in locations:
            normalized_qty = int(qty)
            if normalized_qty <= 0:
                continue
            resolved_slot_id = slot_id if slot_id is not None else unassigned_slot_id
            if resolved_slot_id is None:
                raise ValueError("Unassigned slot is not configured")
            merged[resolved_slot_id] = merged.get(resolved_slot_id, 0) + normalized_qty
        return list(merged.items())

    def _store_part_locations(self, part_id: int, locations: list[tuple[int, int]]) -> None:
        self.db.execute("DELETE FROM part_locations WHERE part_id = ?", (part_id,))
        if locations:
            now = utc_now_iso()
            self.db.executemany(
                """
                INSERT INTO part_locations (part_id, slot_id, qty, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (part_id, slot_id, qty, now, now)
                    for slot_id, qty in locations
                ],
            )
        self._sync_denormalized_slot_id(part_id)

    def _sync_denormalized_slot_id(self, part_id: int) -> None:
        rows = self.db.query_all(
            "SELECT slot_id FROM part_locations WHERE part_id = ? AND qty > 0",
            (part_id,),
        )
        unassigned_slot_id = self._get_unassigned_slot_id()
        slot_id: int | None = None
        if len(rows) == 1:
            candidate = int(rows[0]["slot_id"])
            if candidate != unassigned_slot_id:
                slot_id = candidate
        self.db.execute(
            "UPDATE parts SET slot_id = ? WHERE id = ?",
            (slot_id, part_id),
        )

    def _set_single_location_state(self, part_id: int, slot_id: int | None, total_qty: int) -> None:
        if total_qty <= 0:
            self._store_part_locations(part_id, [])
            return
        target_slot_id = slot_id if slot_id is not None else self._get_unassigned_slot_id()
        if target_slot_id is None:
            self._store_part_locations(part_id, [])
            return
        self._store_part_locations(part_id, [(target_slot_id, total_qty)])

    def _adjust_locations_for_qty_change(self, part_id: int, old_qty: int, new_qty: int) -> None:
        locations = self.list_part_locations(part_id)
        if new_qty <= 0:
            self._store_part_locations(part_id, [])
            return
        if not locations:
            self._set_single_location_state(part_id, None, new_qty)
            return
        if len(locations) == 1:
            self._store_part_locations(part_id, [(locations[0].slot_id, new_qty)])
            return

        delta = new_qty - old_qty
        if delta == 0:
            return

        merged = {location.slot_id: location.qty for location in locations}
        unassigned_slot_id = self._get_unassigned_slot_id()
        if unassigned_slot_id is None:
            raise ValueError("Unassigned slot is not configured")

        if delta > 0:
            merged[unassigned_slot_id] = merged.get(unassigned_slot_id, 0) + delta
            self._store_part_locations(part_id, list(merged.items()))
            return

        available_unassigned = merged.get(unassigned_slot_id, 0)
        needed = -delta
        if available_unassigned < needed:
            raise ValueError(
                "Cannot reduce total quantity for a split part without editing its locations"
            )
        remaining_unassigned = available_unassigned - needed
        if remaining_unassigned > 0:
            merged[unassigned_slot_id] = remaining_unassigned
        else:
            merged.pop(unassigned_slot_id, None)
        self._store_part_locations(part_id, list(merged.items()))
