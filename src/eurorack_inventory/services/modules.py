from __future__ import annotations

from eurorack_inventory.domain.models import BomLine, Build, BuildUpdate, Module
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.modules import ModuleRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.common import make_module_fingerprint


class ModuleService:
    def __init__(
        self,
        module_repo: ModuleRepository,
        part_repo: PartRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.module_repo = module_repo
        self.part_repo = part_repo
        self.audit_repo = audit_repo

    def upsert_module(
        self,
        *,
        name: str,
        maker: str = "Nonlinearcircuits",
        revision: str | None = None,
        source_url: str | None = None,
        notes: str | None = None,
    ) -> Module:
        module = Module(
            id=None,
            fingerprint=make_module_fingerprint(name=name, maker=maker, revision=revision),
            name=name,
            maker=maker,
            revision=revision,
            source_url=source_url,
            notes=notes,
        )
        saved = self.module_repo.upsert_module(module)
        self.audit_repo.add_event(
            event_type="module.upserted",
            entity_type="module",
            entity_id=saved.id,
            message=f"Upserted module {saved.name}",
            payload={"maker": saved.maker, "revision": saved.revision},
        )
        return saved

    def add_bom_line(
        self,
        *,
        module_id: int,
        part_id: int,
        qty_required: int,
        reference_note: str | None = None,
        is_optional: bool = False,
    ) -> BomLine:
        bom = self.module_repo.add_bom_line(
            BomLine(
                id=None,
                module_id=module_id,
                part_id=part_id,
                qty_required=qty_required,
                reference_note=reference_note,
                is_optional=is_optional,
            )
        )
        self.audit_repo.add_event(
            event_type="bom.added",
            entity_type="module",
            entity_id=module_id,
            message=f"Added BOM line part_id={part_id}",
            payload={"qty_required": qty_required, "is_optional": is_optional},
        )
        return bom

    def create_build(
        self,
        *,
        module_id: int,
        nickname: str | None = None,
        status: str = "planned",
        notes: str | None = None,
    ) -> Build:
        build = self.module_repo.create_build(
            Build(id=None, module_id=module_id, nickname=nickname, status=status, notes=notes)
        )
        self.audit_repo.add_event(
            event_type="build.created",
            entity_type="build",
            entity_id=build.id,
            message=f"Created build for module_id={module_id}",
            payload={"status": status},
        )
        return build

    def add_build_update(
        self,
        *,
        build_id: int,
        status: str | None,
        note: str,
    ) -> BuildUpdate:
        update = self.module_repo.add_build_update(
            BuildUpdate(id=None, build_id=build_id, created_at=None, status=status, note=note)
        )
        self.audit_repo.add_event(
            event_type="build.updated",
            entity_type="build",
            entity_id=build_id,
            message="Added build update",
            payload={"status": status},
        )
        return update

    def list_modules(self) -> list[Module]:
        return self.module_repo.list_modules()

    def list_builds(self, module_id: int) -> list[Build]:
        return self.module_repo.list_builds(module_id)

    def get_module_availability(self, module_id: int) -> list[dict]:
        bom_lines = self.module_repo.list_bom_lines(module_id)
        summaries = {summary.part_id: summary for summary in self.part_repo.list_inventory_summaries()}
        results: list[dict] = []
        for line in bom_lines:
            summary = summaries.get(line.part_id)
            total_qty = summary.total_qty if summary else 0
            results.append(
                {
                    "part_id": line.part_id,
                    "qty_required": line.qty_required,
                    "qty_available": total_qty,
                    "enough_stock": total_qty >= line.qty_required,
                    "reference_note": line.reference_note,
                    "is_optional": line.is_optional,
                }
            )
        return results

    def counts(self) -> dict[str, int]:
        return {
            "modules": self.module_repo.count_modules(),
        }
