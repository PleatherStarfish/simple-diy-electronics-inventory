from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz

from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.common import normalize_text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchCandidate:
    part_id: int
    text: str
    source: str


MIN_SCORE = 55.0
SOURCE_WEIGHTS = {"name": 1.0, "alias": 1.0, "sku": 0.9, "category": 0.6, "package": 0.5}


class SearchService:
    """In-memory fuzzy search over canonical names, aliases, categories, and SKUs."""

    def __init__(self, part_repo: PartRepository) -> None:
        self.part_repo = part_repo
        self._candidates: list[SearchCandidate] = []

    def rebuild(self) -> None:
        parts = self.part_repo.list_parts()
        aliases = self.part_repo.list_all_aliases()
        candidates: list[SearchCandidate] = []
        for part in parts:
            candidates.append(SearchCandidate(part_id=part.id, text=normalize_text(part.name), source="name"))
            if part.category:
                candidates.append(SearchCandidate(part_id=part.id, text=normalize_text(part.category), source="category"))
            if part.supplier_sku:
                candidates.append(SearchCandidate(part_id=part.id, text=normalize_text(part.supplier_sku), source="sku"))
            if part.default_package:
                candidates.append(SearchCandidate(part_id=part.id, text=normalize_text(part.default_package), source="package"))
        for alias in aliases:
            candidates.append(SearchCandidate(part_id=alias.part_id, text=alias.normalized_alias, source="alias"))
        self._candidates = candidates
        logger.info("Search index rebuilt with %s candidates", len(candidates))

    def search(self, query: str, limit: int = 10) -> list[int]:
        normalized = normalize_text(query)
        if not normalized:
            return [summary.part_id for summary in self.part_repo.list_inventory_summaries()[:limit]]

        scores: dict[int, float] = {}
        for candidate in self._candidates:
            base = fuzz.WRatio(normalized, candidate.text)
            if normalized == candidate.text:
                base += 40
            elif normalized in candidate.text:
                base += 20
            elif all(token in candidate.text for token in normalized.split()):
                base += 10
            weight = SOURCE_WEIGHTS.get(candidate.source, 0.7)
            weighted = base * weight
            if weighted < MIN_SCORE:
                continue
            current = scores.get(candidate.part_id, 0.0)
            if weighted > current:
                scores[candidate.part_id] = weighted

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [part_id for part_id, _score in ranked[:limit]]
