"""Site submission and retrieval: geometry validation, area computation, persistence.

Validation happens in two passes, and both matter:

1. **Schema** (``PolygonGeometry``) — shape, coordinate ranges, ring closure. Cheap,
   and it runs before any business code sees the request.
2. **Semantic** (here, via shapely) — self-intersection and degeneracy. shapely wraps
   GEOS, which is the same library PostGIS uses, so a polygon accepted here is one
   PostGIS will also accept.

Only after both does the polygon reach the database, where PostGIS computes the
authoritative area and centroid.
"""

from __future__ import annotations

import uuid
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import Polygon

from app.core import calculations, constants
from app.core.exceptions import InvalidGeometryError, ResourceNotFoundError
from app.core.logging import get_logger
from app.repositories.sites import SiteRecord, SiteRepository
from app.schemas.common import Centroid, PolygonGeometry
from app.schemas.sites import SiteCreateRequest, SiteResponse

logger = get_logger(__name__)


class SiteService:
    """Business logic for building sites."""

    def __init__(self, repository: SiteRepository) -> None:
        """Bind the service to its repository."""
        self._repository = repository

    async def create_site(self, request: SiteCreateRequest) -> SiteResponse:
        """Validate, measure and store a submitted site.

        Args:
            request: The validated request body.

        Returns:
            The stored site, including the server-computed area and centroid.

        Raises:
            InvalidGeometryError: If the polygon is self-intersecting, degenerate,
                or its footprint falls outside the supported area bounds.
        """
        geometry = request.geometry.model_dump()

        self._assert_geometry_is_well_formed(request.geometry)

        measurement = await self._repository.measure_polygon(geometry)
        if not measurement.is_valid:
            # shapely and PostGIS share GEOS, so reaching here means the two
            # disagreed — worth surfacing rather than storing something PostGIS
            # considers broken.
            raise InvalidGeometryError(
                "The site boundary is not a valid polygon. Redraw it without " "crossing edges.",
                details={"reason": "postgis_rejected_geometry"},
            )

        # PostGIS returns square metres (geography type); the product's unit is
        # square feet.
        area_sq_ft = calculations.sq_metres_to_sq_feet(measurement.area_sq_m)
        self._assert_area_within_bounds(area_sq_ft)

        logger.info(
            "site_submission_validated",
            area_sq_ft=round(area_sq_ft, 2),
            area_sq_m=round(measurement.area_sq_m, 2),
        )

        record = await self._repository.create(
            geometry=geometry,
            area_sq_ft=area_sq_ft,
            centroid_longitude=measurement.centroid_longitude,
            centroid_latitude=measurement.centroid_latitude,
            label=request.label,
        )
        return self._to_response(record)

    async def get_site(self, site_id: uuid.UUID) -> SiteResponse:
        """Fetch a stored site.

        Raises:
            ResourceNotFoundError: If no site has that id.
        """
        record = await self._repository.get(site_id)
        if record is None:
            raise ResourceNotFoundError(
                "No site exists with that id.",
                details={"site_id": str(site_id)},
            )
        return self._to_response(record)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_geometry_is_well_formed(geometry: PolygonGeometry) -> None:
        """Reject polygons GEOS considers invalid.

        Catches the cases a schema cannot: a bow-tie ring that crosses itself, and
        rings whose points are collinear or coincident so they enclose no area.

        Raises:
            InvalidGeometryError: If the ring is not a usable polygon.
        """
        ring = geometry.exterior_ring
        try:
            polygon = Polygon(ring)
            is_valid = polygon.is_valid
            is_empty = polygon.is_empty
        except (GEOSException, ValueError) as error:
            # A malformed ring can make GEOS raise rather than return False.
            raise InvalidGeometryError(
                "The site boundary could not be interpreted as a polygon.",
                details={"reason": "unparseable_ring"},
            ) from error

        if is_empty:
            raise InvalidGeometryError(
                "The site boundary encloses no area.",
                details={"reason": "empty_polygon"},
            )
        if not is_valid:
            raise InvalidGeometryError(
                "The site boundary crosses itself. Redraw it as a simple outline.",
                details={"reason": "self_intersecting"},
            )

    @staticmethod
    def _assert_area_within_bounds(area_sq_ft: float) -> None:
        """Reject footprints outside the range the scoring model supports.

        The same bounds are enforced by a CHECK constraint on the table; this
        produces a clear client-facing error instead of a database integrity error.

        Raises:
            InvalidGeometryError: If the footprint is too small or too large.
        """
        if area_sq_ft < constants.MIN_FLOOR_AREA_SQ_FT:
            raise InvalidGeometryError(
                f"The site is too small to score. The minimum supported footprint "
                f"is {constants.MIN_FLOOR_AREA_SQ_FT:,.0f} sq ft.",
                details={
                    "area_sq_ft": round(area_sq_ft, 2),
                    "minimum_sq_ft": constants.MIN_FLOOR_AREA_SQ_FT,
                },
            )
        if area_sq_ft > constants.MAX_FLOOR_AREA_SQ_FT:
            raise InvalidGeometryError(
                f"The site is too large to score. The maximum supported footprint "
                f"is {constants.MAX_FLOOR_AREA_SQ_FT:,.0f} sq ft.",
                details={
                    "area_sq_ft": round(area_sq_ft, 2),
                    "maximum_sq_ft": constants.MAX_FLOOR_AREA_SQ_FT,
                },
            )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _to_response(record: SiteRecord) -> SiteResponse:
        """Map a stored record onto the API response shape."""
        geometry: dict[str, Any] = record.geometry
        return SiteResponse(
            id=record.id,
            geometry=PolygonGeometry.model_validate(geometry),
            area_sq_ft=record.area_sq_ft,
            centroid=Centroid(
                longitude=record.centroid_longitude,
                latitude=record.centroid_latitude,
            ),
            label=record.label,
            created_at=record.created_at,
        )
