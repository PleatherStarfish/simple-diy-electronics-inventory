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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    else:
        db_path = AppPaths.default().db_path
    context = build_app_context(db_path)

    try:
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
