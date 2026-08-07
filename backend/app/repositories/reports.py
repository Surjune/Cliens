"""Persistence for generated reports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.models import Report

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReportRecord:
    """A stored report."""

    id: uuid.UUID
    score_id: uuid.UUID
    content: str
    prompt_version: str
    model_name: str
    created_at: datetime


class ReportRepository:
    """Reads and writes generated reports."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def get_for_score(
        self, *, score_id: uuid.UUID, prompt_version: str, model_name: str
    ) -> ReportRecord | None:
        """Find an existing report for a score, prompt version and model.

        Reports are cached on all three: regenerating the same score with the same
        prompt and model should return the stored text rather than spending another
        Gemini call and risking a differently worded answer.
        """
        statement = (
            select(Report)
            .where(
                Report.score_id == score_id,
                Report.prompt_version == prompt_version,
                Report.model_name == model_name,
            )
            .order_by(Report.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._to_record(row) if row is not None else None

    async def create(
        self, *, score_id: uuid.UUID, content: str, prompt_version: str, model_name: str
    ) -> ReportRecord:
        """Persist a generated report."""
        report = Report(
            score_id=score_id,
            content=content,
            prompt_version=prompt_version,
            model_name=model_name,
        )
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)

        logger.info("report_persisted", report_id=str(report.id), score_id=str(score_id))
        return self._to_record(report)

    @staticmethod
    def _to_record(row: Report) -> ReportRecord:
        """Map an ORM row onto the repository's return type."""
        return ReportRecord(
            id=row.id,
            score_id=row.score_id,
            content=row.content,
            prompt_version=row.prompt_version,
            model_name=row.model_name,
            created_at=row.created_at,
        )
