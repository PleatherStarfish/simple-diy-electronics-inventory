from __future__ import annotations

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import BomLine, Build, BuildUpdate, Module, utc_now_iso


def _row_to_module(row) -> Module:
    return Module(
        id=row["id"],
        fingerprint=row["fingerprint"],
        name=row["name"],
        maker=row["maker"],
        revision=row["revision"],
        source_url=row["source_url"],
        notes=row["notes"],
    )


def _row_to_bom_line(row) -> BomLine:
    return BomLine(
        id=row["id"],
        module_id=row["module_id"],
        part_id=row["part_id"],
        qty_required=row["qty_required"],
        reference_note=row["reference_note"],
        is_optional=bool(row["is_optional"]),
    )


def _row_to_build(row) -> Build:
    return Build(
        id=row["id"],
        module_id=row["module_id"],
        nickname=row["nickname"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        notes=row["notes"],
    )


def _row_to_build_update(row) -> BuildUpdate:
    return BuildUpdate(
        id=row["id"],
        build_id=row["build_id"],
        created_at=row["created_at"],
        status=row["status"],
        note=row["note"],
    )


class ModuleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_module(self, module: Module) -> Module:
        existing = self.db.query_one(
            "SELECT * FROM modules WHERE fingerprint = ?",
            (module.fingerprint,),
        )
        if existing:
            self.db.execute(
                """
                UPDATE modules
                SET name = ?, maker = ?, revision = ?, source_url = ?, notes = ?
                WHERE fingerprint = ?
                """,
                (
                    module.name,
                    module.maker,
                    module.revision,
                    module.source_url,
                    module.notes,
                    module.fingerprint,
                ),
            )
            row = self.db.query_one("SELECT * FROM modules WHERE fingerprint = ?", (module.fingerprint,))
            assert row is not None
            return _row_to_module(row)

        cursor = self.db.execute(
            """
            INSERT INTO modules (fingerprint, name, maker, revision, source_url, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                module.fingerprint,
                module.name,
                module.maker,
                module.revision,
                module.source_url,
                module.notes,
            ),
        )
        created = self.get_module(int(cursor.lastrowid))
        assert created is not None
        return created

    def get_module(self, module_id: int) -> Module | None:
        row = self.db.query_one("SELECT * FROM modules WHERE id = ?", (module_id,))
        return _row_to_module(row) if row else None

    def list_modules(self) -> list[Module]:
        rows = self.db.query_all("SELECT * FROM modules ORDER BY maker, name")
        return [_row_to_module(row) for row in rows]

    def add_bom_line(self, bom_line: BomLine) -> BomLine:
        cursor = self.db.execute(
            """
            INSERT INTO bom_lines (module_id, part_id, qty_required, reference_note, is_optional)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                bom_line.module_id,
                bom_line.part_id,
                bom_line.qty_required,
                bom_line.reference_note,
                int(bom_line.is_optional),
            ),
        )
        row = self.db.query_one("SELECT * FROM bom_lines WHERE id = ?", (int(cursor.lastrowid),))
        assert row is not None
        return _row_to_bom_line(row)

    def list_bom_lines(self, module_id: int) -> list[BomLine]:
        rows = self.db.query_all(
            "SELECT * FROM bom_lines WHERE module_id = ? ORDER BY id",
            (module_id,),
        )
        return [_row_to_bom_line(row) for row in rows]

    def create_build(self, build: Build) -> Build:
        cursor = self.db.execute(
            """
            INSERT INTO builds (module_id, nickname, status, started_at, completed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                build.module_id,
                build.nickname,
                build.status,
                build.started_at or utc_now_iso(),
                build.completed_at,
                build.notes,
            ),
        )
        row = self.db.query_one("SELECT * FROM builds WHERE id = ?", (int(cursor.lastrowid),))
        assert row is not None
        return _row_to_build(row)

    def list_builds(self, module_id: int) -> list[Build]:
        rows = self.db.query_all(
            "SELECT * FROM builds WHERE module_id = ? ORDER BY started_at DESC",
            (module_id,),
        )
        return [_row_to_build(row) for row in rows]

    def add_build_update(self, update: BuildUpdate) -> BuildUpdate:
        cursor = self.db.execute(
            """
            INSERT INTO build_updates (build_id, created_at, status, note)
            VALUES (?, ?, ?, ?)
            """,
            (
                update.build_id,
                update.created_at or utc_now_iso(),
                update.status,
                update.note,
            ),
        )
        row = self.db.query_one("SELECT * FROM build_updates WHERE id = ?", (int(cursor.lastrowid),))
        assert row is not None
        return _row_to_build_update(row)

    def list_build_updates(self, build_id: int) -> list[BuildUpdate]:
        rows = self.db.query_all(
            "SELECT * FROM build_updates WHERE build_id = ? ORDER BY created_at DESC",
            (build_id,),
        )
        return [_row_to_build_update(row) for row in rows]

    def count_modules(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM modules") or 0)
