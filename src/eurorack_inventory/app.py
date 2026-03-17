from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eurorack_inventory.config import package_dir
from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.logging_config import MemoryLogHandler, configure_logging
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.dashboard import DashboardService
from eurorack_inventory.services.importer import SpreadsheetImportService
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.projects import ProjectService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.services.assignment import AssignmentService
from eurorack_inventory.services.bom import BomService
from eurorack_inventory.services.bom_matching import BomMatchingService
from eurorack_inventory.services.settings import SettingsRepository
from eurorack_inventory.services.dedup import DedupService
from eurorack_inventory.services.storage import StorageService
from eurorack_inventory.repositories.dedup_feedback import DedupFeedbackRepository


@dataclass(slots=True)
class AppContext:
    db: Database
    log_handler: MemoryLogHandler
    part_repo: PartRepository
    storage_repo: StorageRepository
    project_repo: ProjectRepository
    audit_repo: AuditRepository
    inventory_service: InventoryService
    storage_service: StorageService
    project_service: ProjectService
    search_service: SearchService
    import_service: SpreadsheetImportService
    dashboard_service: DashboardService
    settings_repo: SettingsRepository
    assignment_service: AssignmentService
    bom_repo: BomRepository
    bom_service: BomService
    dedup_service: DedupService
    dedup_feedback_repo: DedupFeedbackRepository


def build_app_context(db_path: Path) -> AppContext:
    db = Database(db_path)
    log_handler = configure_logging(db_path.parent / "logs")

    migrations_dir = package_dir() / "db" / "migrations"
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    project_repo = ProjectRepository(db)
    audit_repo = AuditRepository(db)

    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo, part_repo)
    project_service = ProjectService(project_repo, part_repo, audit_repo)
    search_service = SearchService(part_repo)
    import_service = SpreadsheetImportService(inventory_service, storage_service, audit_repo)

    settings_repo = SettingsRepository(db)
    assignment_service = AssignmentService(part_repo, storage_repo, audit_repo, settings_repo)

    bom_repo = BomRepository(db)
    bom_matching_service = BomMatchingService(search_service, part_repo)
    bom_service = BomService(bom_repo, part_repo, bom_matching_service, audit_repo)

    dedup_feedback_repo = DedupFeedbackRepository(db)
    dedup_service = DedupService(db, part_repo, audit_repo, search_service, dedup_feedback_repo)
    dashboard_service = DashboardService(part_repo, storage_repo, project_repo, audit_repo, bom_repo)

    storage_service.ensure_default_unassigned_slot()
    search_service.rebuild()

    return AppContext(
        db=db,
        log_handler=log_handler,
        part_repo=part_repo,
        storage_repo=storage_repo,
        project_repo=project_repo,
        audit_repo=audit_repo,
        inventory_service=inventory_service,
        storage_service=storage_service,
        project_service=project_service,
        search_service=search_service,
        import_service=import_service,
        dashboard_service=dashboard_service,
        settings_repo=settings_repo,
        assignment_service=assignment_service,
        bom_repo=bom_repo,
        bom_service=bom_service,
        dedup_service=dedup_service,
        dedup_feedback_repo=dedup_feedback_repo,
    )
