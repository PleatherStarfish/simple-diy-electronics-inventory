from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eurorack_inventory.config import package_dir
from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.logging_config import MemoryLogHandler, configure_logging
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.modules import ModuleRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.dashboard import DashboardService
from eurorack_inventory.services.importer import SpreadsheetImportService
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.modules import ModuleService
from eurorack_inventory.services.search import SearchService
from eurorack_inventory.services.assignment import AssignmentService
from eurorack_inventory.services.settings import SettingsRepository
from eurorack_inventory.services.storage import StorageService


@dataclass(slots=True)
class AppContext:
    db: Database
    log_handler: MemoryLogHandler
    part_repo: PartRepository
    storage_repo: StorageRepository
    module_repo: ModuleRepository
    audit_repo: AuditRepository
    inventory_service: InventoryService
    storage_service: StorageService
    module_service: ModuleService
    search_service: SearchService
    import_service: SpreadsheetImportService
    dashboard_service: DashboardService
    settings_repo: SettingsRepository
    assignment_service: AssignmentService


def build_app_context(db_path: Path) -> AppContext:
    db = Database(db_path)
    log_handler = configure_logging(db_path.parent / "logs")

    migrations_dir = package_dir() / "db" / "migrations"
    MigrationRunner(db, migrations_dir).apply()

    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    module_repo = ModuleRepository(db)
    audit_repo = AuditRepository(db)

    inventory_service = InventoryService(part_repo, storage_repo, audit_repo)
    storage_service = StorageService(storage_repo, audit_repo)
    module_service = ModuleService(module_repo, part_repo, audit_repo)
    search_service = SearchService(part_repo)
    import_service = SpreadsheetImportService(inventory_service, storage_service, audit_repo)
    dashboard_service = DashboardService(part_repo, storage_repo, module_repo, audit_repo)

    settings_repo = SettingsRepository(db)
    assignment_service = AssignmentService(part_repo, storage_repo, audit_repo, settings_repo)

    storage_service.ensure_default_unassigned_slot()
    search_service.rebuild()

    return AppContext(
        db=db,
        log_handler=log_handler,
        part_repo=part_repo,
        storage_repo=storage_repo,
        module_repo=module_repo,
        audit_repo=audit_repo,
        inventory_service=inventory_service,
        storage_service=storage_service,
        module_service=module_service,
        search_service=search_service,
        import_service=import_service,
        dashboard_service=dashboard_service,
        settings_repo=settings_repo,
        assignment_service=assignment_service,
    )
