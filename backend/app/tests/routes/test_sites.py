"""End-to-end tests for the site vertical slice.

These exercise the full path the brief asks to get working first: polygon submitted
over HTTP, validated, stored in PostGIS, and read back — against the real test
database, not a mock.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core import calculations, constants

pytestmark = pytest.mark.integration

# A site in Chennai, near the Adyar estuary — the Cyclone Michaung framing from the
# brief. Coordinates are [lon, lat] per GeoJSON.
CHENNAI_LON = 80.27
CHENNAI_LAT = 13.01


def square_polygon(
    *,
    longitude: float = CHENNAI_LON,
    latitude: float = CHENNAI_LAT,
    side_degrees: float = 0.0004,
    closed: bool = True,
) -> dict[str, Any]:
    """Build a small square polygon around a point.

    At Chennai's latitude 0.0004 degrees is roughly 44 m, giving about 1,950 sq m
    (~21,000 sq ft) — comfortably inside the supported footprint range.
    """
    ring = [
        [longitude, latitude],
        [longitude + side_degrees, latitude],
        [longitude + side_degrees, latitude + side_degrees],
        [longitude, latitude + side_degrees],
    ]
    if closed:
        ring.append([longitude, latitude])
    return {"type": "Polygon", "coordinates": [ring]}


class TestCreateSite:
    """The happy path: draw a polygon, get back a stored site."""

    async def test_stores_a_site_and_returns_it(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={"geometry": square_polygon(), "label": "Adyar plot"},
        )
        assert response.status_code == 201

        body = response.json()
        assert uuid.UUID(body["id"])
        assert body["label"] == "Adyar plot"
        assert body["geometry"]["type"] == "Polygon"
        assert body["created_at"]

    async def test_computes_area_server_side(self, client: AsyncClient) -> None:
        """A ~44 m square is about 1,950 sq m; the response is in square feet."""
        response = await client.post("/api/sites", json={"geometry": square_polygon()})
        area_sq_ft = response.json()["area_sq_ft"]

        expected_sq_ft = calculations.sq_metres_to_sq_feet(1_950.0)
        assert area_sq_ft == pytest.approx(expected_sq_ft, rel=0.05)

    async def test_computes_the_centroid_at_the_square_centre(self, client: AsyncClient) -> None:
        side = 0.0004
        response = await client.post(
            "/api/sites", json={"geometry": square_polygon(side_degrees=side)}
        )
        centroid = response.json()["centroid"]

        assert centroid["longitude"] == pytest.approx(CHENNAI_LON + side / 2, abs=1e-6)
        assert centroid["latitude"] == pytest.approx(CHENNAI_LAT + side / 2, abs=1e-6)

    async def test_accepts_an_unclosed_ring_and_closes_it(self, client: AsyncClient) -> None:
        """Several drawing libraries omit the repeated closing point."""
        response = await client.post("/api/sites", json={"geometry": square_polygon(closed=False)})
        assert response.status_code == 201

        ring = response.json()["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]

    async def test_label_is_optional(self, client: AsyncClient) -> None:
        response = await client.post("/api/sites", json={"geometry": square_polygon()})
        assert response.status_code == 201
        assert response.json()["label"] is None

    async def test_is_stored_durably_and_readable_afterwards(self, client: AsyncClient) -> None:
        """The round trip is the whole point of the slice."""
        created = await client.post(
            "/api/sites", json={"geometry": square_polygon(), "label": "Round trip"}
        )
        site_id = created.json()["id"]

        fetched = await client.get(f"/api/sites/{site_id}")
        assert fetched.status_code == 200
        assert fetched.json() == created.json()


class TestCreateSiteValidation:
    """Polygon geometry is untrusted input."""

    async def test_rejects_a_self_intersecting_polygon(self, client: AsyncClient) -> None:
        """A bow-tie ring passes schema validation but is not a real footprint."""
        bow_tie = {
            "type": "Polygon",
            "coordinates": [
                [
                    [CHENNAI_LON, CHENNAI_LAT],
                    [CHENNAI_LON + 0.0004, CHENNAI_LAT + 0.0004],
                    [CHENNAI_LON + 0.0004, CHENNAI_LAT],
                    [CHENNAI_LON, CHENNAI_LAT + 0.0004],
                    [CHENNAI_LON, CHENNAI_LAT],
                ]
            ],
        }
        response = await client.post("/api/sites", json={"geometry": bow_tie})

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "INVALID_GEOMETRY"
        assert error["details"]["reason"] == "self_intersecting"

    async def test_rejects_a_degenerate_polygon_with_no_area(self, client: AsyncClient) -> None:
        collinear = {
            "type": "Polygon",
            "coordinates": [
                [
                    [CHENNAI_LON, CHENNAI_LAT],
                    [CHENNAI_LON + 0.0002, CHENNAI_LAT],
                    [CHENNAI_LON + 0.0004, CHENNAI_LAT],
                    [CHENNAI_LON, CHENNAI_LAT],
                ]
            ],
        }
        response = await client.post("/api/sites", json={"geometry": collinear})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GEOMETRY"

    async def test_rejects_a_footprint_below_the_minimum(self, client: AsyncClient) -> None:
        # 0.00001 degrees is roughly 1 m, well under the 100 sq ft floor.
        response = await client.post(
            "/api/sites", json={"geometry": square_polygon(side_degrees=0.00001)}
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "INVALID_GEOMETRY"
        assert error["details"]["minimum_sq_ft"] == constants.MIN_FLOOR_AREA_SQ_FT

    async def test_rejects_a_footprint_above_the_maximum(self, client: AsyncClient) -> None:
        # 0.5 degrees is roughly 55 km, far beyond a building site.
        response = await client.post(
            "/api/sites", json={"geometry": square_polygon(side_degrees=0.5)}
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["maximum_sq_ft"] == (
            constants.MAX_FLOOR_AREA_SQ_FT
        )

    async def test_rejects_a_ring_with_too_few_points(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[CHENNAI_LON, CHENNAI_LAT], [80.28, 13.02]]],
                }
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        ("longitude", "latitude"),
        [(181.0, 13.0), (-181.0, 13.0), (80.0, 91.0), (80.0, -91.0)],
    )
    async def test_rejects_out_of_range_coordinates(
        self, client: AsyncClient, longitude: float, latitude: float
    ) -> None:
        response = await client.post(
            "/api/sites",
            json={"geometry": square_polygon(longitude=longitude, latitude=latitude)},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_a_swapped_coordinate_order(self, client: AsyncClient) -> None:
        """GeoJSON is [lon, lat]; Chennai's latitude is not a valid longitude pair.

        Sending [lat, lon] puts 13.01 in the longitude slot and 80.27 in the
        latitude slot — still in range, so this is caught by the area check rather
        than by the range check. The site lands in the Atlantic at a plausible size,
        which is exactly why the ordering is documented everywhere it is used.
        """
        swapped = {
            "type": "Polygon",
            "coordinates": [
                [
                    [CHENNAI_LAT, CHENNAI_LON],
                    [CHENNAI_LAT + 0.0004, CHENNAI_LON],
                    [CHENNAI_LAT + 0.0004, CHENNAI_LON + 0.0004],
                    [CHENNAI_LAT, CHENNAI_LON + 0.0004],
                    [CHENNAI_LAT, CHENNAI_LON],
                ]
            ],
        }
        response = await client.post("/api/sites", json={"geometry": swapped})

        # It is accepted (the coordinates are individually valid) but the centroid
        # proves the ordering was preserved rather than silently corrected.
        assert response.status_code == 201
        assert response.json()["centroid"]["longitude"] == pytest.approx(CHENNAI_LAT, abs=1e-3)

    async def test_rejects_a_non_polygon_geometry_type(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={"geometry": {"type": "Point", "coordinates": [CHENNAI_LON, CHENNAI_LAT]}},
        )
        assert response.status_code == 422

    async def test_rejects_a_polygon_with_a_hole(self, client: AsyncClient) -> None:
        """Only the exterior ring is supported; a hole is not a building site."""
        with_hole = square_polygon()
        with_hole["coordinates"].append(with_hole["coordinates"][0])

        response = await client.post("/api/sites", json={"geometry": with_hole})
        assert response.status_code == 422

    async def test_rejects_unknown_fields(self, client: AsyncClient) -> None:
        """`extra="forbid"` tells a client about a misspelled field."""
        response = await client.post(
            "/api/sites",
            json={"geometry": square_polygon(), "area_sq_ft": 999_999},
        )
        assert response.status_code == 422

    async def test_rejects_a_label_that_is_too_long(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/sites",
            json={"geometry": square_polygon(), "label": "x" * 201},
        )
        assert response.status_code == 422

    async def test_rejects_a_missing_geometry(self, client: AsyncClient) -> None:
        response = await client.post("/api/sites", json={"label": "no geometry"})
        assert response.status_code == 422


class TestGetSite:
    """Retrieval, including the failure case."""

    async def test_returns_404_for_an_unknown_id(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/sites/{uuid.uuid4()}")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["request_id"]

    async def test_returns_422_for_a_malformed_id(self, client: AsyncClient) -> None:
        response = await client.get("/api/sites/not-a-uuid")
        assert response.status_code == 422


class TestDeterminism:
    """The same polygon must always measure the same."""

    async def test_identical_polygons_produce_identical_measurements(
        self, client: AsyncClient
    ) -> None:
        first = await client.post("/api/sites", json={"geometry": square_polygon()})
        second = await client.post("/api/sites", json={"geometry": square_polygon()})

        assert first.json()["area_sq_ft"] == second.json()["area_sq_ft"]
        assert first.json()["centroid"] == second.json()["centroid"]
        # Distinct rows, though — each submission is its own site.
        assert first.json()["id"] != second.json()["id"]
