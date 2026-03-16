"""Tests for dedup conflict rules, blocking, and integration with known failure cases."""
from __future__ import annotations

import pytest

from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import ComponentFamily, PartSignature
from eurorack_inventory.services.dedup_conflicts import check_conflicts
from eurorack_inventory.services.dedup_blocking import generate_candidates
from eurorack_inventory.services.signature_parser import SignatureParser


def _part(id: int, name: str, category: str | None = None, supplier_sku: str | None = None,
          mpn: str | None = None, manufacturer: str | None = None,
          default_package: str | None = None) -> Part:
    return Part(
        id=id, fingerprint=f"test-{id}", name=name, normalized_name=name.lower(),
        category=category, supplier_sku=supplier_sku, mpn=mpn,
        manufacturer=manufacturer, default_package=default_package,
    )


@pytest.fixture()
def parser():
    return SignatureParser()


# ── Hard reject regression tests ─────────────────────────────────────────
# These are the known failure cases from the spec.


class TestKnownHardRejects:
    """Pairs that were incorrectly matched by the old fuzzy system."""

    def test_150ohm_vs_15k_not_paired(self, parser):
        """150R resistor and 15K resistor: hard reject (value_ohms differ)."""
        pa = _part(1, "150Ω 1% 1/4 W Metal Film Resistor", category="Resistors")
        pb = _part(2, "15K 1% 1/4 W Metal Film Resistor", category="Resistors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "resistor_value_differs" in hard

    def test_15pin_vs_5pin_header_not_paired(self, parser):
        """15-pin vs 5-pin female pin header: hard reject (pin_count differ)."""
        pa = _part(1, "15-pin 2.54mm Single Row Female Pin Header", category="Connectors")
        pb = _part(2, "5-pin 2.54mm Single Row Female Pin Header", category="Connectors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "connector_pin_count_differs" in hard

    def test_100k_pot_vs_10k_pot_not_paired(self, parser):
        """100k B Linear Pot vs 10k B Linear Pot: hard reject (value_ohms differ)."""
        pa = _part(1, "100k B Linear Pot (16mm Alpha)", category="Potentiometers")
        pb = _part(2, "10k B Linear Pot (16mm Alpha)", category="Potentiometers")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "pot_value_differs" in hard

    def test_14pin_vs_8pin_dip_socket_not_paired(self, parser):
        """14 pin DIP socket vs 8 pin DIP socket: hard reject (pin_count differ)."""
        pa = _part(1, "14 pin DIP socket", category="Connectors")
        pb = _part(2, "8 pin DIP socket", category="Connectors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "dip_socket_pin_count_differs" in hard

    def test_spdt_on_off_on_vs_on_on_not_paired(self, parser):
        """ON-OFF-ON switch vs ON-ON switch: hard reject (action_pattern differs)."""
        pa = _part(1, "Mini Toggle Switch SPDT On-Off-On", category="Switches")
        pb = _part(2, "Mini Toggle Switch SPDT On-On", category="Switches")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "switch_function_differs" in hard


# ── Synthetic hard-negative parametric tests ─────────────────────────────


class TestKnownDifferentPartsHardRejected:
    @pytest.mark.parametrize("name_a,name_b,category", [
        ("100R Resistor", "100K Resistor", "Resistors"),
        ("10nF Cap", "100nF Cap", "Capacitors"),
        ("8 pin DIP Socket", "16 pin DIP Socket", "Connectors"),
        ("100k B Pot", "10k B Pot", "Potentiometers"),
        ("SPDT ON-OFF-ON", "SPDT ON-ON", "Switches"),
        ("15-pin Female Header", "5-pin Female Header", "Connectors"),
    ])
    def test_known_different_parts_hard_rejected(self, parser, name_a, name_b, category):
        pa = _part(1, name_a, category=category)
        pb = _part(2, name_b, category=category)
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert len(hard) > 0, f"Expected hard reject for {name_a} vs {name_b}"

    def test_tl072_vs_lm358_different_base(self, parser):
        pa = _part(1, "TL072", category="ICs — Op-Amps")
        pb = _part(2, "LM358", category="ICs — Op-Amps")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "semiconductor_base_device_differs" in hard

    def test_mono_vs_stereo_jack(self, parser):
        pa = _part(1, "3.5mm Mono Jack", category="Connectors")
        pb = _part(2, "3.5mm Stereo Jack", category="Connectors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "connector_subtype_differs" in hard


# ── True positive tests (should be paired) ───────────────────────────────


class TestTrueDuplicatesPaired:
    @pytest.mark.parametrize("name_a,name_b,category", [
        ("100K Resistor 1/4W", "100K Resistor 1/4 Watt", "Resistors"),
        ("100nF Capacitor", "100nF Cap MLCC", "Capacitors"),
    ])
    def test_true_duplicates_no_hard_reject(self, parser, name_a, name_b, category):
        pa = _part(1, name_a, category=category)
        pb = _part(2, name_b, category=category)
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert len(hard) == 0, f"Unexpected hard reject for {name_a} vs {name_b}: {hard}"

    def test_tl072_variants_no_hard_reject(self, parser):
        pa = _part(1, "TL072 Dual Op-Amp", category="ICs — Op-Amps")
        pb = _part(2, "TL072 Op-Amp DIP-8", category="ICs — Op-Amps")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert len(hard) == 0


# ── Soft warning tests ───────────────────────────────────────────────────


class TestSoftWarnings:
    def test_disjoint_sku_warning(self, parser):
        pa = _part(1, "100K Resistor", category="Resistors", supplier_sku="A-1234")
        pb = _part(2, "100K Resistor", category="Resistors", supplier_sku="A-5678")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        _, warnings = check_conflicts(pa, pb, sig_a, sig_b)
        assert "disjoint_tayda_sku" in warnings

    def test_different_manufacturer_warning(self, parser):
        pa = _part(1, "100K Resistor", category="Resistors", manufacturer="Yageo")
        pb = _part(2, "100K Resistor", category="Resistors", manufacturer="Vishay")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        _, warnings = check_conflicts(pa, pb, sig_a, sig_b)
        assert "different_manufacturer" in warnings

    def test_packing_suffix_differs_warning(self, parser):
        pa = _part(1, "BCM847DS,115", category="Transistors")
        pb = _part(2, "BCM847DS,135", category="Transistors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        _, warnings = check_conflicts(pa, pb, sig_a, sig_b)
        assert "packing_suffix_differs" in warnings

    def test_generic_vs_specific_warning(self, parser):
        pa = _part(1, "10uF capacitor", category="Capacitors")
        pb = _part(2, "10uF capacitor (0805 SMD)", category="Capacitors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        _, warnings = check_conflicts(pa, pb, sig_a, sig_b)
        assert "generic_vs_specific" in warnings


# ── Blocking tests ───────────────────────────────────────────────────────


class TestBlocking:
    def test_same_resistor_value_generates_candidate(self, parser):
        pa = _part(1, "100K Resistor 1/4W", category="Resistors")
        pb = _part(2, "100K Resistor 1/4 Watt", category="Resistors")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) in pair_ids

    def test_different_resistor_values_not_blocked_together(self, parser):
        pa = _part(1, "100K Resistor", category="Resistors")
        pb = _part(2, "10K Resistor", category="Resistors")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) not in pair_ids

    def test_exact_sku_generates_candidate(self, parser):
        pa = _part(1, "Alpha Pot 100K", supplier_sku="A-1234")
        pb = _part(2, "100K Linear Pot", supplier_sku="A-1234")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        reasons = {r for _, _, reasons in candidates for r in reasons}
        assert "exact_sku" in reasons

    def test_suppressed_pair_filtered_out(self, parser):
        pa = _part(1, "100K Resistor 1/4W", category="Resistors")
        pb = _part(2, "100K Resistor 1/4 Watt", category="Resistors")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        suppressed = {(1, 2)}
        candidates = generate_candidates([pa, pb], sigs, suppressed)
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) not in pair_ids

    def test_same_connector_subtype_and_pin_count_blocked(self, parser):
        pa = _part(1, "14 pin DIP socket", category="Connectors")
        pb = _part(2, "14-pin DIP Socket IC", category="Connectors")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) in pair_ids

    def test_different_pin_count_not_blocked(self, parser):
        pa = _part(1, "14 pin DIP socket", category="Connectors")
        pb = _part(2, "8 pin DIP socket", category="Connectors")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        # They share the same subtype (dip_socket) but different pin_count,
        # so they should NOT be in the same blocking group
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) not in pair_ids

    def test_same_pot_value_and_taper_blocked(self, parser):
        pa = _part(1, "100k B Linear Pot (16mm Alpha)", category="Potentiometers")
        pb = _part(2, "100k B Linear Pot 16mm", category="Potentiometers")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) in pair_ids

    def test_same_switch_function_blocked(self, parser):
        pa = _part(1, "Mini Toggle Switch SPDT On-Off-On", category="Switches")
        pb = _part(2, "Toggle SPDT ON-OFF-ON Short Lever", category="Switches")
        sigs = {1: parser.parse(pa), 2: parser.parse(pb)}
        candidates = generate_candidates([pa, pb], sigs, set())
        pair_ids = {(a, b) for a, b, _ in candidates}
        assert (1, 2) in pair_ids


# ── Package technology hard reject ───────────────────────────────────────


class TestPackageTechnologyReject:
    def test_smd_vs_tht_hard_reject(self, parser):
        pa = _part(1, "10uF THT capacitor", category="Capacitors")
        pb = _part(2, "10uF capacitor (0805 SMD)", category="Capacitors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "package_technology_differs" in hard

    def test_unknown_mounting_vs_smd_no_hard_reject(self, parser):
        """If mounting is unknown on one side, don't hard reject."""
        pa = _part(1, "10uF capacitor", category="Capacitors")
        pb = _part(2, "10uF capacitor (0805 SMD)", category="Capacitors")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "package_technology_differs" not in hard


# ── Component family cross-check ─────────────────────────────────────────


class TestComponentFamilyReject:
    def test_resistor_vs_pot_hard_reject(self, parser):
        pa = _part(1, "100K", category="Resistors")
        pb = _part(2, "100K", category="Potentiometers")
        sig_a = parser.parse(pa)
        sig_b = parser.parse(pb)
        hard, _ = check_conflicts(pa, pb, sig_a, sig_b)
        assert "component_family_differs" in hard
