import pytest

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part
from eurorack_inventory.services.classifier import classify_part


def _make_part(
    name: str = "Test Part",
    category: str | None = None,
    default_package: str | None = None,
    qty: int = 10,
) -> Part:
    return Part(
        id=1,
        fingerprint="fp",
        name=name,
        normalized_name=name.lower(),
        category=category,
        default_package=default_package,
        qty=qty,
    )


class TestICClassification:
    def test_soic_ic_goes_to_binder(self):
        part = _make_part(name="TL072 SOIC-8", category="ICs")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_smd_ic_goes_to_binder(self):
        part = _make_part(name="LM358 SMD", category="ICs")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_qfp_ic_goes_to_binder(self):
        part = _make_part(name="STM32 QFP-48", category="ICs")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_dip_ic_small_qty_goes_to_small_cell(self):
        part = _make_part(name="TL072 DIP-8", category="ICs", qty=3)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_dip_ic_large_qty_goes_to_binder(self):
        part = _make_part(name="TL072 DIP-8", category="ICs", qty=6)
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_generic_ic_defaults_to_binder(self):
        part = _make_part(name="NE555", category="ICs")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_opamp_category_goes_to_binder(self):
        part = _make_part(name="TL074", category="Op Amp")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_regulator_goes_to_binder(self):
        part = _make_part(name="LM7805", category="Regulator")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_comparator_goes_to_binder(self):
        part = _make_part(name="LM339", category="Comparator")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_ic_in_name_not_category(self):
        part = _make_part(name="IC TL072 SOIC", category=None)
        assert classify_part(part) == StorageClass.BINDER_CARD


class TestLargePartClassification:
    def test_switch_goes_to_large_cell(self):
        part = _make_part(name="SPDT Toggle", category="Switches")
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_potentiometer_goes_to_large_cell(self):
        part = _make_part(name="10K Linear", category="Potentiometers")
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_pot_abbreviation(self):
        part = _make_part(name="B100K Pot", category=None)
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_jack_goes_to_large_cell(self):
        part = _make_part(name="3.5mm Mono", category="Jacks")
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_connector_goes_to_large_cell(self):
        part = _make_part(name="2x5 Shrouded", category="Connectors")
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_encoder_goes_to_large_cell(self):
        part = _make_part(name="Rotary Encoder", category="Encoder")
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_header_goes_to_large_cell(self):
        part = _make_part(name="1x8 Pin Header", category="Headers")
        assert classify_part(part) == StorageClass.LARGE_CELL


class TestLongPartClassification:
    def test_through_hole_resistor_goes_to_long(self):
        part = _make_part(name="10K 1/4W", category="Resistors", qty=50)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_through_hole_resistor_cut_tape_goes_to_long(self):
        part = _make_part(name="10K 1/4W", category="Resistors", default_package="cut_tape", qty=20)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_through_hole_resistor_loose_goes_to_long(self):
        part = _make_part(name="100R 1/4W", category="Resistors", default_package="loose", qty=10)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_through_hole_diode_goes_to_long(self):
        part = _make_part(name="1N4148", category="Diodes", qty=30)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_through_hole_led_goes_to_long(self):
        part = _make_part(name="Red 3mm LED", category="LEDs", qty=20)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_through_hole_led_5mm_goes_to_long(self):
        part = _make_part(name="Green 5mm", category="LEDs", qty=15)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_very_small_qty_through_hole_goes_to_small(self):
        """A handful of through-hole resistors can fit in a small cell."""
        part = _make_part(name="10K 1/4W", category="Resistors", qty=3)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_qty_5_through_hole_goes_to_small(self):
        part = _make_part(name="1N4148", category="Diodes", qty=5)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_qty_6_through_hole_goes_to_long(self):
        part = _make_part(name="1N4148", category="Diodes", qty=6)
        assert classify_part(part) == StorageClass.LONG_CELL


class TestSmallPassiveClassification:
    def test_smt_resistor_goes_to_small(self):
        part = _make_part(name="100R 0805", category="Resistors", default_package="loose", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_smt_resistor_0603_goes_to_small(self):
        part = _make_part(name="10K 0603", category="Resistors", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_smt_diode_goes_to_small(self):
        part = _make_part(name="1N4148 SMD", category="Diodes", qty=30)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_capacitor_goes_to_small(self):
        part = _make_part(name="100nF", category="Capacitors", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_trimmer_goes_to_small(self):
        part = _make_part(name="10K Trimmer", category="Trimmers", qty=5)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_large_qty_smt_goes_to_large(self):
        """100+ SMT passives need a larger cell."""
        part = _make_part(name="100R 0805", category="Resistors", qty=100)
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_99_smt_stays_small(self):
        part = _make_part(name="100R 0805", category="Resistors", qty=99)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_large_qty_capacitor_goes_to_large(self):
        part = _make_part(name="100nF", category="Capacitors", qty=200)
        assert classify_part(part) == StorageClass.LARGE_CELL


class TestFallback:
    def test_unknown_category_goes_to_small(self):
        part = _make_part(name="Mystery Part", category="Miscellaneous")
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_no_category_goes_to_small(self):
        part = _make_part(name="Something", category=None)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL
