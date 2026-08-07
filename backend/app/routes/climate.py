"""Climate risk profile endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core import constants
from app.routes.dependencies import ClimateServiceDep
from app.schemas.climate import ClimateProfile
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/climate", tags=["climate"])


@router.get(
    "/profile",
    response_model=ClimateProfile,
    summary="Climate risk profile for a location",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "Earth Engine failed or returned unusable data.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Earth Engine credentials are not configured.",
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "model": ErrorResponse,
            "description": "Earth Engine did not respond within its budget.",
        },
    },
)
async def get_climate_profile(
    service: ClimateServiceDep,
    longitude: Annotated[float, Query(ge=constants.MIN_LONGITUDE, le=constants.MAX_LONGITUDE)],
    latitude: Annotated[float, Query(ge=constants.MIN_LATITUDE, le=constants.MAX_LATITUDE)],
) -> ClimateProfile:
    """Return CMIP6 projections and IMD historical context for a point.

    Responses are cached against the rounded coordinates and the horizon, so a
    repeat request replays the same upstream data rather than re-querying it.
    """
    return await service.get_profile(longitude=longitude, latitude=latitude)
