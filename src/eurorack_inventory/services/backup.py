"""Backup and restore service — full SQLite snapshot approach.

Export creates a consistent snapshot of the live database using
``sqlite3.Connection.backup()``, which is safe even in WAL mode.

Restore validates the incoming file, creates a safety copy of the
current database, then replaces it.  The caller (UI or CLI) is
expected to exit the process after a successful restore so the app
relaunches against the new data.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Tables that must exist in a valid backup for this app.
_REQUIRED_TABLES = frozenset(
    {
        "parts",
        "part_aliases",
        "storage_containers",
        "storage_slots",
        "modules",
        "bom_lines",
        "builds",
        "build_updates",
        "settings",
        "audit_events",
        "assignment_runs",
    }
)


class BackupError(Exception):
    """Raised when a backup or restore operation fails."""


def default_backup_filename() -> str:
    """Return a timestamped default filename for backups."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"synth_inventory_backup_{stamp}.db"


def _resolve_paths(live_db: Path, target: Path) -> tuple[Path, Path]:
    live = live_db.resolve()
    tgt = target.resolve()
    if live == tgt:
        raise BackupError(
            f"Target path is the same as the live database: {live}\n"
            "Choose a different location."
        )
    return live, tgt


# ── Export ────────────────────────────────────────────────────────────

def export_backup(live_conn: sqlite3.Connection, dest: Path) -> Path:
    """Create a consistent SQLite snapshot at *dest*.

    Uses the C-level backup API so WAL pages are included correctly.
    Returns the resolved destination path on success.
    """
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    backup_conn = sqlite3.connect(dest)
    try:
        live_conn.backup(backup_conn)
        backup_conn.close()
    except Exception:
        backup_conn.close()
        # Clean up partial file on failure
        if dest.exists():
            dest.unlink()
        raise

    logger.info("Backup exported to %s", dest)
    return dest


# ── Validation ────────────────────────────────────────────────────────

def validate_backup(path: Path) -> int:
    """Open *path* as a SQLite database and check that it looks like a
    valid app backup.  Returns the ``user_version`` on success.

    Raises ``BackupError`` on any problem.
    """
    path = path.resolve()
    if not path.exists():
        raise BackupError(f"File does not exist: {path}")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise BackupError(f"Cannot open as SQLite database: {exc}") from exc

    try:
        # Quick integrity check
        result = conn.execute("PRAGMA quick_check;").fetchone()
        if result[0] != "ok":
            raise BackupError(f"SQLite integrity check failed: {result[0]}")

        # Check required tables
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
        table_names = {row[0] for row in rows}

        missing = _REQUIRED_TABLES - table_names
        if missing:
            raise BackupError(
                f"Backup is missing required tables: {', '.join(sorted(missing))}"
            )

        user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
        return int(user_version)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f"Validation failed: {exc}") from exc
    finally:
        conn.close()


# ── Restore ───────────────────────────────────────────────────────────

def _remove_sidecars(db_path: Path) -> None:
    """Delete WAL and SHM sidecar files for *db_path* if they exist."""
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.parent / (db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
            logger.info("Removed stale sidecar %s", sidecar)


def restore_backup(
    backup_path: Path,
    live_db_path: Path,
    *,
    live_conn: sqlite3.Connection | None = None,
) -> Path:
    """Replace the live database with the validated backup.

    Steps:
    1. Validate the backup file.
    2. Close *live_conn* if provided.
    3. Create a timestamped safety copy of the current live DB.
    4. Replace the live DB file with the backup.
    5. Clean up stale WAL/SHM sidecars.

    Returns the path to the safety copy.

    Raises ``BackupError`` if validation fails or the copy cannot
    be completed.  On failure the live database is left intact.
    """
    backup_path = backup_path.resolve()
    live_db_path = live_db_path.resolve()

    if backup_path == live_db_path:
        raise BackupError(
            "Cannot restore from the live database file itself.\n"
            "Choose a different backup file."
        )

    # Step 1 — validate before touching anything
    validate_backup(backup_path)

    # Step 2 — close live connection
    if live_conn is not None:
        live_conn.close()

    # Step 3 — safety copy
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safety_name = f"{live_db_path.stem}_pre_restore_{stamp}{live_db_path.suffix}"
    safety_path = live_db_path.parent / safety_name

    if live_db_path.exists():
        try:
            # Use SQLite backup API for a clean safety copy too,
            # in case the live DB is still in WAL mode on disk.
            src = sqlite3.connect(f"file:{live_db_path}?mode=ro", uri=True)
            dst = sqlite3.connect(safety_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        except Exception as exc:
            raise BackupError(
                f"Failed to create safety copy at {safety_path}: {exc}"
            ) from exc

    # Step 4 — replace live DB with backup
    try:
        # Remove the old live file and its sidecars
        _remove_sidecars(live_db_path)
        if live_db_path.exists():
            live_db_path.unlink()

        # Copy backup into place using SQLite backup API for consistency
        src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        dst = sqlite3.connect(live_db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f"Failed to restore backup: {exc}") from exc

    # Step 5 — clean sidecars (the new file is in rollback-journal mode)
    _remove_sidecars(live_db_path)

    logger.info(
        "Restored backup from %s → %s (safety copy at %s)",
        backup_path,
        live_db_path,
        safety_path,
    )
    return safety_path
