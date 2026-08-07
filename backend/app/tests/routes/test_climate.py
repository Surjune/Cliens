"""Integration tests for the climate profile endpoint.

The most important case here is the unconfigured one. With no Earth Engine
credentials the endpoint must fail explicitly and say why — never return a
plausible-looking projection, which in a permit context would be worse than an
outage.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


class TestUnconfiguredEarthEngine:
    """The default state of a clean clone, so it must behave well."""

    async def test_returns_503_with_an_actionable_error(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/climate/profile", params={"longitude": 80.27, "latitude": 13.01}
        )

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "EXTERNAL_SERVICE_UNCONFIGURED"
        assert error["details"]["service"] == "earth_engine"

    async def test_names_the_variables_that_need_setting(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/climate/profile", params={"longitude": 80.27, "latitude": 13.01}
        )

        missing = response.json()["error"]["details"]["missing"]
        assert "EARTH_ENGINE_PROJECT_ID" in missing

    async def test_does_not_return_a_profile_body(self, client: AsyncClient) -> None:
        """The failure must not be accompanied by partial or placeholder data."""
        response = await client.get(
            "/api/climate/profile", params={"longitude": 80.27, "latitude": 13.01}
        )

        body = response.json()
        assert "projections" not in body
        assert "centroid" not in body

    async def test_carries_a_correlation_id(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/climate/profile", params={"longitude": 80.27, "latitude": 13.01}
        )

        assert response.json()["error"]["request_id"]


class TestParameterValidation:
    """Coordinates are untrusted input here just as they are on /sites."""

    @pytest.mark.parametrize(
        ("longitude", "latitude"),
        [(181.0, 13.0), (-181.0, 13.0), (80.0, 91.0), (80.0, -91.0)],
    )
    async def test_rejects_out_of_range_coordinates(
        self, client: AsyncClient, longitude: float, latitude: float
    ) -> None:
        response = await client.get(
            "/api/climate/profile", params={"longitude": longitude, "latitude": latitude}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_missing_coordinates(self, client: AsyncClient) -> None:
        response = await client.get("/api/climate/profile")

        assert response.status_code == 422

    async def test_rejects_non_numeric_coordinates(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/climate/profile", params={"longitude": "east", "latitude": "north"}
        )

        assert response.status_code == 422
