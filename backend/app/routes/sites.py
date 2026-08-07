"""Site submission and retrieval endpoints.

Thin by design: parse, call one service, return. No branching on business rules,
no arithmetic, no database access.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status

from app.routes.dependencies import SiteServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.sites import SiteCreateRequest, SiteResponse

router = APIRouter(prefix="/sites", tags=["sites"])


@router.post(
    "",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a building site",
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "The polygon is malformed, self-intersecting, or outside "
            "the supported footprint range.",
        }
    },
)
async def create_site(request: SiteCreateRequest, service: SiteServiceDep) -> SiteResponse:
    """Store a site boundary and return it with its computed area and centroid.

    The area is computed by PostGIS from the submitted geometry; any area the
    client calculated for display is not accepted or trusted.
    """
    return await service.create_site(request)


@router.get(
    "/{site_id}",
    response_model=SiteResponse,
    summary="Fetch a stored site",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No site exists with that id.",
        }
    },
)
async def get_site(
    site_id: Annotated[
        uuid.UUID, Path(description="Identifier returned when the site was created.")
    ],
    service: SiteServiceDep,
) -> SiteResponse:
    """Return a previously submitted site."""
    return await service.get_site(site_id)
