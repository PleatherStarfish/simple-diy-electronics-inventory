"""CSV export and import — human-readable data portability format.

Exports all app tables as CSV files inside a zip archive.  A
``manifest.json`` records the schema version so the importer can
validate compatibility.

This complements the SQLite-snapshot backup (``backup.py``) with a
format that can be read, diffed, and edited in any spreadsheet tool.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Tables in topological order (parents before children) so that
# foreign-key constraints are satisfied during import.
_EXPORT_TABLES: list[str] = [
    "storage_containers",
    "storage_slots",
    "parts",
    "part_aliases",
    "modules",
    "bom_lines",
    "builds",
    "build_updates",
    "settings",
    "audit_events",
    "assignment_runs",
]

# Reverse order for deletion (children before parents).
_DELETE_ORDER: list[str] = list(reversed(_EXPORT_TABLES))

_MANIFEST_NAME = "manifest.json"


class CSVBackupError(Exception):
    """Raised when a CSV export or import operation fails."""


def default_csv_backup_filename() -> str:
    """Return a timestamped default filename for CSV backup archives."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"synth_inventory_csv_{stamp}.zip"


# ── Export ────────────────────────────────────────────────────────────


def export_csv(conn: sqlite3.Connection, dest: Path) -> Path:
    """Export all app tables to a zip of CSV files at *dest*.

    Returns the resolved destination path on success.
    """
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]

    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write manifest
            manifest = {
                "format": "synth_inventory_csv",
                "schema_version": int(user_version),
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "tables": _EXPORT_TABLES,
            }
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))

            # Write each table as a CSV
            for table in _EXPORT_TABLES:
                cursor = conn.execute(f"SELECT * FROM [{table}]")  # noqa: S608
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow(row)

                zf.writestr(f"{table}.csv", buf.getvalue())
    except Exception:
        # Clean up partial file on failure
        if dest.exists():
            dest.unlink()
        raise

    logger.info("CSV backup exported to %s", dest)
    return dest


# ── Validation ────────────────────────────────────────────────────────


def validate_csv_archive(path: Path) -> dict:
    """Validate that *path* is a well-formed CSV backup archive.

    Returns the parsed manifest on success.
    Raises ``CSVBackupError`` on any problem.
    """
    path = path.resolve()
    if not path.exists():
        raise CSVBackupError(f"File does not exist: {path}")

    try:
        zf = zipfile.ZipFile(path, "r")
    except Exception as exc:
        raise CSVBackupError(f"Not a valid zip archive: {exc}") from exc

    with zf:
        # Check manifest
        if _MANIFEST_NAME not in zf.namelist():
            raise CSVBackupError(
                f"Archive is missing {_MANIFEST_NAME} — not a valid CSV backup."
            )

        try:
            manifest = json.loads(zf.read(_MANIFEST_NAME))
        except (json.JSONDecodeError, Exception) as exc:
            raise CSVBackupError(f"Cannot parse {_MANIFEST_NAME}: {exc}") from exc

        if manifest.get("format") != "synth_inventory_csv":
            raise CSVBackupError(
                f"Unknown archive format: {manifest.get('format')}"
            )

        # Check required CSV files
        archive_files = set(zf.namelist())
        for table in _EXPORT_TABLES:
            csv_name = f"{table}.csv"
            if csv_name not in archive_files:
                raise CSVBackupError(
                    f"Archive is missing required file: {csv_name}"
                )

    return manifest


# ── Import ────────────────────────────────────────────────────────────


def import_csv(
    archive_path: Path,
    conn: sqlite3.Connection,
) -> dict[str, int]:
    """Import CSV data from a backup archive into the database.

    Replaces all existing data in the target tables.
    Returns a dict of {table_name: rows_imported}.

    Raises ``CSVBackupError`` if validation fails or the import
    encounters an error.  On failure the database is rolled back
    to its prior state.
    """
    archive_path = archive_path.resolve()
    manifest = validate_csv_archive(archive_path)

    row_counts: dict[str, int] = {}

    # Commit any pending implicit transaction before starting ours
    try:
        conn.commit()
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("BEGIN")
    try:
        # Delete existing data (children first)
        for table in _DELETE_ORDER:
            conn.execute(f"DELETE FROM [{table}]")  # noqa: S608

        with zipfile.ZipFile(archive_path, "r") as zf:
            for table in _EXPORT_TABLES:
                csv_name = f"{table}.csv"
                raw = zf.read(csv_name).decode("utf-8")
                reader = csv.reader(io.StringIO(raw))

                columns = next(reader)  # header row
                placeholders = ", ".join("?" for _ in columns)
                col_list = ", ".join(f"[{c}]" for c in columns)
                insert_sql = (
                    f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})"  # noqa: S608
                )

                count = 0
                for row in reader:
                    if not row:
                        continue
                    # Convert empty strings back to None for nullable columns
                    values = [None if v == "" else v for v in row]
                    conn.execute(insert_sql, values)
                    count += 1

                row_counts[table] = count

        # Verify FK integrity before committing
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_check:
            tables_with_violations = {row[0] for row in fk_check}
            raise CSVBackupError(
                f"Foreign key violations after import in: "
                f"{', '.join(sorted(tables_with_violations))}"
            )

        conn.commit()
    except CSVBackupError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise CSVBackupError(f"Import failed: {exc}") from exc
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")

    logger.info(
        "CSV import complete: %s",
        ", ".join(f"{t}={n}" for t, n in row_counts.items()),
    )
    return row_counts
