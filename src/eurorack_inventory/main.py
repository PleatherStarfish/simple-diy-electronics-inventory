from __future__ import annotations

import argparse
import logging
from pathlib import Path

from eurorack_inventory.app import build_app_context
from eurorack_inventory.config import AppPaths, package_dir

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple DIY Synth Inventory desktop app")
    parser.add_argument("--db", default=None, help="Path to SQLite database file (default: ~/Library/Application Support/Simple DIY Synth Inventory/)")
    parser.add_argument("--import", dest="import_path", help="Optional spreadsheet path to import")
    parser.add_argument(
        "--import-mode",
        default="replace_snapshot",
        choices=["replace_snapshot", "merge_quantities"],
        help="Import behavior when --import is provided",
    )
    parser.add_argument(
        "--headless-import",
        action="store_true",
        help="Run the import and exit without launching the UI",
    )
    parser.add_argument(
        "--bootstrap-demo-storage",
        action="store_true",
        help="Create example containers for a quick first run",
    )
    parser.add_argument(
        "--export-backup",
        metavar="PATH",
        help="Export a full database backup to PATH and exit",
    )
    parser.add_argument(
        "--restore-backup",
        metavar="PATH",
        help="Restore the database from a backup file at PATH and exit",
    )
    parser.add_argument(
        "--export-csv",
        metavar="PATH",
        help="Export all data as CSV files in a zip archive and exit",
    )
    parser.add_argument(
        "--import-csv",
        metavar="PATH",
        help="Import data from a CSV zip archive (replaces all current data) and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    else:
        db_path = AppPaths.default().db_path

    # ── Headless restore (before building full app context) ──
    if args.restore_backup:
        from eurorack_inventory.services.backup import BackupError, restore_backup

        backup_file = Path(args.restore_backup).expanduser().resolve()
        try:
            safety = restore_backup(backup_file, db_path)
            print(f"Restored backup from {backup_file}")
            print(f"Safety copy of previous database: {safety}")
            return 0
        except BackupError as exc:
            print(f"Restore failed: {exc}")
            return 1

    context = build_app_context(db_path)

    try:
        # ── Headless export ──
        if args.export_backup:
            from eurorack_inventory.services.backup import BackupError, export_backup

            dest = Path(args.export_backup).expanduser().resolve()
            if dest == db_path.resolve():
                print("Export failed: target path is the same as the live database.")
                return 1
            try:
                result = export_backup(context.db.conn, dest)
                print(f"Backup exported to {result}")
                return 0
            except BackupError as exc:
                print(f"Export failed: {exc}")
                return 1

        # ── Headless CSV export ──
        if args.export_csv:
            from eurorack_inventory.services.csv_backup import CSVBackupError, export_csv

            dest = Path(args.export_csv).expanduser().resolve()
            try:
                result = export_csv(context.db.conn, dest)
                print(f"CSV backup exported to {result}")
                return 0
            except CSVBackupError as exc:
                print(f"CSV export failed: {exc}")
                return 1

        # ── Headless CSV import ──
        if args.import_csv:
            from eurorack_inventory.services.csv_backup import CSVBackupError, import_csv

            archive = Path(args.import_csv).expanduser().resolve()
            try:
                counts = import_csv(archive, context.db.conn)
                total = sum(counts.values())
                print(f"CSV import complete: {total} rows across {len(counts)} tables")
                for table, count in counts.items():
                    print(f"  {table}: {count}")
                return 0
            except CSVBackupError as exc:
                print(f"CSV import failed: {exc}")
                return 1

        if args.bootstrap_demo_storage:
            context.storage_service.bootstrap_demo_storage()

        if args.import_path:
            report = context.import_service.import_file(args.import_path, mode=args.import_mode)
            context.search_service.rebuild()
            logger.info(report.summary())

        if args.headless_import:
            return 0

        try:
            from PySide6.QtWidgets import QApplication
        except ModuleNotFoundError as exc:
            parser.error(
                "PySide6 is not installed. Install GUI dependencies with `pip install -r requirements.txt`."
            )
            raise exc

        from PySide6.QtGui import QIcon
        from eurorack_inventory.ui.main_window import MainWindow
        from eurorack_inventory.ui.styles import LIGHT_THEME_QSS

        app = QApplication([])
        app.setStyle("Fusion")
        app.setStyleSheet(LIGHT_THEME_QSS)

        icon_path = package_dir() / "resources" / "AppIcon.png"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))

        window = MainWindow(context, db_path=db_path)
        window.show()
        return app.exec()
    finally:
        context.db.close()
