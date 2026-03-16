"""Tests for SignatureParser: per-family deterministic parsing of Part names."""
from __future__ import annotations

import pytest

from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import ComponentFamily
from eurorack_inventory.services.signature_parser import SignatureParser


def _part(name: str, category: str | None = None, mpn: str | None = None,
          default_package: str | None = None) -> Part:
    return Part(
        id=1, fingerprint="test", name=name, normalized_name=name.lower(),
        category=category, mpn=mpn, default_package=default_package,
    )


@pytest.fixture()
def parser():
    return SignatureParser()


# ── Family detection ──────────────────────────────────────────────────────


class TestFamilyDetection:
    def test_resistor_category(self, parser):
        sig = parser.parse(_part("150R", category="Resistors"))
        assert sig.component_family == ComponentFamily.RESISTOR

    def test_capacitor_category(self, parser):
        sig = parser.parse(_part("100nF", category="Capacitors"))
        assert sig.component_family == ComponentFamily.CAPACITOR

    def test_ic_compound_category(self, parser):
        sig = parser.parse(_part("TL072", category="ICs — Op-Amps"))
        assert sig.component_family == ComponentFamily.IC

    def test_diode_compound_category(self, parser):
        sig = parser.parse(_part("1N4148", category="Diodes — Signal"))
        assert sig.component_family == ComponentFamily.DIODE

    def test_pot_category(self, parser):
        sig = parser.parse(_part("100k B Pot", category="Potentiometers"))
        assert sig.component_family == ComponentFamily.POT

    def test_switch_category(self, parser):
        sig = parser.parse(_part("SPDT Toggle", category="Switches"))
        assert sig.component_family == ComponentFamily.SWITCH

    def test_connector_category(self, parser):
        sig = parser.parse(_part("15-pin header", category="Connectors"))
        assert sig.component_family == ComponentFamily.CONNECTOR

    def test_unknown_fallback(self, parser):
        sig = parser.parse(_part("Mystery Part", category="Misc"))
        assert sig.component_family == ComponentFamily.UNKNOWN


# ── Resistor parsing ─────────────────────────────────────────────────────


class TestResistorParser:
    def test_150_ohm(self, parser):
        sig = parser.parse(_part("150Ω 1% 1/4 W Metal Film Resistor", category="Resistors"))
        assert sig.component_family == ComponentFamily.RESISTOR
        assert sig.value_ohms == 150.0
        assert sig.tolerance == "1%"
        assert sig.wattage == 0.25

    def test_15k(self, parser):
        sig = parser.parse(_part("15K 1% 1/4 W Metal Film Resistor", category="Resistors"))
        assert sig.component_family == ComponentFamily.RESISTOR
        assert sig.value_ohms == 15000.0

    def test_4k7(self, parser):
        sig = parser.parse(_part("4K7 Resistor", category="Resistors"))
        assert sig.component_family == ComponentFamily.RESISTOR
        assert sig.value_ohms == 4700.0

    def test_100r(self, parser):
        sig = parser.parse(_part("100R Resistor", category="Resistors"))
        assert sig.value_ohms == 100.0

    def test_1m(self, parser):
        sig = parser.parse(_part("1M Resistor", category="Resistors"))
        assert sig.value_ohms == 1_000_000.0

    def test_100_ohm_text(self, parser):
        sig = parser.parse(_part("100 ohm Resistor", category="Resistors"))
        assert sig.value_ohms == 100.0

    def test_no_explicit_mounting_is_none(self, parser):
        sig = parser.parse(_part("100K Resistor", category="Resistors"))
        assert sig.mounting is None

    def test_smd_detected(self, parser):
        sig = parser.parse(_part("100K Resistor 0805 SMD", category="Resistors"))
        assert sig.mounting == "smd"
        assert sig.package == "0805"

    def test_through_hole_detected(self, parser):
        sig = parser.parse(_part("100K Through-hole Resistor", category="Resistors"))
        assert sig.mounting == "through_hole"


# ── Capacitor parsing ────────────────────────────────────────────────────


