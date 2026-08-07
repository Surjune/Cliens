"""Tests for the Earth Engine client.

Scope note, stated plainly: the shape of the Earth Engine *query* itself cannot be
verified without credentials and a registered Cloud project. What is tested here is
everything around it — the credential guard, response normalisation, timeout
handling, and the mapping of upstream failures onto typed errors. The query is
exercised through a stand-in ``ee`` module. This gap is recorded in the README's
"Known limitations".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core import constants
from app.core.config import Settings
from app.core.exceptions import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    ExternalServiceUnconfiguredError,
)
from app.external.earth_engine import EarthEngineClient


@pytest.fixture
def configured_settings(settings: Settings, tmp_path: Path) -> Settings:
    """Settings with every Earth Engine credential present."""
    key_file = tmp_path / "service-account.json"
    key_file.write_text("{}", encoding="utf-8")
    return settings.model_copy(
        update={
            "earth_engine_project_id": "test-project",
            "earth_engine_service_account_email": "sa@test-project.iam.gserviceaccount.com",
            "earth_engine_service_account_file": key_file,
        }
    )


def build_records(years: list[int]) -> list[dict[str, Any]]:
    """Build plausible per-(year, model) records for the stand-in Earth Engine."""
    return [
        {
            "year": year,
            "model": model,
            constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE: 310.0,  # kelvin
            constants.EARTH_ENGINE_BAND_PRECIPITATION: 0.002,  # kg m-2 s-1
            constants.EARTH_ENGINE_BAND_WIND_SPEED: 12.0,  # m/s
            constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY: 78.0,  # percent
        }
        for year in years
        for model in constants.EARTH_ENGINE_CMIP6_MODELS
    ]


class TestCredentialGuard:
    """Missing credentials must produce an explicit error, never a fake number."""

    async def test_unconfigured_raises_rather_than_returning_data(self, settings: Settings) -> None:
        client = EarthEngineClient(settings)

        with pytest.raises(ExternalServiceUnconfiguredError) as caught:
            await client.fetch_projections(
                longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
            )

        assert caught.value.http_status == 503
        assert caught.value.service == "earth_engine"

    async def test_error_names_every_missing_variable(self, settings: Settings) -> None:
        """The message has to be actionable, not just "not configured"."""
        client = EarthEngineClient(settings)

        with pytest.raises(ExternalServiceUnconfiguredError) as caught:
            await client.fetch_projections(
                longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
            )

        missing = caught.value.details["missing"]
        assert "EARTH_ENGINE_PROJECT_ID" in missing
        assert "EARTH_ENGINE_SERVICE_ACCOUNT_EMAIL" in missing
        assert "EARTH_ENGINE_SERVICE_ACCOUNT_FILE" in missing

    def test_reports_configured_when_all_three_are_present(
        self, configured_settings: Settings
    ) -> None:
        assert EarthEngineClient(configured_settings).is_configured is True

    async def test_credentials_never_appear_in_the_error(self, settings: Settings) -> None:
        """Error details are returned to clients, so they must stay clean."""
        client = EarthEngineClient(settings)

        with pytest.raises(ExternalServiceUnconfiguredError) as caught:
            await client.fetch_projections(
                longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
            )

        rendered = str(caught.value.details) + caught.value.message
        assert "service-account.json" not in rendered
        assert "iam.gserviceaccount.com" not in rendered


class TestNormalisation:
    """Earth Engine's FeatureCollection is flattened into a cacheable shape."""

    def test_flattens_features_into_records(self, configured_settings: Settings) -> None:
        client = EarthEngineClient(configured_settings)
        raw = {"features": [{"properties": record} for record in build_records([2025, 2026])]}

        result = client._normalise(raw)

        assert result["dataset"] == constants.EARTH_ENGINE_CMIP6_DATASET
        assert result["scenario"] == constants.EARTH_ENGINE_CMIP6_SCENARIO
        assert len(result["records"]) == 2 * len(constants.EARTH_ENGINE_CMIP6_MODELS)

    def test_skips_features_missing_their_year_or_model(
        self, configured_settings: Settings
    ) -> None:
        client = EarthEngineClient(configured_settings)
        raw = {
            "features": [
                {"properties": {"year": 2025, "model": "ACCESS-CM2", "tasmax": 310.0}},
                {"properties": {"tasmax": 310.0}},  # unusable, no year or model
            ]
        }

        result = client._normalise(raw)

        assert len(result["records"]) == 1

    def test_rejects_a_response_with_no_usable_records(self, configured_settings: Settings) -> None:
        """A site outside dataset coverage must fail loudly, not score as zero risk."""
        client = EarthEngineClient(configured_settings)

        with pytest.raises(ExternalServiceError, match="no usable projection records"):
            client._normalise({"features": []})

    @pytest.mark.parametrize("raw", [None, {}, {"unexpected": "shape"}])
    def test_rejects_an_unexpected_response_shape(
        self, configured_settings: Settings, raw: object
    ) -> None:
        client = EarthEngineClient(configured_settings)

        with pytest.raises(ExternalServiceError, match="unexpected response shape"):
            client._normalise(raw)  # type: ignore[arg-type]  # deliberately wrong


class TestFetchOrchestration:
    """Threading and timeout handling around the blocking Earth Engine call."""

    async def test_returns_the_normalised_payload(
        self, configured_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = EarthEngineClient(configured_settings)
        expected = {"dataset": "d", "scenario": "s", "models": [], "records": [{"year": 2025}]}
        monkeypatch.setattr(EarthEngineClient, "_fetch_blocking", lambda *args, **kwargs: expected)

        result = await client.fetch_projections(
            longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )

        assert result == expected

    async def test_a_slow_aggregation_maps_to_a_timeout_error(
        self, configured_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Earth Engine aggregations can hang; the request must not hang with them."""
        import time

        monkeypatch.setattr(constants, "EARTH_ENGINE_TIMEOUT_SECONDS", 0.05)
        # A genuinely blocking sleep is the point: it stands in for a slow Earth
        # Engine aggregation running on the worker thread, which is exactly what
        # the timeout must interrupt.
        monkeypatch.setattr(
            EarthEngineClient,
            "_fetch_blocking",
            lambda *args, **kwargs: time.sleep(1.0),  # noqa: ASYNC251
        )
        client = EarthEngineClient(configured_settings)

        with pytest.raises(ExternalServiceTimeoutError) as caught:
            await client.fetch_projections(
                longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
            )

        assert caught.value.http_status == 504
