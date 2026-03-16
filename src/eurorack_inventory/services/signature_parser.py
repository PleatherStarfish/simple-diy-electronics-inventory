"""Per-family deterministic parsers producing PartSignature from Part metadata."""
from __future__ import annotations

import re

from eurorack_inventory.domain.models import Part
from eurorack_inventory.domain.part_signature import ComponentFamily, PartSignature

# ── Category → Family mapping ────────────────────────────────────────────

_CATEGORY_TO_FAMILY: dict[str, ComponentFamily] = {
    "resistor": ComponentFamily.RESISTOR,
    "resistors": ComponentFamily.RESISTOR,
    "capacitor": ComponentFamily.CAPACITOR,
    "capacitors": ComponentFamily.CAPACITOR,
    "connector": ComponentFamily.CONNECTOR,
    "connectors": ComponentFamily.CONNECTOR,
    "potentiometer": ComponentFamily.POT,
    "potentiometers": ComponentFamily.POT,
    "switch": ComponentFamily.SWITCH,
    "switches": ComponentFamily.SWITCH,
    "diode": ComponentFamily.DIODE,
    "diodes": ComponentFamily.DIODE,
    "led": ComponentFamily.LED,
    "leds": ComponentFamily.LED,
    "transistor": ComponentFamily.TRANSISTOR,
    "transistors": ComponentFamily.TRANSISTOR,
    "regulator": ComponentFamily.REGULATOR,
    "regulators": ComponentFamily.REGULATOR,
    "sensor": ComponentFamily.SENSOR,
    "sensors": ComponentFamily.SENSOR,
}

# Prefix-based matching for compound categories like "ICs — Op-Amps"
_CATEGORY_PREFIX_FAMILIES: list[tuple[str, ComponentFamily]] = [
    ("ic", ComponentFamily.IC),
    ("diode", ComponentFamily.DIODE),
    ("transistor", ComponentFamily.TRANSISTOR),
    ("led", ComponentFamily.LED),
    ("regulator", ComponentFamily.REGULATOR),
    ("sensor", ComponentFamily.SENSOR),
    ("connector", ComponentFamily.CONNECTOR),
    ("resistor", ComponentFamily.RESISTOR),
    ("capacitor", ComponentFamily.CAPACITOR),
    ("potentiometer", ComponentFamily.POT),
    ("switch", ComponentFamily.SWITCH),
]

# ── Resistor value multipliers ────────────────────────────────────────────

_RESISTANCE_MULTIPLIER = {
    "r": 1.0, "R": 1.0, "Ω": 1.0, "ohm": 1.0,
    "k": 1e3, "K": 1e3,
    "m": 1e6, "M": 1e6,
}

# ── Capacitor value multipliers (to picofarads) ──────────────────────────

_CAP_TO_PF = {
    "p": 1.0, "pf": 1.0,
    "n": 1e3, "nf": 1e3,
    "u": 1e6, "uf": 1e6,
    "µ": 1e6, "μ": 1e6, "µf": 1e6, "μf": 1e6,
}

# ── SMD package codes ────────────────────────────────────────────────────

_SMD_PACKAGES = {"0201", "0402", "0603", "0805", "1206", "1210", "2010", "2512"}