class TestCapacitorParser:
    def test_100nf_smd(self, parser):
        sig = parser.parse(_part("100nF (0805 SMD)", category="Capacitors"))
        assert sig.component_family == ComponentFamily.CAPACITOR
        assert sig.value_pf == 100_000.0
        assert sig.package == "0805"
        assert sig.mounting == "smd"

    def test_10uf(self, parser):
        sig = parser.parse(_part("10uF capacitor", category="Capacitors"))
        assert sig.value_pf == 10_000_000.0

    def test_22pf(self, parser):
        sig = parser.parse(_part("22pF ceramic", category="Capacitors"))
        assert sig.value_pf == 22.0
        assert sig.dielectric == "ceramic"

    def test_electrolytic(self, parser):
        sig = parser.parse(_part("47uF Electrolytic 25V", category="Capacitors"))
        assert sig.polarized is True
        assert sig.dielectric == "electrolytic"
        assert sig.voltage_rating == 25.0

    def test_no_explicit_mounting_is_none(self, parser):
        sig = parser.parse(_part("100nF Capacitor", category="Capacitors"))
        assert sig.mounting is None


# ── Connector parsing ────────────────────────────────────────────────────


class TestConnectorParser:
    def test_15pin_female_header(self, parser):
        sig = parser.parse(_part("15-pin 2.54mm Single Row Female Pin Header", category="Connectors"))
        assert sig.component_family == ComponentFamily.CONNECTOR
        assert sig.connector_subtype == "female_header"
        assert sig.pin_count == 15
        assert sig.pitch_um == 2540
        assert sig.gender == "female"
        assert sig.row_count == 1

    def test_5pin_female_header(self, parser):
        sig = parser.parse(_part("5-pin 2.54mm Single Row Female Pin Header", category="Connectors"))
        assert sig.pin_count == 5
        assert sig.pitch_um == 2540

    def test_14pin_dip_socket(self, parser):
        sig = parser.parse(_part("14 pin DIP socket", category="Connectors"))
        assert sig.connector_subtype == "dip_socket"
        assert sig.pin_count == 14

    def test_8pin_dip_socket(self, parser):
        sig = parser.parse(_part("8 pin DIP socket", category="Connectors"))
        assert sig.connector_subtype == "dip_socket"
        assert sig.pin_count == 8

    def test_audio_jack_mono(self, parser):
        sig = parser.parse(_part("3.5mm Mono Jack", category="Connectors"))
        assert sig.connector_subtype == "audio_jack_mono"

    def test_audio_jack_stereo(self, parser):
        sig = parser.parse(_part("3.5mm Stereo Jack", category="Connectors"))
        assert sig.connector_subtype == "audio_jack_stereo"

    def test_box_header(self, parser):
        sig = parser.parse(_part("10-pin Shrouded Box Header", category="Connectors"))
        assert sig.connector_subtype == "box_header"
        assert sig.pin_count == 10
        assert sig.shrouded is True

    def test_power_header(self, parser):
        sig = parser.parse(_part("Eurorack Power Header 16-pin", category="Connectors"))
        assert sig.connector_subtype == "power_header"
        assert sig.pin_count == 16


# ── Pot parsing ──────────────────────────────────────────────────────────


class TestPotParser:
    def test_100k_b_linear_alpha(self, parser):
        sig = parser.parse(_part("100k B Linear Pot (16mm Alpha)", category="Potentiometers"))
        assert sig.component_family == ComponentFamily.POT
        assert sig.value_ohms == 100_000.0
        assert sig.taper == "B"
        assert sig.body_size_mm == 16
        assert sig.manufacturer_hint == "Alpha"

    def test_10k_pot(self, parser):
        sig = parser.parse(_part("10k B Linear Pot", category="Potentiometers"))
        assert sig.value_ohms == 10_000.0
        assert sig.taper == "B"

    def test_log_taper(self, parser):
        sig = parser.parse(_part("100k A Log Pot", category="Potentiometers"))
        assert sig.taper == "A"

    def test_spline_shaft(self, parser):
        sig = parser.parse(_part("10k B Linear Pot Spline Shaft 9mm", category="Potentiometers"))
        assert sig.shaft_style == "spline"
        assert sig.body_size_mm == 9


# ── Switch parsing ───────────────────────────────────────────────────────


