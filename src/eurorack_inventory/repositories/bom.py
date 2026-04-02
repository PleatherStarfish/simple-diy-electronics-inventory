from __future__ import annotations

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import BomSource, NormalizedBomItem, RawBomItem


def _row_to_bom_source(row) -> BomSource:
    return BomSource(
        id=row["id"],
        filename=row["filename"],
        file_path=row["file_path"],
        file_hash=row["file_hash"],
        source_kind=row["source_kind"],
        parser_key=row["parser_key"],
        manufacturer=row["manufacturer"],
        module_name=row["module_name"],
        extracted_at=row["extracted_at"],
        notes=row["notes"],
        promoted_project_id=row["promoted_project_id"],
    )


def _row_to_raw_item(row) -> RawBomItem:
    return RawBomItem(
        id=row["id"],
        bom_source_id=row["bom_source_id"],
        line_number=row["line_number"],
        raw_description=row["raw_description"],
        raw_qty=row["raw_qty"],
        raw_reference=row["raw_reference"],
        raw_supplier_pn=row["raw_supplier_pn"],
        raw_notes=row["raw_notes"],
    )


def _row_to_normalized_item(row) -> NormalizedBomItem:
    return NormalizedBomItem(
        id=row["id"],
        bom_source_id=row["bom_source_id"],
        raw_item_id=row["raw_item_id"],
        component_type=row["component_type"],
        normalized_value=row["normalized_value"],
        qty=row["qty"],
        package_hint=row["package_hint"],
        reference=row["reference"],
        tayda_pn=row["tayda_pn"],
        mouser_pn=row["mouser_pn"],
        part_id=row["part_id"],
        match_confidence=row["match_confidence"],
        match_status=row["match_status"],
        is_verified=bool(row["is_verified"]),
        notes=row["notes"],
    )


class BomRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── BomSource CRUD ──────────────────────────────────────────────

    def create_bom_source(self, source: BomSource) -> BomSource:
        cursor = self.db.execute(
            """
            INSERT INTO bom_sources
                (filename, file_path, file_hash, source_kind, parser_key,
                 manufacturer, module_name, extracted_at, notes, promoted_project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.filename,
                source.file_path,
                source.file_hash,
                source.source_kind,
                source.parser_key,
                source.manufacturer,
                source.module_name,
                source.extracted_at,
                source.notes,
                source.promoted_project_id,
            ),
        )
        row = self.db.query_one("SELECT * FROM bom_sources WHERE id = ?", (int(cursor.lastrowid),))
        assert row is not None
        return _row_to_bom_source(row)

    def get_bom_source(self, source_id: int) -> BomSource | None:
        row = self.db.query_one("SELECT * FROM bom_sources WHERE id = ?", (source_id,))
        return _row_to_bom_source(row) if row else None

    def list_bom_sources(self) -> list[BomSource]:
        rows = self.db.query_all("SELECT * FROM bom_sources ORDER BY manufacturer, module_name")
        return [_row_to_bom_source(row) for row in rows]

    def get_confirmation_counts(self) -> dict[int, tuple[int, int]]:
        """Return {source_id: (confirmed_count, total_count)} for all sources."""
        rows = self.db.query_all(
            """
            SELECT bom_source_id,
                   SUM(is_verified) AS confirmed,
                   COUNT(*) AS total
            FROM normalized_bom_items
            GROUP BY bom_source_id
            """
        )
        return {row["bom_source_id"]: (int(row["confirmed"]), int(row["total"])) for row in rows}

    def find_by_hash_and_module(self, file_hash: str, module_name: str) -> BomSource | None:
        row = self.db.query_one(
            "SELECT * FROM bom_sources WHERE file_hash = ? AND module_name = ?",
            (file_hash, module_name),
        )
        return _row_to_bom_source(row) if row else None

    def delete_bom_source(self, source_id: int) -> None:
        self.db.execute("DELETE FROM bom_sources WHERE id = ?", (source_id,))

    def rename_bom_source(self, source_id: int, new_name: str) -> None:
        self.db.execute(
            "UPDATE bom_sources SET module_name = ? WHERE id = ?",
            (new_name, source_id),
        )

    def update_file_path(self, source_id: int, new_path: str) -> None:
        self.db.execute(
            "UPDATE bom_sources SET file_path = ? WHERE id = ?",
            (new_path, source_id),
        )

    def set_promoted_project_id(self, source_id: int, project_id: int) -> None:
        self.db.execute(
            "UPDATE bom_sources SET promoted_project_id = ? WHERE id = ?",
            (project_id, source_id),
        )

    def count_bom_sources(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM bom_sources") or 0)

    # ── RawBomItem ──────────────────────────────────────────────────

    def add_raw_items_bulk(self, items: list[RawBomItem]) -> None:
        self.db.executemany(
            """
            INSERT INTO raw_bom_items
                (bom_source_id, line_number, raw_description, raw_qty,
                 raw_reference, raw_supplier_pn, raw_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.bom_source_id,
                    item.line_number,
                    item.raw_description,
                    item.raw_qty,
                    item.raw_reference,
                    item.raw_supplier_pn,
                    item.raw_notes,
                )
                for item in items
            ],
        )

    def list_raw_items(self, source_id: int) -> list[RawBomItem]:
        rows = self.db.query_all(
            "SELECT * FROM raw_bom_items WHERE bom_source_id = ? ORDER BY line_number",
            (source_id,),
        )
        return [_row_to_raw_item(row) for row in rows]

    def delete_raw_items(self, source_id: int) -> None:
        self.db.execute("DELETE FROM raw_bom_items WHERE bom_source_id = ?", (source_id,))

    # ── NormalizedBomItem ───────────────────────────────────────────

    def add_normalized_items_bulk(self, items: list[NormalizedBomItem]) -> None:
        self.db.executemany(
            """
            INSERT INTO normalized_bom_items
                (bom_source_id, raw_item_id, component_type, normalized_value,
                 qty, package_hint, reference, tayda_pn, mouser_pn,
                 part_id, match_confidence, match_status, is_verified, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.bom_source_id,
                    item.raw_item_id,
                    item.component_type,
                    item.normalized_value,
                    item.qty,
                    item.package_hint,
                    item.reference,
                    item.tayda_pn,
                    item.mouser_pn,
                    item.part_id,
                    item.match_confidence,
                    item.match_status,
                    int(item.is_verified),
                    item.notes,
                )
                for item in items
            ],
        )

    def list_normalized_items(self, source_id: int) -> list[NormalizedBomItem]:
        rows = self.db.query_all(
            """
            SELECT * FROM normalized_bom_items
            WHERE bom_source_id = ? ORDER BY id
            """,
            (source_id,),
        )
        return [_row_to_normalized_item(row) for row in rows]

    def get_normalized_item(self, item_id: int) -> NormalizedBomItem | None:
        row = self.db.query_one("SELECT * FROM normalized_bom_items WHERE id = ?", (item_id,))
        return _row_to_normalized_item(row) if row else None

    def list_unmatched_items(self, source_id: int) -> list[NormalizedBomItem]:
        rows = self.db.query_all(
            """
            SELECT * FROM normalized_bom_items
            WHERE bom_source_id = ? AND match_status = 'unmatched'
            ORDER BY id
            """,
            (source_id,),
        )
        return [_row_to_normalized_item(row) for row in rows]

    def update_normalized_item(self, item_id: int, **fields) -> NormalizedBomItem:
        allowed = {
            "component_type", "normalized_value", "qty", "package_hint",
            "reference", "tayda_pn", "mouser_pn", "notes",
            "is_verified", "match_status", "part_id", "match_confidence",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            item = self.get_normalized_item(item_id)
            assert item is not None
            return item

        if "is_verified" in updates:
            updates["is_verified"] = int(updates["is_verified"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [item_id]
        self.db.execute(
            f"UPDATE normalized_bom_items SET {set_clause} WHERE id = ?",
            tuple(values),
        )
        item = self.get_normalized_item(item_id)
        assert item is not None
        return item

    def link_to_part(
        self,
        item_id: int,
        part_id: int,
        confidence: float | None,
        status: str = "manually_matched",
    ) -> NormalizedBomItem:
        return self.update_normalized_item(
            item_id,
            part_id=part_id,
            match_confidence=confidence,
            match_status=status,
        )

    def unlink_part(self, item_id: int) -> NormalizedBomItem:
        return self.update_normalized_item(
            item_id,
            part_id=None,
            match_confidence=None,
            match_status="unmatched",
        )

    def delete_normalized_items(self, source_id: int) -> None:
        self.db.execute(
            "DELETE FROM normalized_bom_items WHERE bom_source_id = ?",
            (source_id,),
        )

    # ── Shopping list query ─────────────────────────────────────────

    def get_shopping_list(self, source_ids: list[int]) -> list[dict]:
        if not source_ids:
            return []

        placeholders = ", ".join("?" for _ in source_ids)
        rows = self.db.query_all(
            f"""
            SELECT
                n.normalized_value,
                n.component_type,
                n.package_hint,
                n.tayda_pn,
                n.mouser_pn,
                n.part_id,
                n.match_status,
                n.bom_source_id,
                bs.module_name,
                n.qty AS qty_needed,
                COALESCE(p.qty, 0) AS qty_available
            FROM normalized_bom_items n
            JOIN bom_sources bs ON bs.id = n.bom_source_id
            LEFT JOIN parts p ON p.id = n.part_id
            WHERE n.bom_source_id IN ({placeholders})
              AND n.match_status != 'skipped'
            ORDER BY n.component_type, n.normalized_value
            """,
            tuple(source_ids),
        )

        # Aggregate: by part_id when matched, otherwise by
        # (normalized_value, component_type, package_hint)
        aggregated: dict[tuple, dict] = {}
        for row in rows:
            part_id = row["part_id"]
            if part_id is not None:
                key = ("part", part_id)
            else:
                key = ("value", row["normalized_value"], row["component_type"], row["package_hint"])

            if key not in aggregated:
                aggregated[key] = {
                    "normalized_value": row["normalized_value"],
                    "component_type": row["component_type"],
                    "package_hint": row["package_hint"],
                    "tayda_pn": row["tayda_pn"],
                    "mouser_pn": row["mouser_pn"],
                    "part_id": part_id,
                    "qty_needed": 0,
                    "qty_available": row["qty_available"],
                    "bom_source_names": set(),
                }

            entry = aggregated[key]
            entry["qty_needed"] += row["qty_needed"]
            entry["bom_source_names"].add(row["module_name"])
            # Keep first non-null PNs
            if not entry["tayda_pn"] and row["tayda_pn"]:
                entry["tayda_pn"] = row["tayda_pn"]
            if not entry["mouser_pn"] and row["mouser_pn"]:
                entry["mouser_pn"] = row["mouser_pn"]

        result = []
        for entry in aggregated.values():
            qty_needed = entry["qty_needed"]
            qty_available = entry["qty_available"]
            entry["qty_to_buy"] = max(0, qty_needed - qty_available)
            entry["bom_source_names"] = sorted(entry["bom_source_names"])
            result.append(entry)

        return result
