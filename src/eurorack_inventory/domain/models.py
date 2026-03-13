from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Part:
    id: int | None
    fingerprint: str
    name: str
    normalized_name: str
    category: str | None = None
    manufacturer: str | None = None
    mpn: str | None = None
    supplier_name: str | None = None
    supplier_sku: str | None = None
    purchase_url: str | None = None
    default_package: str | None = None
    notes: str | None = None
    qty: int = 0
    slot_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class PartAlias:
    id: int | None
    part_id: int
    alias: str
    normalized_alias: str


@dataclass(slots=True)
class StorageContainer:
    id: int | None
    name: str
    container_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    sort_order: int = 0


@dataclass(slots=True)
class StorageSlot:
    id: int | None
    container_id: int
    label: str
    slot_type: str
    ordinal: int | None = None
    x1: int | None = None
    y1: int | None = None
    x2: int | None = None
    y2: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None


@dataclass(slots=True)
class InventorySummary:
    part_id: int
    name: str
    category: str | None
    supplier_sku: str | None
    total_qty: int
    locations: str
    notes: str | None = None


@dataclass(slots=True)
class PartDetail:
    part: Part
    aliases: list[PartAlias]
    location: str


@dataclass(slots=True)
class Module:
    id: int | None
    fingerprint: str
    name: str
    maker: str = "Nonlinearcircuits"
    revision: str | None = None
    source_url: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class BomLine:
    id: int | None
    module_id: int
    part_id: int
    qty_required: int
    reference_note: str | None = None
    is_optional: bool = False


@dataclass(slots=True)
class Build:
    id: int | None
    module_id: int
    nickname: str | None = None
    status: str = "planned"
    started_at: str | None = None
    completed_at: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class BuildUpdate:
    id: int | None
    build_id: int
    created_at: str | None
    status: str | None
    note: str


@dataclass(slots=True)
class ImportReport:
    imported_parts: int = 0
    updated_parts: int = 0
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Imported parts={self.imported_parts}, updated parts={self.updated_parts}, "
            f"skipped rows={self.skipped_rows}"
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
