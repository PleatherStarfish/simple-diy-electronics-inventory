from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.enums import StorageClass


# --- Default category → StorageClass mappings ---

_DEFAULT_CATEGORY_RULES: list[dict] = [
    # Each rule: {"pattern": <regex>, "target": <StorageClass value>, "label": <human name>}
    {"pattern": r"\bics?\b|integrated circuit|op[\s\-]?amp|opamp|comparator|regulator|microcontroller|\bmcu\b",
     "target": StorageClass.BINDER_CARD.value, "label": "ICs / Semiconductors"},
    {"pattern": r"switch|potentiometer|\bpot\b|jack|socket|connector|encoder|relay|transformer|header",
     "target": StorageClass.LARGE_CELL.value, "label": "Mechanical (switches, pots, jacks…)"},
    {"pattern": r"resistor|diode|\bleds?\b",
     "target": StorageClass.LONG_CELL.value, "label": "Through-hole long parts (resistors, diodes, LEDs)"},
    {"pattern": r"resistor|capacitor|\bcap\b|diode|trimmer|\bleds?\b",
     "target": StorageClass.SMALL_SHORT_CELL.value, "label": "Small passives (SMT resistors, caps, trimmers…)"},
]


@dataclass(slots=True)
class ClassifierSettings:
    """User-tuneable knobs for the part classifier."""

    # Quantity thresholds
    small_component_qty_limit: int = 100
    dip_ic_qty_limit: int = 6
    through_hole_small_qty_limit: int = 6

    # Category → StorageClass rules (order matters — first match wins)
    category_rules: list[dict] = field(default_factory=lambda: list(_DEFAULT_CATEGORY_RULES))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> ClassifierSettings:
        data = json.loads(raw)
        return cls(**data)


_SETTINGS_KEY = "classifier"


class SettingsRepository:
    """Simple key-value settings stored in the settings table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_raw(self, key: str) -> str | None:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_raw(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.conn.commit()

    def get_classifier_settings(self) -> ClassifierSettings:
        raw = self.get_raw(_SETTINGS_KEY)
        if raw is None:
            return ClassifierSettings()
        return ClassifierSettings.from_json(raw)

    def save_classifier_settings(self, settings: ClassifierSettings) -> None:
        self.set_raw(_SETTINGS_KEY, settings.to_json())