class SignatureParser:
    """Parse a Part into a PartSignature using deterministic per-family parsers."""

    def parse(self, part: Part) -> PartSignature:
        family = self._detect_family(part)

        if family == ComponentFamily.RESISTOR:
            return self._parse_resistor(part, family)
        if family == ComponentFamily.CAPACITOR:
            return self._parse_capacitor(part, family)
        if family == ComponentFamily.CONNECTOR:
            return self._parse_connector(part, family)
        if family == ComponentFamily.POT:
            return self._parse_pot(part, family)
        if family == ComponentFamily.SWITCH:
            return self._parse_switch(part, family)
        if family in (ComponentFamily.IC, ComponentFamily.TRANSISTOR, ComponentFamily.DIODE):
            return self._parse_semiconductor(part, family)
        if family == ComponentFamily.LED:
            return self._parse_led(part, family)
        if family == ComponentFamily.REGULATOR:
            return self._parse_regulator(part, family)

        return PartSignature(component_family=family)

    # ── Family detection ──────────────────────────────────────────────────

    def _detect_family(self, part: Part) -> ComponentFamily:
        if part.category:
            cat_lower = part.category.strip().lower()
            # Direct lookup
            if cat_lower in _CATEGORY_TO_FAMILY:
                return _CATEGORY_TO_FAMILY[cat_lower]
            # Strip trailing content after " — " or " - " for compound categories
            base = re.split(r"\s*[—–-]\s*", cat_lower)[0].strip()
            if base in _CATEGORY_TO_FAMILY:
                return _CATEGORY_TO_FAMILY[base]
            # Prefix matching
            for prefix, family in _CATEGORY_PREFIX_FAMILIES:
                if cat_lower.startswith(prefix):
                    return family

        # Fallback: name-based heuristics
        return self._detect_family_from_name(part.name)

    def _detect_family_from_name(self, name: str) -> ComponentFamily:
        lower = name.lower()

        # Order matters: check specific patterns before generic keywords
        if re.search(r"\b(trimpot|trimmer)\b", lower):
            return ComponentFamily.POT
        if re.search(r"\bpot\b", lower):
            return ComponentFamily.POT
        if re.search(r"\b(switch|toggle)\b", lower):
            return ComponentFamily.SWITCH
        if re.search(r"\b(resistor)\b", lower) or re.match(r"^\d+[rRΩ]\b", name):
            return ComponentFamily.RESISTOR
        if re.search(r"\b(capacitor|cap)\b", lower) or re.match(r"^\d+[pnuμµ][fF]?\b", name):
            return ComponentFamily.CAPACITOR
        if re.search(r"\b(header|socket|jack|connector|pin\s*strip)\b", lower):
            return ComponentFamily.CONNECTOR
        if re.search(r"\bled\b", lower):
            return ComponentFamily.LED
        if re.search(r"\b(diode|schottky|zener|1n4148|1n400|bat54)\b", lower):
            return ComponentFamily.DIODE
        if re.search(r"\b(transistor|mosfet|jfet|bjt)\b", lower):
            return ComponentFamily.TRANSISTOR
        if re.match(r"^(BC[58]\d{2}|2N\d{4}|MMBF|BCM847|J\d{3})", name, re.I):
            return ComponentFamily.TRANSISTOR
        if re.match(r"^(TL\d|LM\d|NE\d|CD4|74[HL]|PT2399|SSI|LTC|SA\d)", name, re.I):
            return ComponentFamily.IC
        if re.search(r"\b(78[lL]?05|79[lL]?05|7805|regulator|ldo)\b", lower):
            return ComponentFamily.REGULATOR
        if re.search(r"\b(ldr|thermistor|sensor)\b", lower):
            return ComponentFamily.SENSOR

        return ComponentFamily.UNKNOWN

    # ── Resistor parser ───────────────────────────────────────────────────

    def _parse_resistor(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        value_ohms = None
        value_display = None
        wattage = None
        tolerance = None
        mounting = None
        package = None

        # Extract value: "10K5", "4.7K", "150Ω", "100R", "100 ohm", "15K"
        # Pattern 1: "10K5" / "4K7" format — multiplier letter IMMEDIATELY between digits (no space)
        m = re.search(r"(\d+)([kKmM])(\d+)(?!\s*[%wW])", name)
        if m:
            whole = int(m.group(1))
            mult_char = m.group(2)
            frac = m.group(3)
            multiplier = _RESISTANCE_MULTIPLIER.get(mult_char, 1.0)
            value_ohms = whole * multiplier + int(frac) * (multiplier / 10)
            value_display = f"{m.group(1)}{mult_char.upper()}{frac}"
        else:
            # Pattern 2: "4.7K", "150R", "100Ω", "15K", "1M"
            m = re.search(r"(\d+(?:\.\d+)?)\s*([kKmMrRΩ])", name)
            if m:
                num = float(m.group(1))
                mult_char = m.group(2)
                multiplier = _RESISTANCE_MULTIPLIER.get(mult_char, 1.0)
                value_ohms = num * multiplier
                suffix = mult_char.upper() if mult_char.lower() in ("k", "m") else "R"
                value_display = f"{m.group(1)}{suffix}"
            else:
                # Pattern 3: "100 ohm"
                m = re.search(r"(\d+(?:\.\d+)?)\s*ohm", name, re.I)
                if m:
                    value_ohms = float(m.group(1))
                    value_display = f"{m.group(1)}R"

        # Wattage: "1/4W", "0.25W", "1W"
        m = re.search(r"(\d+)/(\d+)\s*[wW]", name)
        if m:
            wattage = float(m.group(1)) / float(m.group(2))
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*[wW](?:att)?", name)
            if m:
                wattage = float(m.group(1))

        # Tolerance: "1%", "5%"
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", name)
        if m:
            tolerance = f"{m.group(1)}%"

        # Mounting / package
        mounting, package = self._detect_mounting_package(part)

        return PartSignature(
            component_family=family,
            value_ohms=value_ohms,
            value_display=value_display,
            mounting=mounting,
            package=package,
            wattage=wattage,
            tolerance=tolerance,
        )

    # ── Capacitor parser ──────────────────────────────────────────────────

    def _parse_capacitor(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        value_pf = None
        value_display = None
        polarized = None
        dielectric = None
        voltage_rating = None
        mounting = None
        package = None

        # Extract value: "100nF", "10uF", "22pF", "100n", "10µF"
        m = re.search(r"(\d+(?:\.\d+)?)\s*([pPnNuUμµ])[fF]?", name)
        if m:
            num = float(m.group(1))
            unit_char = m.group(2).lower()
            if unit_char in ("μ", "µ"):
                unit_char = "u"
            multiplier = {"p": 1.0, "n": 1e3, "u": 1e6}.get(unit_char, 1.0)
            value_pf = num * multiplier
            unit_display = {"p": "pF", "n": "nF", "u": "uF"}.get(unit_char, "?F")
            value_display = f"{m.group(1)}{unit_display}"

        # Polarized
        lower = name.lower()
        if any(kw in lower for kw in ("electrolytic", "tantalum", "polar")):
            polarized = True

        # Dielectric
        if "ceramic" in lower or "mlcc" in lower:
            dielectric = "ceramic"
        elif "film" in lower:
            dielectric = "film"
        elif "electrolytic" in lower:
            dielectric = "electrolytic"
        for code in ("c0g", "np0", "x7r", "x5r", "y5v"):
            if code in lower:
                dielectric = code.upper()
                break

        # Voltage rating: "16V", "50V"
        m = re.search(r"(\d+)\s*[vV]", name)
        if m:
            voltage_rating = float(m.group(1))

        # Mounting / package
        mounting, package = self._detect_mounting_package(part)

        return PartSignature(
            component_family=family,
            value_pf=value_pf,
            value_display=value_display,
            mounting=mounting,
            package=package,
            polarized=polarized,
            dielectric=dielectric,
            voltage_rating=voltage_rating,
        )

    # ── Connector parser ──────────────────────────────────────────────────

    def _parse_connector(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        lower = name.lower()
        connector_subtype = None
        pin_count = None
        row_count = None
        pitch_um = None
        gender = None
        shrouded = None
        machine_tooled = None

        # Subtype detection
        if "dip socket" in lower or "dip-socket" in lower or ("socket" in lower and "dip" in lower):
            connector_subtype = "dip_socket"
        elif "ic socket" in lower:
            connector_subtype = "ic_socket"
        elif "box header" in lower or "boxed header" in lower or "shrouded header" in lower:
            connector_subtype = "box_header"
            shrouded = True
        elif "3.5mm" in lower or "3.5 mm" in lower or "thonkiconn" in lower or "kobiconn" in lower:
            connector_subtype = "audio_jack"
        elif "power" in lower and ("header" in lower or "connector" in lower):
            connector_subtype = "power_header"
        elif "female" in lower and "header" in lower:
            connector_subtype = "female_header"
        elif "male" in lower and ("header" in lower or "pin strip" in lower):
            connector_subtype = "male_header_strip"
        elif "header" in lower or "pin strip" in lower:
            connector_subtype = "header"
        elif "socket" in lower:
            connector_subtype = "socket"

        # Pin count: "15-pin", "8 pin", "5pin"
        m = re.search(r"(\d+)\s*-?\s*pin", lower)
        if m:
            pin_count = int(m.group(1))

        # Pitch: "2.54mm", "2.54 mm"
        m = re.search(r"(\d+\.?\d*)\s*mm", lower)
        if m:
            # Only treat as pitch if it's a standard pitch value, not body size
            pitch_val = float(m.group(1))
            if pitch_val in (1.0, 1.27, 2.0, 2.54, 5.08):
                pitch_um = int(pitch_val * 1000)

        # Gender
        if "female" in lower:
            gender = "female"
        elif "male" in lower:
            gender = "male"

        # Row count
        if "single row" in lower or "1 row" in lower:
            row_count = 1
        elif "dual row" in lower or "double row" in lower or "2 row" in lower:
            row_count = 2

        # Shrouded
        if "shrouded" in lower or "boxed" in lower:
            shrouded = True

        # Machine-tooled
        if "machine" in lower and "tool" in lower:
            machine_tooled = True

        # Stereo vs mono for audio jacks
        if connector_subtype == "audio_jack":
            if "stereo" in lower:
                connector_subtype = "audio_jack_stereo"
            elif "mono" in lower:
                connector_subtype = "audio_jack_mono"

        return PartSignature(
            component_family=family,
            connector_subtype=connector_subtype,
            pin_count=pin_count,
            row_count=row_count,
            pitch_um=pitch_um,
            gender=gender,
            shrouded=shrouded,
            machine_tooled=machine_tooled,
        )

    # ── Pot parser ────────────────────────────────────────────────────────

    def _parse_pot(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        lower = name.lower()
        value_ohms = None
        value_display = None
        taper = None
        body_size_mm = None
        shaft_style = None
        manufacturer_hint = None

        # Value: same multiplier map as resistors
        # "100k", "10K", "1M"
        m = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM])", name)
        if m:
            num = float(m.group(1))
            mult_char = m.group(2)
            multiplier = _RESISTANCE_MULTIPLIER.get(mult_char, 1.0)
            value_ohms = num * multiplier
            value_display = f"{m.group(1)}{mult_char.upper()}"

        # Taper: "B" (linear), "A" (log), "C" (reverse log)
        # Look for standalone B/A/C adjacent to value or "linear"/"log"/"audio"
        if re.search(r"\blinear\b", lower):
            taper = "B"
        elif re.search(r"\blog(?:arithmic)?\b", lower) or re.search(r"\baudio\b", lower):
            taper = "A"
        elif re.search(r"\breverse\s*log\b", lower):
            taper = "C"
        else:
            # Look for taper letter after value: "100k B", "10KB", "10k A"
            m_taper = re.search(r"\d+[kKmM]\s*([ABCabc])\b", name)
            if m_taper:
                taper = m_taper.group(1).upper()

        # Body size: "9mm", "16mm", "24mm"
        for size in (9, 16, 24):
            if re.search(rf"\b{size}\s*mm\b", lower):
                body_size_mm = size
                break

        # Shaft style
        if "spline" in lower:
            shaft_style = "spline"
        elif "d-shaft" in lower or "d shaft" in lower:
            shaft_style = "d-shaft"
        elif "round" in lower and "shaft" in lower:
            shaft_style = "round"

        # Manufacturer hint
        for mfr in ("alpha", "tayda", "bourns", "song huei"):
            if mfr in lower:
                manufacturer_hint = mfr.title()
                break

        return PartSignature(
            component_family=family,
            value_ohms=value_ohms,
            value_display=value_display,
            taper=taper,
            body_size_mm=body_size_mm,
            shaft_style=shaft_style,
            manufacturer_hint=manufacturer_hint,
        )

    # ── Switch parser ─────────────────────────────────────────────────────

    def _parse_switch(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        lower = name.lower()
        upper = name.upper()
        pole_throw = None
        action_pattern = None
        momentary_positions = None
        lever_style = None

        # Pole/throw: SPDT, DPDT, SPST, SP3T, etc.
        m = re.search(r"\b(SP[DST3][TI]|DP[DS][TI])\b", upper)
        if m:
            pole_throw = m.group(1)

        # Action pattern: ON-OFF-ON, ON-ON, ON-OFF, (ON)-OFF-(ON), etc.
        # Capture with possible parenthesized positions for momentary
        m = re.search(r"(\(?ON\)?(?:\s*-\s*\(?(?:ON|OFF)\)?){1,2})", upper)
        if m:
            raw_action = m.group(1)
            # Normalize spacing
            action_pattern = re.sub(r"\s*-\s*", "-", raw_action).upper()
            # Extract momentary positions: "(ON)" means momentary
            momentary = []
            positions = action_pattern.split("-")
            for i, pos in enumerate(positions):
                if pos.startswith("(") and pos.endswith(")"):
                    momentary.append(f"pos{i+1}")
            momentary_positions = tuple(momentary) if momentary else None
            # Clean parens from action_pattern for comparison
            action_pattern = action_pattern.replace("(", "").replace(")", "")

        # Lever style
        if "short" in lower and "lever" in lower:
            lever_style = "short"
        elif "flat" in lower:
            lever_style = "flat"
        elif "long" in lower and "lever" in lower:
            lever_style = "long"
        elif "lever" in lower:
            lever_style = "standard"

        return PartSignature(
            component_family=family,
            pole_throw=pole_throw,
            action_pattern=action_pattern,
            momentary_positions=momentary_positions,
            lever_style=lever_style,
        )

    # ── Semiconductor parser (IC / Transistor / Diode) ────────────────────

    def _parse_semiconductor(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        orderable_mpn = None
        base_device = None
        packing_suffix = None
        package = None
        mounting = None

        # Use part.mpn if populated, else parse from name
        mpn_source = part.mpn if part.mpn else name

        # Try to split MPN into base_device + packing_suffix
        base_device, packing_suffix, orderable_mpn = self._split_mpn(mpn_source)

        # Package detection
        _, package = self._detect_mounting_package(part)
        if package is None:
            # Check name for package hints
            m_pkg = re.search(r"\b(DIP-?\d+|SOIC-?\d+|SOT-?23|SOT-?223|TSSOP-?\d+|QFP-?\d+|PDIP-?\d+)\b", name, re.I)
            if m_pkg:
                package = m_pkg.group(1).upper()

        # Mounting
        mounting_val, _ = self._detect_mounting_package(part)

        return PartSignature(
            component_family=family,
            orderable_mpn=orderable_mpn,
            base_device=base_device,
            packing_suffix=packing_suffix,
            package=package,
            mounting=mounting_val,
        )

    def _split_mpn(self, mpn: str) -> tuple[str | None, str | None, str | None]:
        """Split an MPN into (base_device, packing_suffix, full_mpn).

        Examples:
            "CD4070BM96"     -> ("CD4070BM", "96", "CD4070BM96")
            "CD4070BM/TR"    -> ("CD4070BM", "/TR", "CD4070BM/TR")
            "BCM847DS,115"   -> ("BCM847DS", ",115", "BCM847DS,115")
            "PT2399-SN"      -> ("PT2399", "-SN", "PT2399-SN")
            "PT2399"         -> ("PT2399", None, "PT2399")
            "TL072 Dual Op-Amp" -> ("TL072", None, "TL072")
        """
        if not mpn or not mpn.strip():
            return None, None, None

        # Clean: take first token if name contains spaces (for name-based parsing)
        clean = mpn.strip()

        # Known suffix separators: comma, slash
        m = re.match(r"^([A-Z0-9]+[A-Z])([,/].+)$", clean, re.I)
        if m:
            return m.group(1).upper(), m.group(2), clean

        # Dash suffix: "PT2399-SN" but NOT "SOT-23" (package codes)
        m = re.match(r"^([A-Z]{1,4}\d{3,5}[A-Z]*)(-[A-Z]{1,4}\d{0,3})$", clean, re.I)
        if m:
            return m.group(1).upper(), m.group(2), clean

        # Trailing numeric packing code after letter+digit+letter base: "CD4070BM96"
        # Requires at least one trailing alpha char before the numeric suffix
        m = re.match(r"^([A-Z]{1,4}\d{2,5}[A-Z]{1,3})(\d{2,3})$", clean, re.I)
        if m:
            return m.group(1).upper(), m.group(2), clean

        # Simple base device: extract leading alphanumeric part number
        m = re.match(r"^([A-Z]{1,4}\d{2,5}[A-Z]{0,3})\b", clean, re.I)
        if m:
            base = m.group(1).upper()
            rest = clean[len(m.group(1)):].strip()
            if rest and not rest[0].isalnum():
                return base, None, base
            return base, None, base

        # Fallback for bare device names
        m = re.match(r"^([A-Z0-9]+)", clean, re.I)
        if m:
            return m.group(1).upper(), None, m.group(1).upper()

        return None, None, None

    # ── LED parser ────────────────────────────────────────────────────────

    def _parse_led(self, part: Part, family: ComponentFamily) -> PartSignature:
        name = part.name
        lower = name.lower()
        package = None
        value_display = None

        # Size: "3mm", "5mm"
        m = re.search(r"(\d+)\s*mm", lower)
        if m:
            value_display = f"{m.group(1)}mm"

        # Color
        for color in ("red", "green", "blue", "yellow", "white", "orange", "amber", "bipolar"):
            if color in lower:
                value_display = f"{value_display} {color}" if value_display else color
                break

        mounting, package = self._detect_mounting_package(part)

        return PartSignature(
            component_family=family,
            value_display=value_display,
            mounting=mounting,
            package=package,
        )

    # ── Regulator parser ──────────────────────────────────────────────────

    def _parse_regulator(self, part: Part, family: ComponentFamily) -> PartSignature:
        base_device, packing_suffix, orderable_mpn = self._split_mpn(part.mpn or part.name)
        mounting, package = self._detect_mounting_package(part)

        return PartSignature(
            component_family=family,
            base_device=base_device,
            packing_suffix=packing_suffix,
            orderable_mpn=orderable_mpn,
            mounting=mounting,
            package=package,
        )

    # ── Shared helpers ────────────────────────────────────────────────────

    def _detect_mounting_package(self, part: Part) -> tuple[str | None, str | None]:
        """Detect mounting type and package from part name and metadata.

        Returns (mounting, package).
        """
        name = part.name
        lower = name.lower()
        pkg_field = (part.default_package or "").strip()
        mounting = None
        package = None

        # Check package field first
        if pkg_field:
            pkg_upper = pkg_field.upper()
            if pkg_upper in _SMD_PACKAGES:
                mounting = "smd"
                package = pkg_upper
                return mounting, package
            if pkg_upper in ("THT", "THROUGH_HOLE", "THROUGH-HOLE", "AXIAL", "RADIAL"):
                mounting = "through_hole"
                package = pkg_upper
                return mounting, package
            package = pkg_field

        # Check name for SMD indicators
        for smd_pkg in _SMD_PACKAGES:
            if smd_pkg in name:
                mounting = "smd"
                package = smd_pkg
                return mounting, package

        if re.search(r"\bSMD\b", name, re.I) or re.search(r"\bSMT\b", name, re.I):
            mounting = "smd"
        elif re.search(r"\b(through.?hole|tht|axial|radial)\b", lower):
            mounting = "through_hole"

        # Check for DIP/SOT/SOIC packages in name
        m = re.search(r"\b(DIP-?\d+|SOIC|SOT-?23|SOT-?223|TSSOP|QFP)\b", name, re.I)
        if m:
            package = m.group(1).upper()

        return mounting, package
