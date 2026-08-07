"""Builds a climate risk profile from Earth Engine projections and IMD context, with caching.

The cache is what makes ``/score`` deterministic. Earth Engine responses are stored
against the rounded centroid and year range, so re-scoring a site replays the exact
projections the first score used. Without that, a re-score could move purely because
NASA republished the dataset between the two calls.

All unit conversion from upstream units to the canonical internal ones happens here,
at the boundary, and is annotated inline.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from app.core import calculations, constants
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.external.earth_engine import EarthEngineClient
from app.external.imd import DistrictHistory, IMDClient
from app.repositories.cache import ExternalCacheRepository, build_location_cache_key
from app.schemas.climate import (
    ClimateProfile,
    DataProvenance,
    HistoricalContext,
    YearlyHazardProjection,
)
from app.schemas.common import Centroid

logger = get_logger(__name__)


class ClimateDataService:
    """Assembles the climate risk profile for a site."""

    def __init__(
        self,
        *,
        earth_engine: EarthEngineClient,
        imd: IMDClient,
        cache: ExternalCacheRepository,
    ) -> None:
        """Bind the service to its clients and cache."""
        self._earth_engine = earth_engine
        self._imd = imd
        self._cache = cache

    async def get_profile(self, *, longitude: float, latitude: float) -> ClimateProfile:
        """Build the climate profile for a location.

        Args:
            longitude: WGS84 longitude of the site centroid.
            latitude: WGS84 latitude of the site centroid.

        Returns:
            Projections for every year of the horizon, historical context where
            available, and provenance for both.

        Raises:
            ExternalServiceUnconfiguredError: If Earth Engine credentials are
                absent. No projection means no score; a fabricated one is worse.
            ExternalServiceError: If Earth Engine failed or returned unusable data.
        """
        raw, provenance = await self._fetch_projections(longitude=longitude, latitude=latitude)
        projections = self._to_projections(raw)

        history = await self._imd.fetch_district_history(longitude=longitude, latitude=latitude)

        logger.info(
            "climate_profile_built",
            longitude=longitude,
            latitude=latitude,
            years=len(projections),
            has_history=history is not None,
        )

        return ClimateProfile(
            centroid=Centroid(longitude=longitude, latitude=latitude),
            projections=projections,
            historical=self._to_history(history),
            provenance=(*provenance, self._history_provenance(history)),
        )

    # ------------------------------------------------------------------
    # Projections
    # ------------------------------------------------------------------
    async def _fetch_projections(
        self, *, longitude: float, latitude: float
    ) -> tuple[dict[str, Any], tuple[DataProvenance, ...]]:
        """Return the raw Earth Engine payload, from cache when one is live."""
        cache_key = build_location_cache_key(
            dataset=(
                f"{constants.EARTH_ENGINE_CMIP6_DATASET}"
                f"/{constants.EARTH_ENGINE_CMIP6_SCENARIO}"
            ),
            longitude=longitude,
            latitude=latitude,
            start_year=constants.HORIZON_START_YEAR,
            end_year=constants.HORIZON_END_YEAR,
        )

        cached = await self._cache.get(service="earth_engine", cache_key=cache_key)
        if cached is not None:
            return cached, (
                DataProvenance(
                    service="earth_engine",
                    dataset=cached.get("dataset", constants.EARTH_ENGINE_CMIP6_DATASET),
                    retrieved_at=datetime.fromisoformat(cached["retrieved_at"]),
                    served_from_cache=True,
                    notes=(
                        f"Scenario {cached.get('scenario')}, "
                        f"{len(cached.get('models', []))}-model ensemble. Replayed from "
                        "cache so re-scoring cannot drift."
                    ),
                ),
            )

        payload = await self._earth_engine.fetch_projections(
            longitude=longitude,
            latitude=latitude,
            start_year=constants.HORIZON_START_YEAR,
            end_year=constants.HORIZON_END_YEAR,
        )
        retrieved_at = datetime.now(UTC)
        payload["retrieved_at"] = retrieved_at.isoformat()

        await self._cache.put(service="earth_engine", cache_key=cache_key, payload=payload)

        return payload, (
            DataProvenance(
                service="earth_engine",
                dataset=payload["dataset"],
                retrieved_at=retrieved_at,
                served_from_cache=False,
                notes=(
                    f"Scenario {payload['scenario']}, " f"{len(payload['models'])}-model ensemble."
                ),
            ),
        )

    @staticmethod
    def _to_projections(raw: dict[str, Any]) -> tuple[YearlyHazardProjection, ...]:
        """Convert raw per-model records into one converted projection per year.

        Records arrive as one entry per (year, model). The ensemble mean across
        models is used for the point estimate, because a single model's structural
        bias should not decide a permit.

        Raises:
            ExternalServiceError: If a year is missing every band it needs. Silently
                dropping the year would leave a gap the score engine would then
                treat as absent risk.
        """
        by_year: dict[int, list[dict[str, Any]]] = {}
        for record in raw["records"]:
            year = int(record["year"])
            by_year.setdefault(year, []).append(record)

        projections: list[YearlyHazardProjection] = []
        for year in sorted(by_year):
            records = by_year[year]

            temperature_k = _mean_band(records, constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE)
            precipitation_flux = _mean_band(records, constants.EARTH_ENGINE_BAND_PRECIPITATION)
            wind_ms = _mean_band(records, constants.EARTH_ENGINE_BAND_WIND_SPEED)
            humidity_percent = _mean_band(records, constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY)

            if None in (temperature_k, precipitation_flux, wind_ms, humidity_percent):
                raise ExternalServiceError(
                    f"Earth Engine returned incomplete bands for {year}.",
                    service="earth_engine",
                    details={"year": year},
                )

            # tasmax is published in kelvin -> degrees Celsius.
            max_temperature_c = calculations.kelvin_to_celsius(float(temperature_k or 0.0))
            # pr is published in kg m-2 s-1 -> millimetres per day.
            rainfall_mm = calculations.precipitation_flux_to_mm_per_day(
                float(precipitation_flux or 0.0)
            )
            # hurs is a percentage, clamped because ensemble means can round just
            # past 100 and the wet-bulb fit is only defined on [0, 100].
            humidity = calculations.clamp(float(humidity_percent or 0.0), 0.0, 100.0)

            projections.append(
                YearlyHazardProjection(
                    year=year,
                    # sfcWind is already metres per second.
                    peak_wind_speed_ms=max(0.0, float(wind_ms or 0.0)),
                    max_daily_rainfall_mm=max(0.0, rainfall_mm),
                    max_temperature_c=max_temperature_c,
                    max_wet_bulb_temperature_c=calculations.wet_bulb_temperature_c(
                        max_temperature_c, humidity
                    ),
                )
            )

        if not projections:
            raise ExternalServiceError(
                "Earth Engine returned no projections for the scoring horizon.",
                service="earth_engine",
            )
        return tuple(projections)

    # ------------------------------------------------------------------
    # Historical context
    # ------------------------------------------------------------------
    @staticmethod
    def _to_history(history: DistrictHistory | None) -> HistoricalContext | None:
        """Map district history onto the API shape, or pass through absence."""
        if history is None:
            return None
        return HistoricalContext(
            district=history.district,
            state=history.state,
            cyclone_events_recorded=history.cyclone_events_recorded,
            strongest_recorded_wind_ms=history.strongest_recorded_wind_ms,
            strongest_recorded_category=calculations.classify_cyclone_category(
                history.strongest_recorded_wind_ms
            ),
            wettest_recorded_day_mm=history.wettest_recorded_day_mm,
            record_period_start_year=history.record_period_start_year,
            record_period_end_year=history.record_period_end_year,
        )

    @staticmethod
    def _history_provenance(history: DistrictHistory | None) -> DataProvenance:
        """Describe where the historical context came from, including its absence."""
        if history is None:
            return DataProvenance(
                service="imd",
                dataset="district_history",
                retrieved_at=datetime.now(UTC),
                served_from_cache=False,
                notes=(
                    "No historical record is available for this location. IMD "
                    "coverage is uneven and no substitute figures were used."
                ),
            )
        return DataProvenance(
            service="imd",
            dataset="district_history",
            retrieved_at=datetime.now(UTC),
            served_from_cache=history.from_fallback,
            notes=(
                f"{history.source_note} "
                + (
                    "Served from the bundled offline snapshot, not the live IMD " "endpoint."
                    if history.from_fallback
                    else "Retrieved live."
                )
            ),
        )


def _mean_band(records: list[dict[str, Any]], band: str) -> float | None:
    """Ensemble mean of one band across models, ignoring models that omitted it.

    Returns ``None`` when no model reported the band, so the caller can raise
    rather than silently treating a missing hazard as zero.
    """
    values = [
        float(record[band])
        for record in records
        if record.get(band) is not None and isinstance(record[band], int | float)
    ]
    if not values:
        return None
    return statistics.fmean(values)
