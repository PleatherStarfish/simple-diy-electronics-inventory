from __future__ import annotations

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import utc_now_iso


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: int | None,
        message: str,
        payload: dict | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO audit_events (created_at, event_type, entity_type, entity_id, message, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                event_type,
                entity_type,
                entity_id,
                message,
                self.db.dumps_json(payload or {}),
            ),
        )

    def list_recent(self, limit: int = 50) -> list[dict]:
        rows = self.db.query_all(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]
