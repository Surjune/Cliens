"""Persistence for computed scores and their breakdowns."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.models import Score

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    """A stored score."""

    id: uuid.UUID
    site_id: uuid.UUID
    input_hash: str
    scenario: str
    crossing_year: int | None
    crossing_year_lower: int | None
    crossing_year_upper: int | None
    confidence_label: str
    breakdown: dict[str, Any]
    damage_model_version: str
    material_model_version: str
    created_at: datetime


class ScoreRepository:
    """Reads and writes computed scores."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def get_by_hash(self, *, input_hash: str, scenario: str) -> ScoreRecord | None:
        """Find an existing score for identical inputs.

        This is what makes ``/score`` idempotent: the same site, materials and
        model versions return the stored row rather than a recomputation that
        could differ by a floating-point hair.
        """
        statement = select(Score).where(Score.input_hash == input_hash, Score.scenario == scenario)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._to_record(row) if row is not None else None

    async def get(self, score_id: uuid.UUID) -> ScoreRecord | None:
        """Fetch one score by id."""
        row = (
            await self._session.execute(select(Score).where(Score.id == score_id))
        ).scalar_one_or_none()
        return self._to_record(row) if row is not None else None

    async def create(
        self,
        *,
        site_id: uuid.UUID,
        input_hash: str,
        scenario: str,
        crossing_year: int | None,
        crossing_year_lower: int | None,
        crossing_year_upper: int | None,
        confidence_label: str,
        breakdown: dict[str, Any],
        damage_model_version: str,
        material_model_version: str,
    ) -> ScoreRecord:
        """Persist a computed score and return it as stored."""
        score = Score(
            site_id=site_id,
            input_hash=input_hash,
            scenario=scenario,
            crossing_year=crossing_year,
            crossing_year_lower=crossing_year_lower,
            crossing_year_upper=crossing_year_upper,
            confidence_label=confidence_label,
            breakdown=breakdown,
            damage_model_version=damage_model_version,
            material_model_version=material_model_version,
        )
        self._session.add(score)
        # Flush rather than commit: the session dependency owns the transaction.
        await self._session.flush()
        await self._session.refresh(score)

        logger.info(
            "score_persisted",
            score_id=str(score.id),
            scenario=scenario,
            crossing_year=crossing_year,
        )
        return self._to_record(score)

    @staticmethod
    def _to_record(row: Score) -> ScoreRecord:
        """Map an ORM row onto the repository's return type."""
        return ScoreRecord(
            id=row.id,
            site_id=row.site_id,
            input_hash=row.input_hash,
            scenario=row.scenario,
            crossing_year=row.crossing_year,
            crossing_year_lower=row.crossing_year_lower,
            crossing_year_upper=row.crossing_year_upper,
            confidence_label=row.confidence_label,
            breakdown=row.breakdown,
            damage_model_version=row.damage_model_version,
            material_model_version=row.material_model_version,
            created_at=row.created_at,
        )
