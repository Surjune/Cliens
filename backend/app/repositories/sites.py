"""Persistence for building sites, including PostGIS geometry writes and centroid reads.

This is the only module that issues spatial SQL for sites. It returns plain
dataclasses rather than ORM instances so that nothing above the repository layer
can trigger a lazy load — a query firing from inside a service would violate the
layering in CLAUDE.md in a way that is easy to miss in review.

Every statement is parameterised. Geometry arrives as a GeoJSON string and is
converted by PostGIS, so no client value is ever interpolated into SQL text.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import constants
from app.core.logging import get_logger
from app.repositories.models import Site

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PolygonMeasurement:
    """Geometric facts PostGIS derived from a candidate polygon.

    Attributes:
        area_sq_m: Area in square metres, computed on the geography type so it
            accounts for the curvature of the earth rather than treating degrees
            as a planar unit.
        centroid_longitude: Centroid longitude in WGS84.
        centroid_latitude: Centroid latitude in WGS84.
        is_valid: PostGIS's own validity verdict (``ST_IsValid``).
    """

    area_sq_m: float
    centroid_longitude: float
    centroid_latitude: float
    is_valid: bool


@dataclass(frozen=True, slots=True)
class SiteRecord:
    """A stored site, fully materialised.

    ``geometry`` is a GeoJSON mapping rather than a WKB element so that callers
    never need PostGIS types to read it.
    """

    id: uuid.UUID
    geometry: dict[str, Any]
    area_sq_ft: float
    centroid_longitude: float
    centroid_latitude: float
    label: str | None
    created_at: datetime


class SiteRepository:
    """Reads and writes building sites."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def measure_polygon(self, geometry: dict[str, Any]) -> PolygonMeasurement:
        """Ask PostGIS for the area, centroid and validity of a candidate polygon.

        Done before insertion so the service can reject an out-of-bounds footprint
        without writing anything, and so area is computed by the same engine that
        will store the geometry.

        Args:
            geometry: A GeoJSON Polygon mapping.

        Returns:
            The measurement. ``is_valid`` false means PostGIS would reject or
            mis-handle this geometry; the caller decides what to do about it.
        """
        geojson = json.dumps(geometry)

        # ST_GeomFromGeoJSON assumes EPSG:4326 per the GeoJSON spec; SetSRID makes
        # that explicit so the geography cast below cannot silently assume another.
        parsed = func.ST_SetSRID(func.ST_GeomFromGeoJSON(geojson), constants.WGS84_SRID)

        statement = select(
            # Casting to geography yields square METRES on the ellipsoid. Computing
            # ST_Area on the geometry type instead would return square degrees,
            # which is meaningless as an area.
            func.ST_Area(
                func.cast(parsed, Geography(geometry_type="POLYGON", srid=constants.WGS84_SRID))
            ).label("area_sq_m"),
            func.ST_X(func.ST_Centroid(parsed)).label("centroid_longitude"),
            func.ST_Y(func.ST_Centroid(parsed)).label("centroid_latitude"),
            func.ST_IsValid(parsed).label("is_valid"),
        )

        row = (await self._session.execute(statement)).one()
        return PolygonMeasurement(
            area_sq_m=float(row.area_sq_m),
            centroid_longitude=float(row.centroid_longitude),
            centroid_latitude=float(row.centroid_latitude),
            is_valid=bool(row.is_valid),
        )

    async def create(
        self,
        *,
        geometry: dict[str, Any],
        area_sq_ft: float,
        centroid_longitude: float,
        centroid_latitude: float,
        label: str | None,
    ) -> SiteRecord:
        """Insert a site and return it as stored.

        Args:
            geometry: GeoJSON Polygon mapping, already validated by the service.
            area_sq_ft: Server-computed area. Never a client-supplied value.
            centroid_longitude: Server-computed centroid longitude.
            centroid_latitude: Server-computed centroid latitude.
            label: Optional user-supplied name.
        """
        site = Site(
            geometry=func.ST_SetSRID(
                func.ST_GeomFromGeoJSON(json.dumps(geometry)), constants.WGS84_SRID
            ),
            area_sq_ft=area_sq_ft,
            centroid_longitude=centroid_longitude,
            centroid_latitude=centroid_latitude,
            label=label,
        )
        self._session.add(site)
        # Flush rather than commit: the session dependency owns the transaction, so
        # a later failure in the same request still rolls this back.
        await self._session.flush()

        logger.info(
            "site_created",
            site_id=str(site.id),
            area_sq_ft=round(area_sq_ft, 2),
            centroid=(round(centroid_longitude, 5), round(centroid_latitude, 5)),
        )

        stored = await self.get(site.id)
        if stored is None:  # pragma: no cover — impossible directly after a flush
            raise RuntimeError(f"site {site.id} vanished immediately after insert")
        return stored

    async def get(self, site_id: uuid.UUID) -> SiteRecord | None:
        """Fetch one site by id, or ``None`` if it does not exist."""
        statement = select(
            Site.id,
            # ST_AsGeoJSON returns a JSON string; parsing it here means callers
            # never handle PostGIS binary types.
            func.ST_AsGeoJSON(Site.geometry).label("geometry"),
            Site.area_sq_ft,
            Site.centroid_longitude,
            Site.centroid_latitude,
            Site.label,
            Site.created_at,
        ).where(Site.id == site_id)

        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None

        return SiteRecord(
            id=row.id,
            geometry=json.loads(row.geometry),
            area_sq_ft=row.area_sq_ft,
            centroid_longitude=row.centroid_longitude,
            centroid_latitude=row.centroid_latitude,
            label=row.label,
            created_at=row.created_at,
        )