class TestSwitchParser:
    def test_spdt_on_off_on(self, parser):
        sig = parser.parse(_part("Mini Toggle Switch SPDT On-Off-On", category="Switches"))
        assert sig.component_family == ComponentFamily.SWITCH
        assert sig.pole_throw == "SPDT"
        assert sig.action_pattern == "ON-OFF-ON"

    def test_spdt_on_on(self, parser):
        sig = parser.parse(_part("Mini Toggle Switch SPDT On-On", category="Switches"))
        assert sig.pole_throw == "SPDT"
        assert sig.action_pattern == "ON-ON"

    def test_dpdt(self, parser):
        sig = parser.parse(_part("DPDT Toggle Switch ON-ON", category="Switches"))
        assert sig.pole_throw == "DPDT"
        assert sig.action_pattern == "ON-ON"

    def test_momentary(self, parser):
        sig = parser.parse(_part("SPDT (ON)-OFF-(ON) Momentary", category="Switches"))
        assert sig.pole_throw == "SPDT"
        assert sig.action_pattern == "ON-OFF-ON"
        assert sig.momentary_positions is not None
        assert len(sig.momentary_positions) >= 1


# ── Semiconductor parsing ────────────────────────────────────────────────


class TestSemiconductorParser:
    def test_cd4070bm96(self, parser):
        sig = parser.parse(_part("CD4070BM96", category="ICs — Logic"))
        assert sig.component_family == ComponentFamily.IC
        assert sig.base_device == "CD4070BM"
        assert sig.packing_suffix == "96"

    def test_bcm847ds_comma(self, parser):
        sig = parser.parse(_part("BCM847DS,115", category="Transistors"))
        assert sig.component_family == ComponentFamily.TRANSISTOR
        assert sig.base_device == "BCM847DS"
        assert sig.packing_suffix == ",115"

    def test_pt2399(self, parser):
        sig = parser.parse(_part("PT2399", category="ICs — Audio"))
        assert sig.component_family == ComponentFamily.IC
        assert sig.base_device == "PT2399"

    def test_tl072_descriptive(self, parser):
        sig = parser.parse(_part("TL072 Dual Op-Amp", category="ICs — Op-Amps"))
        assert sig.base_device == "TL072"

    def test_mpn_field_preferred(self, parser):
        sig = parser.parse(_part("Some Op-Amp IC", category="ICs — Op-Amps", mpn="TL072CDR"))
        assert sig.base_device == "TL072CDR"

    def test_pt2399_sn(self, parser):
        sig = parser.parse(_part("PT2399-SN", category="ICs — Audio"))
        assert sig.base_device == "PT2399"
        assert sig.packing_suffix == "-SN"


# ── Real inventory name regression tests ─────────────────────────────────


class TestRealInventoryNames:
    """Tests against actual part names from the inventory."""

    @pytest.mark.parametrize("name,category,expected_family,key_field,expected_value", [
        ("150Ω 1% 1/4 W Metal Film Resistor", "Resistors", ComponentFamily.RESISTOR, "value_ohms", 150.0),
        ("15K 1% 1/4 W Metal Film Resistor", "Resistors", ComponentFamily.RESISTOR, "value_ohms", 15000.0),
        ("100nF (0805 SMD)", "Capacitors", ComponentFamily.CAPACITOR, "value_pf", 100000.0),
        ("10uF capacitor", "Capacitors", ComponentFamily.CAPACITOR, "value_pf", 10000000.0),
        ("100k B Linear Pot (16mm Alpha)", "Potentiometers", ComponentFamily.POT, "value_ohms", 100000.0),
    ])
    def test_value_parsing(self, parser, name, category, expected_family, key_field, expected_value):
        sig = parser.parse(_part(name, category=category))
        assert sig.component_family == expected_family
        assert getattr(sig, key_field) == pytest.approx(expected_value, rel=0.01)

    @pytest.mark.parametrize("name,category,expected_pin_count", [
        ("15-pin 2.54mm Single Row Female Pin Header", "Connectors", 15),
        ("5-pin 2.54mm Single Row Female Pin Header", "Connectors", 5),
        ("14 pin DIP socket", "Connectors", 14),
        ("8 pin DIP socket", "Connectors", 8),
    ])
    def test_pin_count_parsing(self, parser, name, category, expected_pin_count):
        sig = parser.parse(_part(name, category=category))
        assert sig.pin_count == expected_pin_count
