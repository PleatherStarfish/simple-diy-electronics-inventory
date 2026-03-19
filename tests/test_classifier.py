import pytest

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.domain.models import Part
from eurorack_inventory.services.classifier import (
    PartCompatibility,
    classify_part,
    classify_part_compat,
)


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

    def test_smt_resistor_package_only_goes_to_small(self):
        part = _make_part(name="100R", category="Resistors", default_package="SMD 0805", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_smt_resistor_0603_goes_to_small(self):
        part = _make_part(name="10K 0603", category="Resistors", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_smt_diode_goes_to_small(self):
        part = _make_part(name="1N4148 SMD", category="Diodes", qty=30)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_smt_led_package_only_goes_to_small(self):
        part = _make_part(name="Blue", category="LEDs", default_package="0805", qty=20)
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


class TestStorageClassOverride:
    def test_override_respected(self):
        """Override forces a different storage class."""
        part = _make_part(name="100R 0805", category="Resistors", qty=10)
        part = Part(
            id=part.id, fingerprint=part.fingerprint, name=part.name,
            normalized_name=part.normalized_name, category=part.category,
            qty=part.qty, storage_class_override="large_cell",
        )
        assert classify_part(part) == StorageClass.LARGE_CELL

    def test_invalid_override_falls_through(self):
        """Invalid override string falls through to normal rules."""
        part = Part(
            id=1, fingerprint="fp", name="100R 0805",
            normalized_name="100r 0805", category="Resistors",
            qty=10, storage_class_override="nonexistent",
        )
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_none_override_uses_normal_rules(self):
        """None override → normal classification."""
        part = _make_part(name="Toggle", category="Switches")
        assert part.storage_class_override is None
        assert classify_part(part) == StorageClass.LARGE_CELL


class TestFallback:
    def test_unknown_category_goes_to_small(self):
        part = _make_part(name="Mystery Part", category="Miscellaneous")
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_no_category_goes_to_small(self):
        part = _make_part(name="Something", category=None)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL


class TestCompatibilityMatrix:
    def test_small_short_cell_preferred(self):
        part = _make_part(name="100nF 0805", category="Capacitors", qty=10)
        compat = classify_part_compat(part)
        assert compat.preferred == StorageClass.SMALL_SHORT_CELL

    def test_small_short_cell_fallbacks(self):
        part = _make_part(name="100nF 0805", category="Capacitors", qty=10)
        compat = classify_part_compat(part)
        assert compat.penalty_for(StorageClass.SMALL_SHORT_CELL) == 0.0
        assert compat.penalty_for(StorageClass.LARGE_CELL) == 0.3
        assert compat.penalty_for(StorageClass.LONG_CELL) == 0.5
        assert compat.penalty_for(StorageClass.BINDER_CARD) == 0.8

    def test_large_cell_preferred(self):
        part = _make_part(name="Toggle Switch", category="Switches")
        compat = classify_part_compat(part)
        assert compat.preferred == StorageClass.LARGE_CELL

    def test_large_cell_fallbacks(self):
        part = _make_part(name="Toggle Switch", category="Switches")
        compat = classify_part_compat(part)
        assert compat.penalty_for(StorageClass.LARGE_CELL) == 0.0
        assert compat.penalty_for(StorageClass.LONG_CELL) == 0.3
        assert compat.penalty_for(StorageClass.BINDER_CARD) == 0.8
        # Large parts cannot fit in small cells
        assert compat.penalty_for(StorageClass.SMALL_SHORT_CELL) is None

    def test_long_cell_preferred(self):
        part = _make_part(name="10K Resistor", category="Resistors", qty=50)
        compat = classify_part_compat(part)
        assert compat.preferred == StorageClass.LONG_CELL

    def test_long_cell_fallbacks(self):
        part = _make_part(name="10K Resistor", category="Resistors", qty=50)
        compat = classify_part_compat(part)
        assert compat.penalty_for(StorageClass.LONG_CELL) == 0.0
        assert compat.penalty_for(StorageClass.BINDER_CARD) == 0.8
        # Long parts cannot fit in large-only or small cells
        assert compat.penalty_for(StorageClass.LARGE_CELL) is None
        assert compat.penalty_for(StorageClass.SMALL_SHORT_CELL) is None

    def test_binder_card_preferred(self):
        part = _make_part(name="TL072 SOIC-8", category="ICs")
        compat = classify_part_compat(part)
        assert compat.preferred == StorageClass.BINDER_CARD

    def test_binder_card_fallbacks(self):
        part = _make_part(name="TL072 SOIC-8", category="ICs")
        compat = classify_part_compat(part)
        assert compat.penalty_for(StorageClass.BINDER_CARD) == 0.0
        assert compat.penalty_for(StorageClass.SMALL_SHORT_CELL) == 0.6
        assert compat.penalty_for(StorageClass.LARGE_CELL) == 0.8
        assert compat.penalty_for(StorageClass.LONG_CELL) == 0.9

    def test_compatible_classes_order(self):
        part = _make_part(name="100nF 0805", category="Capacitors", qty=10)
        compat = classify_part_compat(part)
        classes = compat.compatible_classes()
        assert classes[0] == StorageClass.SMALL_SHORT_CELL  # preferred first
        assert StorageClass.LARGE_CELL in classes
        assert StorageClass.LONG_CELL in classes
        assert StorageClass.BINDER_CARD in classes  # last-resort fallback

    def test_classify_part_compat_respects_override(self):
        part = _make_part(name="Custom Part", category="Misc")
        part = Part(
            id=1, fingerprint="fp", name="Custom Part", normalized_name="custom part",
            category="Misc", qty=10, storage_class_override="large_cell",
        )
        compat = classify_part_compat(part)
        assert compat.preferred == StorageClass.LARGE_CELL


# ──────────────────────────────────────────────────────────
# Expanded IC pattern
# ──────────────────────────────────────────────────────────


class TestExpandedICClassification:
    @pytest.mark.parametrize("name,category", [
        ("MCP4921 DAC", "ICs"),
        ("ADS1115 ADC", None),
        ("ICE40 FPGA", "ICs"),
        ("NE555 Timer", None),
        ("555 Astable", None),
        ("74HC595 Shift Register", "ICs"),
        ("CD4050 Buffer", "ICs"),
        ("ULN2803 Driver", "ICs"),
        ("CD4051 Multiplexer", "ICs"),
        ("CD4051 MUX", None),
        ("Si5351 Oscillator", "ICs"),
        ("XC9572 CPLD", "ICs"),
    ])
    def test_expanded_ic_keywords_go_to_binder(self, name, category):
        part = _make_part(name=name, category=category)
        assert classify_part(part) == StorageClass.BINDER_CARD


# ──────────────────────────────────────────────────────────
# Transistor classification
# ──────────────────────────────────────────────────────────


class TestTransistorClassification:
    def test_smt_transistor_goes_to_binder(self):
        part = _make_part(name="2N7002", category="Transistors", default_package="SOT-23")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_smt_mosfet_goes_to_binder(self):
        part = _make_part(name="BSS138 MOSFET", category=None, default_package="SOT-23")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_through_hole_transistor_small_qty_goes_to_small(self):
        part = _make_part(name="2N3904", category="Transistors", default_package="TO-92", qty=3)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_through_hole_transistor_large_qty_goes_to_binder(self):
        part = _make_part(name="2N3904", category="Transistors", default_package="TO-92", qty=10)
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_to220_transistor_small_qty(self):
        part = _make_part(name="IRF540", category="Transistors", default_package="TO-220", qty=2)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_generic_transistor_goes_to_binder(self):
        part = _make_part(name="BC547", category="Transistors")
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_jfet_goes_to_binder(self):
        part = _make_part(name="J201 JFET", category=None)
        assert classify_part(part) == StorageClass.BINDER_CARD

    def test_bs170_goes_to_binder(self):
        part = _make_part(name="BS170", category="Transistors")
        assert classify_part(part) == StorageClass.BINDER_CARD


# ──────────────────────────────────────────────────────────
# Expanded large-part classification
# ──────────────────────────────────────────────────────────


class TestExpandedLargePartClassification:
    @pytest.mark.parametrize("name,category", [
        ("M3 Standoff", "Hardware"),
        ("Nylon Spacer", "Hardware"),
        ("Davies 1900 Knob", "Knobs"),
        ("3A Fuse", "Fuses"),
        ("Fuse Holder", "Fuses"),
        ("Screw Terminal", "Connectors"),
        ("PCB Mounting Clip", "Hardware"),
        ("Bracket", "Hardware"),
        ("TO-220 Heatsink", "Hardware"),
        ("Heat Sink", "Hardware"),
        ("128x64 OLED Display", "Displays"),
        ("16x2 LCD", "Displays"),
    ])
    def test_expanded_large_parts_go_to_large_cell(self, name, category):
        part = _make_part(name=name, category=category)
        assert classify_part(part) == StorageClass.LARGE_CELL


# ──────────────────────────────────────────────────────────
# Through-hole capacitor long-part detection
# ──────────────────────────────────────────────────────────


class TestThroughHoleCapacitorClassification:
    def test_electrolytic_cap_goes_to_long(self):
        part = _make_part(name="10uF Electrolytic", category="Capacitors", qty=20)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_film_cap_goes_to_long(self):
        part = _make_part(name="100nF Film Cap", category="Capacitors", qty=15)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_radial_cap_goes_to_long(self):
        part = _make_part(name="47uF", category="Capacitors", default_package="Radial", qty=10)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_axial_cap_goes_to_long(self):
        part = _make_part(name="100nF", category="Capacitors", default_package="Axial", qty=10)
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_small_qty_electrolytic_goes_to_small(self):
        part = _make_part(name="10uF Electrolytic", category="Capacitors", qty=3)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_generic_capacitor_stays_small(self):
        """A capacitor with no through-hole indicator stays in Rule 6 (SMALL_SHORT_CELL)."""
        part = _make_part(name="100nF", category="Capacitors", qty=50)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL


# ──────────────────────────────────────────────────────────
# SMT size regex false positive prevention
# ──────────────────────────────────────────────────────────


class TestSMTSizePatternRobustness:
    def test_standalone_0805_detected(self):
        part = _make_part(name="100R 0805", category="Resistors", qty=10)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_0805_in_package_detected(self):
        part = _make_part(name="100R", category="Resistors", default_package="0805", qty=10)
        assert classify_part(part) == StorageClass.SMALL_SHORT_CELL

    def test_part_number_with_embedded_0805_not_falsely_smt(self):
        """R0805-series should NOT be detected as SMT — the 0805 is part of the part number."""
        part = _make_part(name="R0805-series", category="Resistors", qty=10)
        # Without false SMT detection, this through-hole resistor goes to LONG_CELL
        assert classify_part(part) == StorageClass.LONG_CELL

    def test_model_number_with_embedded_1206_not_falsely_smt(self):
        part = _make_part(name="Model1206X", category="Resistors", qty=10)
        assert classify_part(part) == StorageClass.LONG_CELL
