"""Score and re-score (prove) endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.routes.dependencies import ScoringServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.scoring import ProveResponse, ScoreRequest, ScoreResponse

router = APIRouter(prefix="/score", tags=["scoring"])

SCORING_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such site."},
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "A material code is unknown or invalid for its component.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Earth Engine is unconfigured, or the ML artifacts are missing.",
    },
}


@router.post(
    "",
    response_model=ScoreResponse,
    summary="Compute the Climate Lien Score for a site",
    responses=SCORING_ERROR_RESPONSES,
)
async def create_score(request: ScoreRequest, service: ScoringServiceDep) -> ScoreResponse:
    """Score a site with the submitted materials.

    Deterministic: identical inputs return the identical stored score, including
    the model versions that produced it.
    """
    return await service.score(site_id=request.site_id, selection=request.materials)


@router.post(
    "/prove",
    response_model=ProveResponse,
    summary="Score, recommend better materials, and re-score with them applied",
    responses=SCORING_ERROR_RESPONSES,
)
async def prove(request: ScoreRequest, service: ScoringServiceDep) -> ProveResponse:
    """Return the baseline and improved scores side by side.

    Both are computed by the same engine from the same cached climate profile, so
    the two crossing years are directly comparable.
    """
    return await service.prove(site_id=request.site_id, selection=request.materials)
