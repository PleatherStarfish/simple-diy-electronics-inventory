from __future__ import annotations

import logging
from pathlib import Path

from eurorack_inventory.db.connection import Database

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Apply SQL migrations tracked by SQLite PRAGMA user_version."""

    def __init__(self, db: Database, migrations_dir: Path) -> None:
        self.db = db
        self.migrations_dir = migrations_dir

    def current_version(self) -> int:
        value = self.db.scalar("PRAGMA user_version;")
        return int(value or 0)

    def available_migrations(self) -> list[tuple[int, Path]]:
        migrations: list[tuple[int, Path]] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            prefix = path.stem.split("_", 1)[0]
            migrations.append((int(prefix), path))
        return migrations

    def apply(self) -> None:
        current = self.current_version()
        for version, path in self.available_migrations():
            if version <= current:
                continue
            logger.info("Applying migration %s from %s", version, path.name)
            sql = path.read_text(encoding="utf-8")
            with self.db.transaction() as conn:
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version = {version};")
            current = version
        logger.info("Database schema version is %s", current)
