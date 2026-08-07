"""India Meteorological Department client for historical cyclone and rainfall context.

**Read this before relying on it.** IMD publishes no documented, versioned, keyed
public REST API. ``api.imd.gov.in`` exposes undocumented endpoints that change
without notice and are periodically IP-restricted. This client therefore:

* calls the live endpoint properly — real timeouts, retries on transient failures
  only, typed errors, and strict validation of whatever comes back; and
* falls back to a small bundled snapshot when the live endpoint is unreachable or
  returns something unusable.

The fallback is **explicitly labelled** in the response provenance and covers only a
few districts. For any district not in it, the client returns ``None`` — meaning "no
historical context available" — rather than inventing plausible figures. An absent
record is reported as absent.

Units: IMD publishes wind speeds in km/h and rainfall in mm. Wind is converted to
m/s at the boundary of this module; rainfall is already in the internal unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core import calculations
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.external.http import request_json

logger = get_logger(__name__)

SERVICE_NAME = "imd"

# Bundled snapshot, used when the live endpoint cannot be reached.
FALLBACK_DATA_PATH = Path(__file__).parent / "data" / "imd_district_history.json"


@dataclass(frozen=True, slots=True)
class DistrictHistory:
    """Observed cyclone and rainfall history for one district.

    Attributes:
        district: District name as IMD writes it.
        state: State or union territory.
        cyclone_events_recorded: Cyclonic storms or stronger over the record period.
        strongest_recorded_wind_ms: Strongest sustained wind on record, m/s.
        wettest_recorded_day_mm: Highest single-day rainfall on record, mm.
        record_period_start_year: First year covered by the record.
        record_period_end_year: Last year covered by the record.
        from_fallback: True when this came from the bundled snapshot rather than
            the live endpoint. Surfaced to the client in the profile provenance.
        source_note: Human-readable provenance for this particular record.
    """

    district: str
    state: str
    cyclone_events_recorded: int
    strongest_recorded_wind_ms: float
    wettest_recorded_day_mm: float
    record_period_start_year: int
    record_period_end_year: int
    from_fallback: bool
    source_note: str


@lru_cache(maxsize=1)
def _load_fallback() -> dict[str, Any]:
    """Load and cache the bundled snapshot.

    Raises:
        ExternalServiceError: If the bundled file is missing or malformed, which
            means the deployment is broken rather than the upstream being down.
    """
    try:
        with FALLBACK_DATA_PATH.open(encoding="utf-8") as handle:
            data: dict[str, Any] = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ExternalServiceError(
            "The bundled IMD fallback dataset could not be read.",
            service=SERVICE_NAME,
            details={"path": str(FALLBACK_DATA_PATH)},
        ) from error
    return data


class IMDClient:
    """Fetches district-level historical context for a point location."""

    def __init__(self, settings: Settings) -> None:
        """Bind the client to configuration."""
        self._settings = settings

    async def fetch_district_history(
        self, *, longitude: float, latitude: float
    ) -> DistrictHistory | None:
        """Return historical context for the district containing a point.

        Tries the live endpoint first. On any failure it falls back to the bundled
        snapshot, and if that has no entry for the location it returns ``None``.

        Args:
            longitude: WGS84 longitude.
            latitude: WGS84 latitude.

        Returns:
            The district's history, or ``None`` when no record exists for it.
        """
        try:
            payload = await request_json(
                service=SERVICE_NAME,
                method="GET",
                url=f"{self._settings.imd_api_base_url.rstrip('/')}/districts/history",
                timeout_seconds=self._settings.imd_request_timeout_seconds,
                params={"lon": longitude, "lat": latitude},
            )
        except ExternalServiceError as error:
            # Expected often enough to log at info rather than error: the endpoint
            # is undocumented and frequently unavailable.
            logger.info(
                "imd_live_unavailable_using_fallback",
                reason=error.code,
                longitude=longitude,
                latitude=latitude,
            )
            return self._from_fallback(longitude=longitude, latitude=latitude)

        try:
            return self._parse_live(payload)
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("imd_live_response_unusable_using_fallback", error=str(error))
            return self._from_fallback(longitude=longitude, latitude=latitude)

    @staticmethod
    def _parse_live(payload: dict[str, Any]) -> DistrictHistory:
        """Map a live IMD response onto the internal shape.

        Raises:
            KeyError: If an expected field is absent.
            TypeError: If a field has an unusable type.
            ValueError: If a numeric field cannot be parsed.

        The caller treats any of these as "unusable" and falls back, rather than
        propagating a partially populated record.
        """
        # IMD publishes wind in km/h; the internal unit is m/s.
        strongest_wind_kmph = float(payload["strongest_wind_kmph"])

        return DistrictHistory(
            district=str(payload["district"]),
            state=str(payload["state"]),
            cyclone_events_recorded=int(payload["cyclone_events"]),
            strongest_recorded_wind_ms=calculations.kmph_to_ms(strongest_wind_kmph),
            wettest_recorded_day_mm=float(payload["max_daily_rainfall_mm"]),
            record_period_start_year=int(payload["period_start_year"]),
            record_period_end_year=int(payload["period_end_year"]),
            from_fallback=False,
            source_note="Live IMD endpoint.",
        )

    def _from_fallback(self, *, longitude: float, latitude: float) -> DistrictHistory | None:
        """Look the point up in the bundled snapshot.

        Returns ``None`` when the location falls outside every bundled bounding box
        — absence of data is reported as absence, never filled in.
        """
        data = _load_fallback()

        for entry in data["districts"]:
            box = entry["bounding_box"]
            within_longitude = box["min_lon"] <= longitude <= box["max_lon"]
            within_latitude = box["min_lat"] <= latitude <= box["max_lat"]
            if not (within_longitude and within_latitude):
                continue

            logger.info("imd_fallback_matched", district=entry["district"])
            return DistrictHistory(
                district=entry["district"],
                state=entry["state"],
                cyclone_events_recorded=entry["cyclone_events"],
                # Stored in km/h to match how IMD publishes it; converted here.
                strongest_recorded_wind_ms=calculations.kmph_to_ms(entry["strongest_wind_kmph"]),
                wettest_recorded_day_mm=entry["max_daily_rainfall_mm"],
                record_period_start_year=entry["period_start_year"],
                record_period_end_year=entry["period_end_year"],
                from_fallback=True,
                source_note=entry["source"],
            )

        logger.info("imd_no_history_available", longitude=longitude, latitude=latitude)
        return None
