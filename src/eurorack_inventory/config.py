from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


def package_dir() -> Path:
    """Package root — works both normally and when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "eurorack_inventory"
    return Path(__file__).resolve().parent


@dataclass(slots=True)
class AppPaths:
    """Filesystem paths used by the app."""

    db_path: Path
    log_dir: Path

    @classmethod
    def from_db_path(cls, db_path: Path) -> "AppPaths":
        db_path = db_path.expanduser().resolve()
        log_dir = db_path.parent / "logs"
        return cls(db_path=db_path, log_dir=log_dir)

    @classmethod
    def default(cls) -> "AppPaths":
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "Simple DIY Synth Inventory"
        else:
            base = Path.home() / ".local" / "share" / "simple-diy-synth-inventory"
        base.mkdir(parents=True, exist_ok=True)
        return cls.from_db_path(base / "eurorack_inventory.db")
