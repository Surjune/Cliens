"""Tests for the climate data service.

Two things matter most here and both are covered directly: the unit conversions at
the Earth Engine boundary (a silent kelvin-vs-Celsius mistake would corrupt every
score), and the caching behaviour that makes re-scoring deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import constants
from app.core.exceptions import ExternalServiceError, ExternalServiceUnconfiguredError
from app.external.imd import DistrictHistory
from app.services.climate_data import ClimateDataService

CHENNAI_LON = 80.27
CHENNAI_LAT = 13.01


def build_payload(years: list[int]) -> dict[str, Any]:
    """A realistic Earth Engine payload in upstream units."""
    return {
        "dataset": constants.EARTH_ENGINE_CMIP6_DATASET,
        "scenario": constants.EARTH_ENGINE_CMIP6_SCENARIO,
        "models": list(constants.EARTH_ENGINE_CMIP6_MODELS),
        "records": [
            {
                "year": year,
                "model": model,
                constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE: 313.15,  # 40 °C
                constants.EARTH_ENGINE_BAND_PRECIPITATION: 0.001,  # 86.4 mm/day
                constants.EARTH_ENGINE_BAND_WIND_SPEED: 25.0,  # m/s
                constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY: 70.0,  # percent
            }
            for year in years
            for model in constants.EARTH_ENGINE_CMIP6_MODELS
        ],
    }


class StubEarthEngine:
    """Returns a canned payload and records how often it was called."""

    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None):
        self.payload = payload if payload is not None else build_payload([2025, 2026])
        self.error = error
        self.call_count = 0

    async def fetch_projections(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return dict(self.payload)


class StubIMD:
    """Returns a canned district history, or none."""

    def __init__(self, history: DistrictHistory | None = None):
        self.history = history

    async def fetch_district_history(self, **kwargs: Any) -> DistrictHistory | None:  # noqa: ANN401
        return self.history


class StubCache:
    """An in-memory stand-in for the durable cache."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict[str, Any]] = {}
        self.put_count = 0

    async def get(self, *, service: str, cache_key: str) -> dict[str, Any] | None:
        return self.store.get((service, cache_key))

    async def put(
        self,
        *,
        service: str,
        cache_key: str,
        payload: dict[str, Any],
        **_: Any,  # noqa: ANN401 — absorbs ttl_days without restating its type
    ) -> None:
        self.put_count += 1
        self.store[(service, cache_key)] = payload


def build_service(
    earth_engine: StubEarthEngine | None = None,
    imd: StubIMD | None = None,
    cache: StubCache | None = None,
) -> ClimateDataService:
    """Wire the service to stubs."""
    return ClimateDataService(
        earth_engine=earth_engine or StubEarthEngine(),  # type: ignore[arg-type]
        imd=imd or StubIMD(),  # type: ignore[arg-type]
        cache=cache or StubCache(),  # type: ignore[arg-type]
    )


class TestUnitConversion:
    """A silent unit mismatch here would corrupt every score downstream."""

    async def test_converts_kelvin_to_celsius(self) -> None:
        service = build_service()

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        # 313.15 K is exactly 40 °C.
        assert profile.projections[0].max_temperature_c == pytest.approx(40.0)

    async def test_converts_precipitation_flux_to_mm_per_day(self) -> None:
        service = build_service()

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        # 0.001 kg m-2 s-1 over 86,400 s is 86.4 mm/day.
        assert profile.projections[0].max_daily_rainfall_mm == pytest.approx(86.4)

    async def test_leaves_wind_speed_in_metres_per_second(self) -> None:
        service = build_service()

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert profile.projections[0].peak_wind_speed_ms == pytest.approx(25.0)

    async def test_derives_wet_bulb_below_dry_bulb(self) -> None:
        """Wet-bulb temperature is always at or below dry-bulb below 100% humidity."""
        service = build_service()

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        projection = profile.projections[0]

        assert projection.max_wet_bulb_temperature_c < projection.max_temperature_c


class TestEnsembleHandling:
    """Multiple models are averaged; incomplete years are an error."""

    async def test_averages_across_models_into_one_entry_per_year(self) -> None:
        service = build_service(StubEarthEngine(build_payload([2025, 2026, 2027])))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert [p.year for p in profile.projections] == [2025, 2026, 2027]

    async def test_returns_years_in_ascending_order(self) -> None:
        payload = build_payload([2027, 2025, 2026])
        service = build_service(StubEarthEngine(payload))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert [p.year for p in profile.projections] == [2025, 2026, 2027]

    async def test_a_year_missing_a_band_is_an_error_not_a_zero(self) -> None:
        """Dropping the year would let the engine read it as absent risk."""
        payload = build_payload([2025])
        for record in payload["records"]:
            del record[constants.EARTH_ENGINE_BAND_WIND_SPEED]
        service = build_service(StubEarthEngine(payload))

        with pytest.raises(ExternalServiceError, match="incomplete bands"):
            await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

    async def test_ignores_a_single_model_that_omitted_a_band(self) -> None:
        """One model dropping out must not discard the whole year."""
        payload = build_payload([2025])
        del payload["records"][0][constants.EARTH_ENGINE_BAND_WIND_SPEED]
        service = build_service(StubEarthEngine(payload))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert profile.projections[0].peak_wind_speed_ms == pytest.approx(25.0)


