"""Turns a score breakdown into a plain-English report via the Gemini client.

The model is given the score payload and nothing else, and the prompt forbids it
from introducing any figure not present there. That is the whole design: the
numbers are computed by the deterministic engine, and the model's only job is to
put them into sentences.

Reports are stored against the score, the prompt version and the model name, so
asking twice returns the same text rather than spending another API call on a
differently worded answer.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_logger
from app.external.gemini import GeminiClient
from app.external.prompts import PROMPT_VERSION, build_report_prompt
from app.repositories.reports import ReportRecord, ReportRepository
from app.repositories.scores import ScoreRecord, ScoreRepository
from app.schemas.reports import ReportResponse

logger = get_logger(__name__)


class ReportingService:
    """Generates and stores plain-English reports."""

    def __init__(
        self,
        *,
        reports: ReportRepository,
        scores: ScoreRepository,
        gemini: GeminiClient,
    ) -> None:
        """Bind the service to its repositories and client."""
        self._reports = reports
        self._scores = scores
        self._gemini = gemini

    async def generate(self, *, score_id: uuid.UUID) -> ReportResponse:
        """Produce a report for a computed score.

        Raises:
            ResourceNotFoundError: If the score does not exist.
            ExternalServiceUnconfiguredError: If no Gemini key is configured.
            ExternalServiceError: If Gemini failed or returned nothing usable.
        """
        score = await self._scores.get(score_id)
        if score is None:
            raise ResourceNotFoundError(
                "No score exists with that id.", details={"score_id": str(score_id)}
            )

        existing = await self._reports.get_for_score(
            score_id=score_id,
            prompt_version=PROMPT_VERSION,
            model_name=self._gemini.model_name,
        )
        if existing is not None:
            logger.info("report_served_from_store", score_id=str(score_id))
            return self._to_response(existing)

        prompt = build_report_prompt(self._payload_for(score))
        content = await self._gemini.generate(prompt)

        record = await self._reports.create(
            score_id=score_id,
            content=content,
            prompt_version=PROMPT_VERSION,
            model_name=self._gemini.model_name,
        )
        logger.info(
            "report_generated",
            score_id=str(score_id),
            prompt_version=PROMPT_VERSION,
            model=self._gemini.model_name,
        )
        return self._to_response(record)

    @staticmethod
    def _payload_for(score: ScoreRecord) -> dict[str, Any]:
        """Assemble exactly what the model is allowed to see.

        Deliberately narrow. The per-year table is summarised rather than passed
        in full: 31 rows of projections would crowd out the parts that matter and
        invite the model to quote individual years it was not asked about.
        """
        breakdown = score.breakdown
        years = breakdown.get("years", [])
        return {
            "crossing_year": score.crossing_year,
            "crossing_year_range": {
                "earliest": score.crossing_year_lower,
                "latest": score.crossing_year_upper,
            },
            "confidence": score.confidence_label,
            "survives_horizon": score.crossing_year is None,
            "uninsurable_damage_threshold": breakdown.get("uninsurable_damage_threshold"),
            "area_sq_ft": breakdown.get("area_sq_ft"),
            "materials": breakdown.get("materials", []),
            "component_breakdown": breakdown.get("components", []),
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "any_year_exceeds_survivability_limit": any(
                year.get("exceeds_survivability_limit") for year in years
            ),
        }

    @staticmethod
    def _to_response(record: ReportRecord) -> ReportResponse:
        """Map a stored report onto the API response shape."""
        return ReportResponse(
            id=record.id,
            score_id=record.score_id,
            content=record.content,
            prompt_version=record.prompt_version,
            model_name=record.model_name,
            created_at=record.created_at,
        )
