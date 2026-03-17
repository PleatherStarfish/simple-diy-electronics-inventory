"""
BOM Service (Orchestrator)
Coordinates extraction, normalization, matching, and persistence of BOM data.
"""
from __future__ import annotations

import logging
from pathlib import Path

from eurorack_inventory.domain.models import (
    BomSource,
    ShoppingListItem,
    utc_now_iso,
)
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.bom_extractor import (
    check_pdf_available,
    clean_module_name,
    extract_csv,
    extract_pdf,
    file_hash,
    format_pdf_runtime_error,
    get_pdf_runtime_status,
)
from eurorack_inventory.services.bom_matching import BomMatchingService
from eurorack_inventory.services.bom_normalizer import normalize

logger = logging.getLogger(__name__)


class BomService:
    def __init__(
        self,
        bom_repo: BomRepository,
        part_repo: PartRepository,
        matching_service: BomMatchingService,
        audit_repo: AuditRepository,
    ) -> None:
        self.bom_repo = bom_repo
        self.part_repo = part_repo
        self.matching = matching_service
        self.audit_repo = audit_repo

    # ── Import ──────────────────────────────────────────────────────

    def import_csv(self, csv_path: Path) -> list[BomSource]:
        """
        Import a CSV file. Returns a list of BomSources (one per module
        in a combined CSV, or one for a single-module CSV).
        """
        csv_path = csv_path.resolve()
        fhash = file_hash(csv_path)
        modules = extract_csv(csv_path)
        if not modules:
            return []

        sources: list[BomSource] = []
        with self.bom_repo.db.transaction():
            for module_name, raw_items in modules.items():
                existing = self.bom_repo.find_by_hash_and_module(fhash, module_name)
                if existing:
                    self.bom_repo.delete_bom_source(existing.id)
                    logger.info("Replacing existing BOM source for %s", module_name)

                source = self.bom_repo.create_bom_source(BomSource(
                    id=None,
                    filename=csv_path.name,
                    file_path=str(csv_path),
                    file_hash=fhash,
                    source_kind="csv",
                    parser_key="nlc",
                    manufacturer="Nonlinearcircuits",
                    module_name=module_name,
                    extracted_at=utc_now_iso(),
                ))

                for item in raw_items:
                    item.bom_source_id = source.id
                self.bom_repo.add_raw_items_bulk(raw_items)

                raw_with_ids = self.bom_repo.list_raw_items(source.id)
                normalized = normalize(raw_with_ids)
                for item in normalized:
                    item.bom_source_id = source.id
                self.bom_repo.add_normalized_items_bulk(normalized)

                self.audit_repo.add_event(
                    event_type="bom.imported",
                    entity_type="bom_source",
                    entity_id=source.id,
                    message=f"Imported BOM for {module_name} from {csv_path.name}",
                    payload={
                        "raw_count": len(raw_items),
                        "normalized_count": len(normalized),
                        "source_kind": "csv",
                    },
                )
                sources.append(source)

        return sources

    def import_pdf(self, pdf_path: Path) -> BomSource:
        """Import a single PDF. Requires tabula-py + Java."""
        runtime_status = get_pdf_runtime_status()
        if not runtime_status.available:
            raise RuntimeError(format_pdf_runtime_error(runtime_status))

        pdf_path = pdf_path.resolve()
        fhash = file_hash(pdf_path)
        module_name = clean_module_name(pdf_path.stem)
        raw_items = extract_pdf(pdf_path)
        if not raw_items:
            raise ValueError(f"No BOM data detected in {pdf_path.name}")

        preview_normalized = normalize(raw_items)
        if not preview_normalized:
            raise ValueError(f"Could not normalize any BOM rows from {pdf_path.name}")

        with self.bom_repo.db.transaction():
            existing = self.bom_repo.find_by_hash_and_module(fhash, module_name)
            if existing:
                self.bom_repo.delete_bom_source(existing.id)

            source = self.bom_repo.create_bom_source(BomSource(
                id=None,
                filename=pdf_path.name,
                file_path=str(pdf_path),
                file_hash=fhash,
                source_kind="pdf",
                parser_key="nlc",
                manufacturer="Nonlinearcircuits",
                module_name=module_name,
                extracted_at=utc_now_iso(),
            ))

            for item in raw_items:
                item.bom_source_id = source.id
            self.bom_repo.add_raw_items_bulk(raw_items)

            raw_with_ids = self.bom_repo.list_raw_items(source.id)
            normalized = normalize(raw_with_ids)
            if not normalized:
                raise RuntimeError(
                    f"Normalization unexpectedly produced no rows after importing {pdf_path.name}"
                )
            for item in normalized:
                item.bom_source_id = source.id
            self.bom_repo.add_normalized_items_bulk(normalized)

            self.audit_repo.add_event(
                event_type="bom.imported",
                entity_type="bom_source",
                entity_id=source.id,
                message=f"Imported BOM for {module_name} from {pdf_path.name}",
                payload={
                    "raw_count": len(raw_items),
                    "normalized_count": len(normalized),
                    "source_kind": "pdf",
                },
            )
        return source

    def import_directory(self, dir_path: Path) -> list[BomSource]:
        """Batch import all supported files from a directory."""
        dir_path = dir_path.resolve()
        sources: list[BomSource] = []

        csv_files = sorted(dir_path.glob("*.csv"))
        for csv_file in csv_files:
            sources.extend(self.import_csv(csv_file))

        if check_pdf_available():
            pdf_files = sorted(dir_path.glob("*.pdf")) + sorted(dir_path.glob("*.PDF"))
            for pdf_file in pdf_files:
                try:
                    sources.append(self.import_pdf(pdf_file))
                except Exception as e:
                    logger.warning("Failed to import %s: %s", pdf_file.name, e)

        return sources

    # ── Re-normalize ────────────────────────────────────────────────

    def re_normalize(self, source_id: int) -> int:
        """Re-run normalizer on existing raw items. Returns count of normalized items."""
        with self.bom_repo.db.transaction():
            self.bom_repo.delete_normalized_items(source_id)
            raw_items = self.bom_repo.list_raw_items(source_id)
            normalized = normalize(raw_items)
            for item in normalized:
                item.bom_source_id = source_id
            self.bom_repo.add_normalized_items_bulk(normalized)
        return len(normalized)

    # ── Matching ────────────────────────────────────────────────────

    def auto_match_bom(self, source_id: int) -> int:
        """Run auto-matching on all unmatched items. Returns count matched."""
        with self.bom_repo.db.transaction():
            return self.matching.auto_match_bom(source_id, self.bom_repo)

    def auto_match_item(self, item_id: int) -> None:
        """Re-match a single item after edit."""
        with self.bom_repo.db.transaction():
            self.matching.auto_match_item(item_id, self.bom_repo)

    # ── Create part & match ─────────────────────────────────────────

    def create_part_and_match(self, item_id: int, part_fields: dict):
        """Create a new inventory part (or find existing) and link to a BOM item.

        If a part with the same fingerprint already exists, links to the existing
        part WITHOUT modifying it. New parts are created with qty=0.
        """
        from eurorack_inventory.domain.models import Part
        from eurorack_inventory.services.common import make_part_fingerprint, normalize_text

        fingerprint = make_part_fingerprint(
            category=part_fields.get("category"),
            name=part_fields["name"],
            supplier_sku=part_fields.get("supplier_sku"),
            package=part_fields.get("default_package"),
        )

        with self.bom_repo.db.transaction():
            existing = self.part_repo.db.query_one(
                "SELECT id FROM parts WHERE fingerprint = ?", (fingerprint,)
            )
            if existing:
                part = self.part_repo.get_part_by_id(existing["id"])
            else:
                part = Part(
                    id=None,
                    fingerprint=fingerprint,
                    name=part_fields["name"],
                    normalized_name=normalize_text(part_fields["name"]),
                    category=part_fields.get("category"),
                    manufacturer=part_fields.get("manufacturer"),
                    mpn=part_fields.get("mpn"),
                    supplier_name=part_fields.get("supplier_name"),
                    supplier_sku=part_fields.get("supplier_sku"),
                    purchase_url=part_fields.get("purchase_url"),
                    default_package=part_fields.get("default_package"),
                    notes=part_fields.get("notes"),
                    qty=0,
                    slot_id=part_fields.get("slot_id"),
                    storage_class_override=part_fields.get("storage_class_override"),
                )
                part = self.part_repo.upsert_part(part)
                self.audit_repo.add_event(
                    event_type="part.created_from_bom",
                    entity_type="part",
                    entity_id=part.id,
                    message=f"Created part '{part.name}' from BOM item",
                )

            self.bom_repo.link_to_part(item_id, part.id, 1.0, "manually_matched")
            self.bom_repo.update_normalized_item(item_id, is_verified=True)

            self.audit_repo.add_event(
                event_type="bom.matched",
                entity_type="normalized_bom_item",
                entity_id=item_id,
                message=f"Matched BOM item to part '{part.name}' (created from BOM)",
                payload={"part_id": part.id},
            )

        return part

    # ── Rename ────────────────────────────────────────────────────

    def rename_source(self, source_id: int, new_name: str) -> None:
        """Rename a BOM source's module name."""
        source = self.bom_repo.get_bom_source(source_id)
        if source is None:
            raise ValueError(f"BOM source {source_id} not found")
        old_name = source.module_name
        self.bom_repo.rename_bom_source(source_id, new_name)
        self.audit_repo.add_event(
            event_type="bom.renamed",
            entity_type="bom_source",
            entity_id=source_id,
            message=f"Renamed BOM source '{old_name}' to '{new_name}'",
        )

    # ── Relink file ─────────────────────────────────────────────────

    def relink_source_file(self, source_id: int, new_path: Path) -> None:
        """Update the file path for a BOM source (e.g. after the file was moved)."""
        source = self.bom_repo.get_bom_source(source_id)
        if source is None:
            raise ValueError(f"BOM source {source_id} not found")
        resolved = str(new_path.resolve())
        self.bom_repo.update_file_path(source_id, resolved)
        self.audit_repo.add_event(
            event_type="bom.relinked",
            entity_type="bom_source",
            entity_id=source_id,
            message=f"Relinked BOM source '{source.module_name}' to {new_path.name}",
            payload={"old_path": source.file_path, "new_path": resolved},
        )

    # ── Shopping list ───────────────────────────────────────────────

    def get_shopping_list(self, source_ids: list[int]) -> list[ShoppingListItem]:
        """Compute shopping list for selected BOM sources."""
        raw = self.bom_repo.get_shopping_list(source_ids)
        return [
            ShoppingListItem(
                normalized_value=r["normalized_value"],
                component_type=r["component_type"],
                package_hint=r["package_hint"],
                qty_needed=r["qty_needed"],
                qty_available=r["qty_available"],
                qty_to_buy=r["qty_to_buy"],
                tayda_pn=r.get("tayda_pn"),
                mouser_pn=r.get("mouser_pn"),
                bom_source_names=r["bom_source_names"],
                part_id=r.get("part_id"),
            )
            for r in raw
        ]

    # ── Promote to Project ──────────────────────────────────────────

    def promote_to_project(self, source_id: int):
        """
        Create a Project from a fully verified BOM.
        All normalized items must be verified and either matched or skipped.
        """
        from eurorack_inventory.services.projects import ProjectService
        from eurorack_inventory.repositories.projects import ProjectRepository

        source = self.bom_repo.get_bom_source(source_id)
        if source is None:
            raise ValueError(f"BOM source {source_id} not found")
        if source.promoted_project_id is not None:
            raise ValueError(f"BOM source already promoted to project {source.promoted_project_id}")

        items = self.bom_repo.list_normalized_items(source_id)
        if not items:
            raise ValueError("BOM has no normalized items")

        # Gate: all items must be verified and either matched or skipped
        for item in items:
            if not item.is_verified:
                raise ValueError(
                    f"Item '{item.normalized_value}' is not verified. "
                    "All items must be verified before promotion."
                )
            if item.match_status not in ("manually_matched", "auto_matched", "skipped"):
                raise ValueError(
                    f"Item '{item.normalized_value}' is unmatched. "
                    "All items must be matched or skipped before promotion."
                )

        # Create project
        with self.bom_repo.db.transaction():
            project_repo = ProjectRepository(self.bom_repo.db)
            project_svc = ProjectService(project_repo, self.part_repo, self.audit_repo)
            project = project_svc.upsert_project(
                name=source.module_name,
                maker=source.manufacturer,
            )

            for item in items:
                if item.part_id is not None and item.match_status != "skipped":
                    project_svc.add_bom_line(
                        project_id=project.id,
                        part_id=item.part_id,
                        qty_required=item.qty,
                        reference_note=item.reference,
                        is_optional=False,
                    )

            self.bom_repo.set_promoted_project_id(source_id, project.id)
            self.audit_repo.add_event(
                event_type="bom.promoted",
                entity_type="bom_source",
                entity_id=source_id,
                message=f"Promoted BOM {source.module_name} to project {project.id}",
                payload={"project_id": project.id},
            )

        return project

    # ── Delete ──────────────────────────────────────────────────────

    def delete_source(self, source_id: int) -> None:
        """Delete a BOM source and all its items (cascade)."""
        source = self.bom_repo.get_bom_source(source_id)
        if source:
            with self.bom_repo.db.transaction():
                self.bom_repo.delete_bom_source(source_id)
                self.audit_repo.add_event(
                    event_type="bom.deleted",
                    entity_type="bom_source",
                    entity_id=source_id,
                    message=f"Deleted BOM source {source.module_name}",
                )

    # ── Queries ─────────────────────────────────────────────────────

    def list_bom_sources(self) -> list[BomSource]:
        return self.bom_repo.list_bom_sources()

    def counts(self) -> dict[str, int]:
        return {"bom_sources": self.bom_repo.count_bom_sources()}
