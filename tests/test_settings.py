from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part
from eurorack_inventory.services.classifier import classify_part
from eurorack_inventory.services.settings import ClassifierSettings, SettingsRepository

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def settings_repo(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    yield SettingsRepository(db)
    db.close()


def _make_part(
    name: str = "Test Part",
    category: str | None = None,
    qty: int = 10,
) -> Part:
    return Part(
        id=1, fingerprint="fp", name=name,
        normalized_name=name.lower(), category=category, qty=qty,
    )


class TestSettingsRepository:
    def test_default_settings_when_empty(self, settings_repo):
        s = settings_repo.get_classifier_settings()
        assert s.small_component_qty_limit == 100
        assert s.dip_ic_qty_limit == 6
        assert s.through_hole_small_qty_limit == 6
        assert len(s.category_rules) == 4

    def test_save_and_load_round_trip(self, settings_repo):
        s = ClassifierSettings(
            small_component_qty_limit=50,
            dip_ic_qty_limit=10,
            through_hole_small_qty_limit=3,
        )
        settings_repo.save_classifier_settings(s)
        loaded = settings_repo.get_classifier_settings()
        assert loaded.small_component_qty_limit == 50
        assert loaded.dip_ic_qty_limit == 10
        assert loaded.through_hole_small_qty_limit == 3

    def test_overwrite_existing(self, settings_repo):
        settings_repo.save_classifier_settings(ClassifierSettings(small_component_qty_limit=50))
        settings_repo.save_classifier_settings(ClassifierSettings(small_component_qty_limit=200))
        loaded = settings_repo.get_classifier_settings()
        assert loaded.small_component_qty_limit == 200


class TestClassifierWithSettings:
    def test_custom_small_component_limit(self):
        """Lower the limit so 50 SMT resistors go to large cell."""
        settings = ClassifierSettings(small_component_qty_limit=40)
        part = _make_part(name="100R 0805", category="Resistors", qty=50)
        assert classify_part(part, settings) == StorageClass.LARGE_CELL

    def test_default_small_component_limit_keeps_small(self):
        """With default limit (100), 50 SMT resistors stay in small cell."""
        part = _make_part(name="100R 0805", category="Resistors", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_custom_dip_ic_limit(self):
        """Raise the DIP IC limit so 8 DIP ICs still go to small cell."""
        settings = ClassifierSettings(dip_ic_qty_limit=10)
        part = _make_part(name="TL072 DIP-8", category="ICs", qty=8)
        assert classify_part(part, settings) == StorageClass.SMALL_SHORT_CELL

    def test_default_dip_ic_limit_sends_to_binder(self):
        """With default limit (6), 8 DIP ICs go to binder."""
        part = _make_part(name="TL072 DIP-8", category="ICs", qty=8)
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_custom_through_hole_small_limit(self):
        """Raise TH small limit so 8 through-hole resistors go to small cell."""
        settings = ClassifierSettings(through_hole_small_qty_limit=10)
        part = _make_part(name="10K 1/4W", category="Resistors", qty=8)
        assert classify_part(part, settings) == StorageClass.SMALL_SHORT_CELL

    def test_default_through_hole_limit_sends_to_long(self):
        """With default limit (6), 8 through-hole resistors go to long cell."""
        part = _make_part(name="10K 1/4W", category="Resistors", qty=8)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_none_settings_uses_defaults(self):
        """Passing None for settings uses built-in defaults."""
        part = _make_part(name="100R 0805", category="Resistors", qty=99)
        assert classify_part(part, None) == StorageClass.SMALL_SHORT_CELL


class TestClassifierSettingsSerialization:
    def test_json_round_trip(self):
        original = ClassifierSettings(
            small_component_qty_limit=42,
            dip_ic_qty_limit=3,
            through_hole_small_qty_limit=8,
        )
        raw = original.to_json()
        restored = ClassifierSettings.from_json(raw)
        assert restored.small_component_qty_limit == 42
        assert restored.dip_ic_qty_limit == 3
        assert restored.through_hole_small_qty_limit == 8
        assert len(restored.category_rules) == len(original.category_rules)
