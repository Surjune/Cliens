"""Downloadable client report endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import Response

from app.routes.dependencies import ScoringServiceDep
from app.routes.scoring import to_selection
from app.schemas.common import ErrorResponse
from app.schemas.scoring import ScoreRequest
from app.services.report_pdf import build_report_pdf

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "The request did not match the expected shape.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "No measured climate profile for that district, or models not trained.",
    },
}


@router.post(
    "",
    summary="Download the client report as a PDF",
    responses={
        status.HTTP_200_OK: {
            "content": {"application/pdf": {}},
            "description": "The report.",
        },
        **REPORT_ERRORS,
    },
)
async def download_report(request: ScoreRequest, service: ScoringServiceDep) -> Response:
    """Score the district and return the result as a downloadable PDF.

    Takes the same body as ``POST /score`` and re-scores rather than reading a
    stored result. Scoring is deterministic and inexpensive, so this avoids
    persisting anything and guarantees the document matches the current engine
    rather than a stale row.
    """
    comparison = service.compare(
        district=request.district,
        proposed=to_selection(request.materials),
        situation=request.element_situation,
    )
    pdf = build_report_pdf(comparison, evaluated_own_materials=request.materials is not None)

    filename = f"building-quality-score-{comparison.district.lower()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
