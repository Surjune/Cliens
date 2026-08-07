"""Report generation endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.routes.dependencies import ReportingServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.reports import ReportRequest, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such score."},
    status.HTTP_502_BAD_GATEWAY: {
        "model": ErrorResponse,
        "description": "Gemini failed or returned nothing usable.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Gemini is not configured.",
    },
}


@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a plain-English report for a score",
    responses=REPORT_ERROR_RESPONSES,
)
async def create_report(request: ReportRequest, service: ReportingServiceDep) -> ReportResponse:
    """Turn a score breakdown into readable prose.

    The model receives only the computed breakdown and is instructed not to
    introduce any figure absent from it. Repeat requests return the stored report
    rather than regenerating it.
    """
    return await service.generate(score_id=request.score_id)
