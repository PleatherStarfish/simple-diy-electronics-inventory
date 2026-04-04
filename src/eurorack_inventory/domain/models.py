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
    storage_class_override: str | None = None


@dataclass(slots=True)
class PartAlias:
    id: int | None
    part_id: int
    alias: str
    normalized_alias: str


@dataclass(slots=True)
class PartLocation:
    id: int | None
    part_id: int
    slot_id: int
    qty: int
    created_at: str | None = None
    updated_at: str | None = None
    container_name: str | None = None
    slot_label: str | None = None

    @property
    def is_unassigned(self) -> bool:
        return self.container_name == "Unassigned"

    @property
    def location_label(self) -> str:
        if self.container_name and self.slot_label:
            return f"{self.container_name} / {self.slot_label}"
        return f"slot #{self.slot_id}"


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
    default_package: str | None
    supplier_sku: str | None
    total_qty: int
    locations: str
    notes: str | None = None


@dataclass(slots=True)
class PartDetail:
    part: Part
    aliases: list[PartAlias]
    location: str
    locations: list[PartLocation] = field(default_factory=list)


@dataclass(slots=True)
class Project:
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
    project_id: int
    part_id: int
    qty_required: int
    reference_note: str | None = None
    is_optional: bool = False


@dataclass(slots=True)
class Build:
    id: int | None
    project_id: int
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
class BomSource:
    id: int | None
    filename: str
    file_path: str
    file_hash: str
    source_kind: str
    parser_key: str
    manufacturer: str
    module_name: str
    extracted_at: str | None
    notes: str | None = None
    promoted_project_id: int | None = None


@dataclass(slots=True)
class RawBomItem:
    id: int | None
    bom_source_id: int
    line_number: int
    raw_description: str
    raw_qty: str
    raw_reference: str | None = None
    raw_supplier_pn: str | None = None
    raw_notes: str | None = None


@dataclass(slots=True)
class NormalizedBomItem:
    id: int | None
    bom_source_id: int
    raw_item_id: int
    component_type: str | None
    normalized_value: str
    qty: int
    package_hint: str | None = None
    reference: str | None = None
    tayda_pn: str | None = None
    mouser_pn: str | None = None
    part_id: int | None = None
    match_confidence: float | None = None
    match_status: str = "unmatched"
    is_verified: bool = False
    notes: str | None = None


@dataclass(slots=True)
class ShoppingListItem:
    normalized_value: str
    component_type: str | None
    package_hint: str | None
    qty_needed: int
    qty_available: int
    qty_to_buy: int
    tayda_pn: str | None = None
    mouser_pn: str | None = None
    bom_source_names: list[str] = field(default_factory=list)
    part_id: int | None = None


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