class TestDeterminismThroughCaching:
    """Re-scoring must not drift because an upstream republished its data."""

    async def test_second_request_is_served_from_cache(self) -> None:
        earth_engine = StubEarthEngine()
        cache = StubCache()
        service = build_service(earth_engine, cache=cache)

        await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert earth_engine.call_count == 1

    async def test_cached_profiles_are_identical(self) -> None:
        service = build_service(cache=StubCache())

        first = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        second = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert first.projections == second.projections

    async def test_cache_reuse_is_declared_in_provenance(self) -> None:
        """A reader must be able to tell a replayed profile from a fresh one."""
        service = build_service(cache=StubCache())

        first = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        second = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        earth_engine_first = next(p for p in first.provenance if p.service == "earth_engine")
        earth_engine_second = next(p for p in second.provenance if p.service == "earth_engine")

        assert earth_engine_first.served_from_cache is False
        assert earth_engine_second.served_from_cache is True

    async def test_nearby_coordinates_share_a_cache_entry(self) -> None:
        """Rounding is finer than any grid cell, so this cannot merge conditions."""
        earth_engine = StubEarthEngine()
        service = build_service(earth_engine, cache=StubCache())

        await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        await service.get_profile(longitude=CHENNAI_LON + 1e-7, latitude=CHENNAI_LAT)

        assert earth_engine.call_count == 1

    async def test_distant_coordinates_do_not_share_a_cache_entry(self) -> None:
        earth_engine = StubEarthEngine()
        service = build_service(earth_engine, cache=StubCache())

        await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)
        await service.get_profile(longitude=CHENNAI_LON + 0.5, latitude=CHENNAI_LAT)

        assert earth_engine.call_count == 2


class TestHistoricalContext:
    """Absent history is reported as absent."""

    async def test_includes_history_when_available(self) -> None:
        history = DistrictHistory(
            district="Chennai",
            state="Tamil Nadu",
            cyclone_events_recorded=11,
            strongest_recorded_wind_ms=36.1,
            wettest_recorded_day_mm=490.0,
            record_period_start_year=1990,
            record_period_end_year=2023,
            from_fallback=True,
            source_note="Cyclone Vardah (Dec 2016).",
        )
        service = build_service(imd=StubIMD(history))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert profile.historical is not None
        assert profile.historical.district == "Chennai"
        # 36.1 m/s is about 130 km/h — a Very Severe Cyclonic Storm.
        assert profile.historical.strongest_recorded_category == "Very Severe Cyclonic Storm"

    async def test_reports_absence_without_substituting_figures(self) -> None:
        service = build_service(imd=StubIMD(None))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert profile.historical is None
        imd_provenance = next(p for p in profile.provenance if p.service == "imd")
        assert "No historical record" in (imd_provenance.notes or "")

    async def test_fallback_history_is_labelled_as_offline(self) -> None:
        history = DistrictHistory(
            district="Chennai",
            state="Tamil Nadu",
            cyclone_events_recorded=11,
            strongest_recorded_wind_ms=36.1,
            wettest_recorded_day_mm=490.0,
            record_period_start_year=1990,
            record_period_end_year=2023,
            from_fallback=True,
            source_note="Bundled snapshot.",
        )
        service = build_service(imd=StubIMD(history))

        profile = await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        imd_provenance = next(p for p in profile.provenance if p.service == "imd")
        assert "bundled offline snapshot" in (imd_provenance.notes or "")


class TestFailurePropagation:
    """A missing projection means no score at all."""

    async def test_unconfigured_earth_engine_propagates(self) -> None:
        error = ExternalServiceUnconfiguredError("nope", service="earth_engine")
        service = build_service(StubEarthEngine(error=error))

        with pytest.raises(ExternalServiceUnconfiguredError):
            await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

    async def test_a_failed_fetch_is_not_cached(self) -> None:
        """A failure must not poison the cache for later successful attempts."""
        cache = StubCache()
        error = ExternalServiceError("upstream down", service="earth_engine")
        service = build_service(StubEarthEngine(error=error), cache=cache)

        with pytest.raises(ExternalServiceError):
            await service.get_profile(longitude=CHENNAI_LON, latitude=CHENNAI_LAT)

        assert cache.put_count == 0
