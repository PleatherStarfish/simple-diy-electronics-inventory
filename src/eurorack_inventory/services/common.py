from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = normalized.replace("ohm", " ohm ")
    normalized = re.sub(r"[_/]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9.+-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def make_part_fingerprint(
    *,
    category: str | None,
    name: str,
    supplier_sku: str | None,
    package: str | None = None,
) -> str:
    bits = [
        normalize_text(category),
        normalize_text(name),
        normalize_text(supplier_sku),
        normalize_text(package),
    ]
    return "|".join(bits)


def make_module_fingerprint(name: str, maker: str, revision: str | None = None) -> str:
    bits = [normalize_text(maker), normalize_text(name), normalize_text(revision)]
    return "|".join(bits)
