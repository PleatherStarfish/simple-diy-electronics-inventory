"""Tests for the backup / restore service."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.backup import (
    BackupError,
    export_backup,
    restore_backup,
    validate_backup,
)
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.projects import ProjectService
from eurorack_inventory.services.settings import SettingsRepository
from eurorack_inventory.services.storage import StorageService

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"
)


def _make_db(path: Path) -> Database:
    db = Database(path)
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    return db


def _seed_representative_data(db: Database) -> dict:
    """Populate every persisted domain and return expected reference values."""
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    project_repo = ProjectRepository(db)
    audit_repo = AuditRepository(db)
    settings_repo = SettingsRepository(db)
    inventory = InventoryService(part_repo, storage_repo, audit_repo)
    storage = StorageService(storage_repo, audit_repo)
    projects = ProjectService(project_repo, part_repo, audit_repo)

    # Storage container + slot
    slot = storage.ensure_default_unassigned_slot()

    container = storage.create_container(
        name="Grid Box A", container_type="grid_box",
        metadata={"rows": 4, "cols": 6},
    )
    grid_slot = storage.create_grid_slot(
        container_id=container.id, label="A1",
    )

    # Part with alias
    part = inventory.upsert_part(
        name="100nF capacitor",
        category="Capacitors",
        qty=200,
        slot_id=grid_slot.id,
        supplier_sku="A-553",
        package="SMD 0805",
        notes="MLCC",
    )
    part_repo.add_alias(part.id, "0.1uF cap", "0.1uf cap")

    # Settings
    settings_repo.set_raw("test_key", "test_value")

    # Project + BOM + build + build_update
    project = projects.upsert_project(name="Dual VCA", maker="NLC")
    bom = projects.add_bom_line(
        project_id=project.id, part_id=part.id, qty_required=4
    )
    build = projects.create_build(project_id=project.id, nickname="Build #1")
    build_update = projects.add_build_update(
        build_id=build.id, status="in_progress", note="Started soldering"
    )

    # Assignment run (direct insert — mirrors what AssignmentService does)
    db.execute(
        """
        INSERT INTO assignment_runs (created_at, mode, scope_json, plan_json, snapshot_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "2025-01-01T00:00:00Z",
            "full_rebuild",
            json.dumps({"all_parts": True}),
            json.dumps([[part.id, grid_slot.id]]),
            json.dumps([{"part_id": part.id, "old_slot": None}]),
        ),
    )
    db.conn.commit()

    # Audit events are already created by the service calls above,
    # but let's verify at least one exists.
    audit_count = db.scalar("SELECT COUNT(*) FROM audit_events")

    return {
        "part_name": part.name,
        "part_qty": part.qty,
        "part_slot_id": part.slot_id,
        "part_supplier_sku": "A-553",
        "alias": "0.1uF cap",
        "container_name": container.name,
        "setting_key": "test_key",
        "setting_value": "test_value",
        "project_name": "Dual VCA",
        "build_nickname": "Build #1",
        "audit_count": audit_count,
    }


# ── Export / Restore round-trip ──────────────────────────────────────


