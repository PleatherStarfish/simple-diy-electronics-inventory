"""Repository for dedup feedback persistence (merge / not_duplicate decisions)."""
from __future__ import annotations

import json
from dataclasses import asdict

from eurorack_inventory.db.connection import Database
from eurorack_inventory.domain.models import utc_now_iso
from eurorack_inventory.domain.part_signature import PartSignature


class DedupFeedbackRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _canonical(id_a: int, id_b: int) -> tuple[int, int]:
        return (min(id_a, id_b), max(id_a, id_b))

    def record_merge(
        self,
        kept_id: int,
        removed_id: int,
        score: float,
        reasons: list[str],
        sig_a: PartSignature | None,
        sig_b: PartSignature | None,
        name_a: str,
        name_b: str,
    ) -> None:
        a, b = self._canonical(kept_id, removed_id)
        self._upsert(a, b, "merged", score, reasons, sig_a, sig_b, name_a, name_b)

    def record_not_duplicate(
        self,
        id_a: int,
        id_b: int,
        score: float,
        reasons: list[str],
        sig_a: PartSignature | None,
        sig_b: PartSignature | None,
        name_a: str,
        name_b: str,
    ) -> None:
        a, b = self._canonical(id_a, id_b)
        self._upsert(a, b, "not_duplicate", score, reasons, sig_a, sig_b, name_a, name_b)

    def list_suppressed_pairs(self) -> set[tuple[int, int]]:
        """Return all pairs marked as not_duplicate (canonical ordering)."""
        rows = self.db.query_all(
            "SELECT part_id_a, part_id_b FROM dedup_feedback WHERE decision = 'not_duplicate'"
        )
        return {(row["part_id_a"], row["part_id_b"]) for row in rows}

    def is_suppressed(self, id_a: int, id_b: int) -> bool:
        a, b = self._canonical(id_a, id_b)
        row = self.db.query_one(
            "SELECT 1 FROM dedup_feedback WHERE part_id_a = ? AND part_id_b = ? AND decision = 'not_duplicate'",
            (a, b),
        )
        return row is not None

    def _upsert(
        self,
        id_a: int,
        id_b: int,
        decision: str,
        score: float,
        reasons: list[str],
        sig_a: PartSignature | None,
        sig_b: PartSignature | None,
        name_a: str,
        name_b: str,
    ) -> None:
        sig_json_a = json.dumps(asdict(sig_a)) if sig_a else None
        sig_json_b = json.dumps(asdict(sig_b)) if sig_b else None
        self.db.execute(
            """INSERT INTO dedup_feedback
                (part_id_a, part_id_b, decision, score, reasons_json,
                 sig_snapshot_a, sig_snapshot_b, name_a, name_b, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(part_id_a, part_id_b)
               DO UPDATE SET decision = excluded.decision,
                             score = excluded.score,
                             reasons_json = excluded.reasons_json,
                             sig_snapshot_a = excluded.sig_snapshot_a,
                             sig_snapshot_b = excluded.sig_snapshot_b,
                             name_a = excluded.name_a,
                             name_b = excluded.name_b,
                             created_at = excluded.created_at
            """,
            (
                id_a, id_b, decision, score,
                json.dumps(reasons),
                sig_json_a, sig_json_b,
                name_a, name_b,
                utc_now_iso(),
            ),
        )
