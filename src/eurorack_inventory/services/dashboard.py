from __future__ import annotations

from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.modules import ModuleRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository


class DashboardService:
    def __init__(
        self,
        part_repo: PartRepository,
        storage_repo: StorageRepository,
        module_repo: ModuleRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self.module_repo = module_repo
        self.audit_repo = audit_repo

    def snapshot(self) -> dict:
        return {
            "parts": self.part_repo.count_parts(),
            "containers": self.storage_repo.count_containers(),
            "slots": self.storage_repo.count_slots(),
            "modules": self.module_repo.count_modules(),
            "recent_events": self.audit_repo.list_recent(limit=10),
        }