def test_export_and_restore_round_trip(tmp_path: Path) -> None:
    """Seed a DB, export, wipe, restore, and verify all data survives."""
    live_path = tmp_path / "live.db"
    db = _make_db(live_path)
    expected = _seed_representative_data(db)

    # Export
    backup_path = tmp_path / "backup.db"
    export_backup(db.conn, backup_path)
    db.close()

    assert backup_path.exists()

    # Simulate a wiped database
    live_path.unlink()
    fresh_db = _make_db(live_path)
    assert fresh_db.scalar("SELECT COUNT(*) FROM parts") == 0
    fresh_db.close()

    # Restore
    safety = restore_backup(backup_path, live_path)
    assert safety.exists()

    # Reopen and verify
    restored_db = _make_db(live_path)

    # Parts
    part_row = restored_db.query_one("SELECT * FROM parts WHERE name = ?", (expected["part_name"],))
    assert part_row is not None
    assert part_row["qty"] == expected["part_qty"]
    assert part_row["slot_id"] == expected["part_slot_id"]
    assert part_row["supplier_sku"] == expected["part_supplier_sku"]

    # Part aliases
    alias_row = restored_db.query_one(
        "SELECT * FROM part_aliases WHERE alias = ?", (expected["alias"],)
    )
    assert alias_row is not None

    # Storage containers and slots
    container_row = restored_db.query_one(
        "SELECT * FROM storage_containers WHERE name = ?", (expected["container_name"],)
    )
    assert container_row is not None
    slot_count = restored_db.scalar(
        "SELECT COUNT(*) FROM storage_slots WHERE container_id = ?",
        (container_row["id"],),
    )
    assert slot_count > 0

    # Settings
    setting_row = restored_db.query_one(
        "SELECT value FROM settings WHERE key = ?", (expected["setting_key"],)
    )
    assert setting_row is not None
    assert setting_row["value"] == expected["setting_value"]

    # Modules (projects)
    project_row = restored_db.query_one(
        "SELECT * FROM modules WHERE name = ?", (expected["project_name"],)
    )
    assert project_row is not None

    # BOM lines
    bom_count = restored_db.scalar(
        "SELECT COUNT(*) FROM bom_lines WHERE module_id = ?", (project_row["id"],)
    )
    assert bom_count >= 1

    # Builds and build updates
    build_row = restored_db.query_one(
        "SELECT * FROM builds WHERE module_id = ?", (project_row["id"],)
    )
    assert build_row is not None
    assert build_row["nickname"] == expected["build_nickname"]

    update_count = restored_db.scalar(
        "SELECT COUNT(*) FROM build_updates WHERE build_id = ?", (build_row["id"],)
    )
    assert update_count >= 1

    # Assignment runs
    run_count = restored_db.scalar("SELECT COUNT(*) FROM assignment_runs")
    assert run_count >= 1

    # Audit events
    audit_count = restored_db.scalar("SELECT COUNT(*) FROM audit_events")
    assert audit_count >= expected["audit_count"]

    # Schema version preserved
    user_version = restored_db.scalar("PRAGMA user_version")
    assert int(user_version) > 0

    restored_db.close()


# ── Validation ────────────────────────────────────────────────────────


def test_validate_backup_accepts_good_file(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "good.db")
    db.close()
    version = validate_backup(tmp_path / "good.db")
    assert version > 0


def test_validate_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="does not exist"):
        validate_backup(tmp_path / "nope.db")


def test_validate_rejects_non_sqlite_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_text("not a database")
    with pytest.raises(BackupError):
        validate_backup(bad)


def test_validate_rejects_missing_tables(tmp_path: Path) -> None:
    """A SQLite file without the app's tables should fail validation."""
    empty_db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db_path)
    conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(BackupError, match="missing required tables"):
        validate_backup(empty_db_path)


# ── Failure safety ────────────────────────────────────────────────────


def test_invalid_backup_does_not_overwrite_live_db(tmp_path: Path) -> None:
    """If the backup file is invalid, the live DB must remain untouched."""
    live_path = tmp_path / "live.db"
    db = _make_db(live_path)
    _seed_representative_data(db)
    original_count = db.scalar("SELECT COUNT(*) FROM parts")
    db.close()

    bad_backup = tmp_path / "bad_backup.db"
    bad_backup.write_text("this is not a database")

    with pytest.raises(BackupError):
        restore_backup(bad_backup, live_path)

    # Live DB should be intact
    db2 = _make_db(live_path)
    assert db2.scalar("SELECT COUNT(*) FROM parts") == original_count
    db2.close()


def test_cannot_export_over_live_db(tmp_path: Path) -> None:
    """Exporting to the same path as the live DB should be blocked at the
    CLI / UI layer, but the service also raises for the restore path."""
    live_path = tmp_path / "live.db"
    db = _make_db(live_path)
    db.close()

    with pytest.raises(BackupError, match="Cannot restore from the live database"):
        restore_backup(live_path, live_path)


def test_restore_cleans_wal_sidecars(tmp_path: Path) -> None:
    """After restore, stale -wal and -shm files should be removed."""
    live_path = tmp_path / "live.db"
    db = _make_db(live_path)
    db.close()

    # Create fake sidecar files
    wal = tmp_path / "live.db-wal"
    shm = tmp_path / "live.db-shm"
    wal.write_bytes(b"fake wal")
    shm.write_bytes(b"fake shm")

    # Create a valid backup
    backup_path = tmp_path / "backup.db"
    src = _make_db(tmp_path / "src.db")
    export_backup(src.conn, backup_path)
    src.close()

    restore_backup(backup_path, live_path)

    assert not wal.exists()
    assert not shm.exists()
