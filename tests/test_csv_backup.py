"""Tests for the CSV export / import service."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.csv_backup import (
    CSVBackupError,
    export_csv,
    import_csv,
    validate_csv_archive,
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


def _seed_data(db: Database) -> dict:
    """Populate representative data across all tables. Returns expected values."""
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    project_repo = ProjectRepository(db)
    audit_repo = AuditRepository(db)
    settings_repo = SettingsRepository(db)
    inventory = InventoryService(part_repo, storage_repo, audit_repo)
    storage = StorageService(storage_repo, audit_repo)
    projects = ProjectService(project_repo, part_repo, audit_repo)

    slot = storage.ensure_default_unassigned_slot()

    container = storage.create_container(
        name="Box A", container_type="grid_box",
        metadata={"rows": 4, "cols": 6},
    )
    grid_slot = storage.create_grid_slot(
        container_id=container.id, label="A1",
    )

    part = inventory.upsert_part(
        name="10k resistor",
        category="Resistors",
        qty=100,
        slot_id=grid_slot.id,
        supplier_sku="T-100",
        package="Through-hole",
        notes="1/4W",
    )
    part_repo.add_alias(part.id, "10k ohm", "10k ohm")

    settings_repo.set_raw("csv_test", "hello")

    project = projects.upsert_project(name="Test Module", maker="NLC")
    projects.add_bom_line(
        project_id=project.id, part_id=part.id, qty_required=2,
    )
    build = projects.create_build(project_id=project.id, nickname="Build 1")
    projects.add_build_update(
        build_id=build.id, status="in_progress", note="Started",
    )

    # Assignment run
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

    return {
        "part_name": part.name,
        "part_qty": part.qty,
        "alias": "10k ohm",
        "container_name": container.name,
        "setting_key": "csv_test",
        "setting_value": "hello",
        "project_name": "Test Module",
        "build_nickname": "Build 1",
    }


# ── Round-trip ────────────────────────────────────────────────────────


def test_csv_export_import_round_trip(tmp_path: Path) -> None:
    """Export CSV, clear DB, import, and verify all data survives."""
    db = _make_db(tmp_path / "live.db")
    expected = _seed_data(db)

    # Export
    archive = tmp_path / "backup.zip"
    export_csv(db.conn, archive)
    assert archive.exists()

    # Verify the archive contains expected files
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "parts.csv" in names
        assert "modules.csv" in names

    # Import into a fresh DB
    db2 = _make_db(tmp_path / "target.db")
    counts = import_csv(archive, db2.conn)

    assert counts["parts"] >= 1
    assert counts["part_aliases"] >= 1
    assert counts["storage_containers"] >= 1
    assert counts["storage_slots"] >= 1
    assert counts["modules"] >= 1
    assert counts["bom_lines"] >= 1
    assert counts["builds"] >= 1
    assert counts["build_updates"] >= 1
    assert counts["settings"] >= 1
    assert counts["audit_events"] >= 1
    assert counts["assignment_runs"] >= 1

    # Verify data integrity
    part = db2.query_one("SELECT * FROM parts WHERE name = ?", (expected["part_name"],))
    assert part is not None
    assert int(part["qty"]) == expected["part_qty"]

    alias = db2.query_one("SELECT * FROM part_aliases WHERE alias = ?", (expected["alias"],))
    assert alias is not None

    container = db2.query_one(
        "SELECT * FROM storage_containers WHERE name = ?", (expected["container_name"],)
    )
    assert container is not None

    setting = db2.query_one("SELECT value FROM settings WHERE key = ?", (expected["setting_key"],))
    assert setting is not None
    assert setting["value"] == expected["setting_value"]

    project = db2.query_one("SELECT * FROM modules WHERE name = ?", (expected["project_name"],))
    assert project is not None

    build = db2.query_one("SELECT * FROM builds WHERE nickname = ?", (expected["build_nickname"],))
    assert build is not None

    db.close()
    db2.close()


def test_csv_export_replaces_existing_data(tmp_path: Path) -> None:
    """Importing into a DB with existing data should replace it."""
    db = _make_db(tmp_path / "source.db")
    _seed_data(db)

    archive = tmp_path / "backup.zip"
    export_csv(db.conn, archive)
    db.close()

    # Create a target DB with different data
    db2 = _make_db(tmp_path / "target.db")
    part_repo = PartRepository(db2)
    storage_repo = StorageRepository(db2)
    audit_repo = AuditRepository(db2)
    inventory = InventoryService(part_repo, storage_repo, audit_repo)
    storage = StorageService(storage_repo, audit_repo)
    storage.ensure_default_unassigned_slot()
    inventory.upsert_part(name="DIFFERENT PART", category="Other", qty=999)

    assert db2.scalar("SELECT COUNT(*) FROM parts WHERE name = 'DIFFERENT PART'") == 1

    import_csv(archive, db2.conn)

    # Old data should be gone, new data from archive should be present
    assert db2.scalar("SELECT COUNT(*) FROM parts WHERE name = 'DIFFERENT PART'") == 0
    assert db2.scalar("SELECT COUNT(*) FROM parts WHERE name = '10k resistor'") == 1

    db2.close()


# ── Validation ────────────────────────────────────────────────────────


def test_validate_accepts_good_archive(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "test.db")
    archive = tmp_path / "good.zip"
    export_csv(db.conn, archive)
    db.close()

    manifest = validate_csv_archive(archive)
    assert manifest["format"] == "synth_inventory_csv"
    assert manifest["schema_version"] > 0


def test_validate_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CSVBackupError, match="does not exist"):
        validate_csv_archive(tmp_path / "nope.zip")


def test_validate_rejects_non_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_text("not a zip file")
    with pytest.raises(CSVBackupError, match="(?i)not a valid zip"):
        validate_csv_archive(bad)


def test_validate_rejects_missing_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "no_manifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("parts.csv", "id\n1\n")
    with pytest.raises(CSVBackupError, match="missing manifest"):
        validate_csv_archive(archive)


def test_validate_rejects_missing_csv(tmp_path: Path) -> None:
    archive = tmp_path / "incomplete.zip"
    manifest = {"format": "synth_inventory_csv", "schema_version": 5}
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("parts.csv", "id\n")
    with pytest.raises(CSVBackupError, match="missing required file"):
        validate_csv_archive(archive)


# ── Failure safety ────────────────────────────────────────────────────


def test_invalid_archive_does_not_corrupt_db(tmp_path: Path) -> None:
    """If import fails, the DB should be rolled back to its prior state."""
    db = _make_db(tmp_path / "live.db")
    _seed_data(db)
    original_count = db.scalar("SELECT COUNT(*) FROM parts")

    bad_archive = tmp_path / "bad.zip"
    bad_archive.write_text("not a zip")

    with pytest.raises(CSVBackupError):
        import_csv(bad_archive, db.conn)

    # DB should be intact
    assert db.scalar("SELECT COUNT(*) FROM parts") == original_count
    db.close()


def test_csv_with_fk_violation_rolls_back(tmp_path: Path) -> None:
    """A CSV archive with broken FK references should fail and roll back."""
    db = _make_db(tmp_path / "live.db")
    _seed_data(db)
    original_parts = db.scalar("SELECT COUNT(*) FROM parts")

    # Export, then tamper with the archive
    archive = tmp_path / "backup.zip"
    export_csv(db.conn, archive)

    # Create a new archive with a bom_line pointing to a nonexistent module
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "r") as src, zipfile.ZipFile(tampered, "w") as dst:
        for name in src.namelist():
            if name == "bom_lines.csv":
                # Write a row with invalid module_id
                dst.writestr(
                    name,
                    "id,module_id,part_id,qty_required,reference_note,is_optional\n"
                    "999,99999,99999,1,,0\n",
                )
            else:
                dst.writestr(name, src.read(name))

    with pytest.raises(CSVBackupError, match="Foreign key"):
        import_csv(tampered, db.conn)

    # DB should be intact after rollback
    assert db.scalar("SELECT COUNT(*) FROM parts") == original_parts
    db.close()


# ── Archive content inspection ────────────────────────────────────────


def test_exported_csv_is_readable(tmp_path: Path) -> None:
    """The exported CSV files should be parseable standard CSV."""
    db = _make_db(tmp_path / "test.db")
    _seed_data(db)

    archive = tmp_path / "export.zip"
    export_csv(db.conn, archive)
    db.close()

    with zipfile.ZipFile(archive) as zf:
        raw = zf.read("parts.csv").decode("utf-8")
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        assert len(rows) >= 1
        assert "name" in rows[0]
        assert "qty" in rows[0]
