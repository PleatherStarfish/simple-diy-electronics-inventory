from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from eurorack_inventory.domain.models import ImportReport
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.storage import StorageService

logger = logging.getLogger(__name__)


class SpreadsheetImportService:
    SHEET_NAME = "Consolidated Inventory"

    def __init__(
        self,
        inventory_service: InventoryService,
        storage_service: StorageService,
        audit_repo: AuditRepository,
    ) -> None:
        self.inventory_service = inventory_service
        self.storage_service = storage_service
        self.audit_repo = audit_repo

    def import_file(self, path: str | Path, *, mode: str = "replace_snapshot") -> ImportReport:
        report = ImportReport()
        path = Path(path).expanduser().resolve()

        df = pd.read_excel(path, sheet_name=self.SHEET_NAME)
        if mode not in {"replace_snapshot", "merge_quantities"}:
            raise ValueError(f"Unsupported import mode: {mode!r}")

        target_slot = self.storage_service.ensure_default_unassigned_slot()

        for index, row in df.iterrows():
            category = self._to_text(row.get("Category"))
            component = self._to_text(row.get("Component"))
            qty_value = row.get("Total Qty")
            supplier_sku = self._to_text(row.get("Tayda SKU"))
            notes = self._to_text(row.get("Merged From"))

            if not component:
                report.skipped_rows += 1
                continue
            qty = self._safe_int(qty_value)
            if qty is None or qty <= 0:
                report.skipped_rows += 1
                report.warnings.append(
                    f"Skipped row {index + 2}: non-positive qty {qty_value!r} for component {component!r}"
                )
                continue

            existing_part_count_before = self.inventory_service.part_repo.count_parts()
            part = self.inventory_service.upsert_part(
                name=component,
                category=category,
                supplier_sku=supplier_sku,
                notes=notes,
                qty=qty,
                slot_id=target_slot.id,
            )
            existing_part_count_after = self.inventory_service.part_repo.count_parts()
            if existing_part_count_after > existing_part_count_before:
                report.imported_parts += 1
            else:
                report.updated_parts += 1

            if category:
                self.inventory_service.add_alias(part.id, f"{component} {category}")
            if supplier_sku:
                self.inventory_service.add_alias(part.id, supplier_sku)

        self.audit_repo.add_event(
            event_type="import.completed",
            entity_type="import",
            entity_id=None,
            message=f"Imported spreadsheet {path.name}",
            payload={
                "path": str(path),
                "mode": mode,
                "report": {
                    "imported_parts": report.imported_parts,
                    "updated_parts": report.updated_parts,
                    "skipped_rows": report.skipped_rows,
                },
            },
        )
        logger.info(report.summary())
        return report

    @staticmethod
    def _to_text(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _safe_int(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
