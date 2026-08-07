"""Tests for the IMD client, including its offline fallback.

The fallback is the interesting part: IMD's endpoint is undocumented and often
unreachable, so the behaviour when it fails is the behaviour users will usually get.
The rule under test throughout is that missing data is reported as missing, never
substituted.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core import calculations, constants
from app.core.config import Settings
from app.external.imd import IMDClient

# Inside the bundled Chennai bounding box.
CHENNAI_LON = 80.27
CHENNAI_LAT = 13.01

# Central London — deliberately outside every bundled district.
UNCOVERED_LON = -0.12
UNCOVERED_LAT = 51.50


@pytest.fixture
def imd_client(settings: Settings) -> IMDClient:
    """A client pointed at a test host, so respx can intercept it."""
    return IMDClient(settings.model_copy(update={"imd_api_base_url": "https://imd.test"}))


@pytest.fixture(autouse=True)
def _no_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff so failure-path tests do not sleep."""
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_MAX_BACKOFF_SECONDS", 0.0)


LIVE_PAYLOAD = {
    "district": "Chennai",
    "state": "Tamil Nadu",
    "cyclone_events": 12,
    "strongest_wind_kmph": 130.0,
    "max_daily_rainfall_mm": 494.0,
    "period_start_year": 1990,
    "period_end_year": 2024,
}


class TestLiveEndpoint:
    """When IMD answers, its data is used and converted correctly."""

    @respx.mock
    async def test_uses_the_live_response(self, imd_client: IMDClient) -> None:
        respx.get("https://imd.test/districts/history").mock(
            return_value=httpx.Response(200, json=LIVE_PAYLOAD)
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.district == "Chennai"
        assert history.from_fallback is False
        assert history.cyclone_events_recorded == 12

    @respx.mock
    async def test_converts_wind_from_kmph_to_ms(self, imd_client: IMDClient) -> None:
        """IMD publishes km/h; every internal wind value is m/s."""
        respx.get("https://imd.test/districts/history").mock(
            return_value=httpx.Response(200, json=LIVE_PAYLOAD)
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.strongest_recorded_wind_ms == pytest.approx(calculations.kmph_to_ms(130.0))
        # 130 km/h is about 36 m/s — a sanity check that the conversion is the
        # right way round, which a round-trip assertion alone would not catch.
        assert 35.0 < history.strongest_recorded_wind_ms < 37.0


class TestFallbackBehaviour:
    """The path users hit most often, given the endpoint's reliability."""

    @respx.mock
    async def test_falls_back_when_the_endpoint_is_unreachable(self, imd_client: IMDClient) -> None:
        respx.get("https://imd.test/districts/history").mock(
            side_effect=httpx.ConnectError("no route")
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.district == "Chennai"
        assert history.from_fallback is True

    @respx.mock
    async def test_falls_back_on_a_server_error(self, imd_client: IMDClient) -> None:
        respx.get("https://imd.test/districts/history").mock(return_value=httpx.Response(500))

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.from_fallback is True

    @respx.mock
    async def test_falls_back_when_the_live_response_is_missing_fields(
        self, imd_client: IMDClient
    ) -> None:
        """A partial record must not be half-populated with defaults."""
        respx.get("https://imd.test/districts/history").mock(
            return_value=httpx.Response(200, json={"district": "Chennai"})
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.from_fallback is True

    @respx.mock
    async def test_falls_back_when_the_endpoint_returns_html(self, imd_client: IMDClient) -> None:
        respx.get("https://imd.test/districts/history").mock(
            return_value=httpx.Response(200, text="<html>maintenance</html>")
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert history.from_fallback is True

    @respx.mock
    async def test_fallback_is_labelled_with_its_provenance(self, imd_client: IMDClient) -> None:
        """A reader must be able to tell bundled data from live data."""
        respx.get("https://imd.test/districts/history").mock(
            side_effect=httpx.ConnectError("no route")
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON, latitude=CHENNAI_LAT
        )

        assert history is not None
        assert "Vardah" in history.source_note


class TestAbsentCoverage:
    """Missing data is reported as missing — never invented."""

    @respx.mock
    async def test_returns_none_outside_every_bundled_district(self, imd_client: IMDClient) -> None:
        respx.get("https://imd.test/districts/history").mock(
            side_effect=httpx.ConnectError("no route")
        )

        history = await imd_client.fetch_district_history(
            longitude=UNCOVERED_LON, latitude=UNCOVERED_LAT
        )

        assert history is None

    @respx.mock
    async def test_does_not_borrow_a_neighbouring_districts_figures(
        self, imd_client: IMDClient
    ) -> None:
        """A point just outside Chennai's box gets nothing, not Chennai's data."""
        respx.get("https://imd.test/districts/history").mock(
            side_effect=httpx.ConnectError("no route")
        )

        history = await imd_client.fetch_district_history(
            longitude=CHENNAI_LON,
            latitude=20.0,  # far north of the Chennai bounding box
        )

        assert history is None
