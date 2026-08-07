"""Unit tests for the site service, isolated from the database.

The repository is stubbed here, which keeps these tests fast and lets the defensive
branches be reached directly — a PostGIS-rejected geometry cannot be produced
through the HTTP API, because shapely rejects it first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.exceptions import InvalidGeometryError, ResourceNotFoundError
from app.repositories.sites import PolygonMeasurement, SiteRecord
from app.schemas.common import PolygonGeometry
from app.schemas.sites import SiteCreateRequest
from app.services.sites import SiteService

VALID_RING = [
    [80.27, 13.01],
    [80.2704, 13.01],
    [80.2704, 13.0104],
    [80.27, 13.0104],
    [80.27, 13.01],
]


class StubSiteRepository:
    """A repository that returns whatever the test tells it to.

    Deliberately not a mock library double: an explicit stub makes the contract the
    service depends on visible in one place.
    """

    def __init__(
        self,
        *,
        measurement: PolygonMeasurement | None = None,
        record: SiteRecord | None = None,
    ) -> None:
        self.measurement = measurement or PolygonMeasurement(
            area_sq_m=1_950.0,
            centroid_longitude=80.2702,
            centroid_latitude=13.0102,
            is_valid=True,
        )
        self.record = record
        self.created_with: dict[str, Any] | None = None

    async def measure_polygon(self, geometry: dict[str, Any]) -> PolygonMeasurement:
        return self.measurement

    async def create(
        self,
        **kwargs: Any,  # noqa: ANN401 — mirrors the repository's keyword-only signature
    ) -> SiteRecord:
        self.created_with = kwargs
        return SiteRecord(
            id=uuid.uuid4(),
            geometry={"type": "Polygon", "coordinates": [VALID_RING]},
            area_sq_ft=kwargs["area_sq_ft"],
            centroid_longitude=kwargs["centroid_longitude"],
            centroid_latitude=kwargs["centroid_latitude"],
            label=kwargs["label"],
            created_at=datetime.now(UTC),
        )

    async def get(self, site_id: uuid.UUID) -> SiteRecord | None:
        return self.record


def build_service(repository: StubSiteRepository) -> SiteService:
    """Wire the service to a stub repository."""
    return SiteService(repository)  # type: ignore[arg-type]  # structural stand-in


def request_for(ring: list[list[float]]) -> SiteCreateRequest:
    """Build a create request from a raw ring."""
    return SiteCreateRequest(
        geometry=PolygonGeometry.model_validate({"type": "Polygon", "coordinates": [ring]}),
        label=None,
    )


class TestAreaIsServerComputed:
    """The client never supplies the area its score is based on."""

    async def test_converts_the_postgis_area_from_square_metres(self) -> None:
        repository = StubSiteRepository()
        service = build_service(repository)

        response = await service.create_site(request_for(VALID_RING))

        # 1,950 sq m is about 20,990 sq ft.
        assert response.area_sq_ft == pytest.approx(20_989.6, rel=1e-3)
        assert repository.created_with is not None
        assert repository.created_with["area_sq_ft"] == response.area_sq_ft

    async def test_passes_the_postgis_centroid_through_unchanged(self) -> None:
        repository = StubSiteRepository()
        service = build_service(repository)

        response = await service.create_site(request_for(VALID_RING))

        assert response.centroid.longitude == 80.2702
        assert response.centroid.latitude == 13.0102


class TestDefensiveBranches:
    """Paths that the HTTP API cannot reach, but that must still be correct."""

    async def test_rejects_geometry_postgis_considers_invalid(self) -> None:
        """shapely and PostGIS share GEOS; disagreement must not be stored."""
        repository = StubSiteRepository(
            measurement=PolygonMeasurement(
                area_sq_m=1_950.0,
                centroid_longitude=80.27,
                centroid_latitude=13.01,
                is_valid=False,
            )
        )
        service = build_service(repository)

        with pytest.raises(InvalidGeometryError) as caught:
            await service.create_site(request_for(VALID_RING))

        assert caught.value.details["reason"] == "postgis_rejected_geometry"
        assert repository.created_with is None  # nothing was written

    async def test_rejects_a_ring_that_encloses_no_area(self) -> None:
        """Four coincident points form a valid-but-empty polygon."""
        degenerate = [[80.27, 13.01]] * 4
        service = build_service(StubSiteRepository())

        with pytest.raises(InvalidGeometryError) as caught:
            await service.create_site(request_for(degenerate))

        assert caught.value.details["reason"] in {"empty_polygon", "self_intersecting"}

    async def test_area_below_the_minimum_is_rejected_before_any_write(self) -> None:
        repository = StubSiteRepository(
            measurement=PolygonMeasurement(
                area_sq_m=1.0,  # about 10 sq ft, under the 100 sq ft floor
                centroid_longitude=80.27,
                centroid_latitude=13.01,
                is_valid=True,
            )
        )
        service = build_service(repository)

        with pytest.raises(InvalidGeometryError, match="too small"):
            await service.create_site(request_for(VALID_RING))

        assert repository.created_with is None


class TestGetSite:
    """Retrieval maps a missing row onto a typed error, not None."""

    async def test_raises_not_found_for_an_unknown_id(self) -> None:
        service = build_service(StubSiteRepository(record=None))
        site_id = uuid.uuid4()

        with pytest.raises(ResourceNotFoundError) as caught:
            await service.get_site(site_id)

        assert caught.value.details["site_id"] == str(site_id)

    async def test_returns_a_stored_site(self) -> None:
        record = SiteRecord(
            id=uuid.uuid4(),
            geometry={"type": "Polygon", "coordinates": [VALID_RING]},
            area_sq_ft=2_000.0,
            centroid_longitude=80.2702,
            centroid_latitude=13.0102,
            label="Stored",
            created_at=datetime.now(UTC),
        )
        service = build_service(StubSiteRepository(record=record))

        response = await service.get_site(record.id)

        assert response.id == record.id
        assert response.label == "Stored"
        assert response.area_sq_ft == 2_000.0
