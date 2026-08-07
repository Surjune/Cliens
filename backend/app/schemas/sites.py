"""Site creation and retrieval schemas, including validated polygon geometry.

Area is deliberately absent from the request. The frontend computes an area with
turf.js for immediate on-map feedback, but the authoritative figure is computed by
PostGIS from the stored geometry — one source of truth, and a client cannot inflate
or understate the footprint its score is based on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.schemas.common import Centroid, PolygonGeometry, SchemaBase


class SiteCreateRequest(SchemaBase):
    """A building site submitted from the map."""

    geometry: PolygonGeometry = Field(
        description="GeoJSON Polygon of the site boundary, WGS84, [lon, lat] order."
    )
    label: Annotated[str | None, Field(max_length=200)] = Field(
        default=None,
        description="Optional name for this site, shown in the UI.",
    )


class SiteResponse(SchemaBase):
    """A stored building site.

    ``area_sq_ft`` and ``centroid`` are both computed by PostGIS from the geometry,
    never supplied by the client.
    """

    id: uuid.UUID
    geometry: PolygonGeometry
    area_sq_ft: float = Field(
        description="Footprint area computed from the geometry by PostGIS, in square feet."
    )
    centroid: Centroid = Field(
        description="Geometric centre of the polygon; the point used for climate lookups."
    )
    label: str | None
    created_at: datetime
