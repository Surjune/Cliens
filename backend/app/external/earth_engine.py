"""Google Earth Engine client for CMIP6 projections and hazard layers.

Wraps the ``earthengine-api`` package, which is synchronous and blocking. Every call
is dispatched to a worker thread so it cannot stall the event loop.

Authentication is service-account based: Earth Engine authenticates as a service
account *within a specific registered Cloud project*, so all three of project id,
account email and key file are required. With any of them missing this client
raises ``ExternalServiceUnconfiguredError`` — it never returns placeholder numbers,
because a fabricated climate projection in a permit decision is worse than an error.

Units, as published in NASA/GDDP-CMIP6:

===============  ==========================  ==========================
Band             Published unit              Converted to
===============  ==========================  ==========================
``tasmax``       kelvin                      degrees Celsius
``pr``           kg m-2 s-1 (== mm/s)        millimetres per day
``sfcWind``      metres per second           unchanged
``hurs``         percent                     unchanged
===============  ==========================  ==========================

Conversion happens in the climate service, not here: this client's job is to return
the upstream response faithfully so that what gets cached is what was received.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.core import constants
from app.core.config import Settings
from app.core.exceptions import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    ExternalServiceUnconfiguredError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

SERVICE_NAME = "earth_engine"

# Earth Engine initialisation is process-wide and not thread-safe, so it is guarded
# and performed at most once per process.
_init_lock = threading.Lock()
_initialised = False


class EarthEngineClient:
    """Reads CMIP6 projections for a point location."""

    def __init__(self, settings: Settings) -> None:
        """Bind the client to configuration.

        Construction never touches the network; the first request initialises.
        """
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        """Whether credentials are present for authentication to be attempted."""
        return self._settings.earth_engine_configured

    def _require_configured(self) -> None:
        """Raise unless every credential is present.

        Raises:
            ExternalServiceUnconfiguredError: If any credential is missing.
        """
        if self.is_configured:
            return
        missing = [
            name
            for name, value in (
                ("EARTH_ENGINE_PROJECT_ID", self._settings.earth_engine_project_id),
                (
                    "EARTH_ENGINE_SERVICE_ACCOUNT_EMAIL",
                    self._settings.earth_engine_service_account_email,
                ),
                (
                    "EARTH_ENGINE_SERVICE_ACCOUNT_FILE",
                    self._settings.earth_engine_service_account_file,
                ),
            )
            if not value
        ]
        raise ExternalServiceUnconfiguredError(
            "Earth Engine is not configured, so climate projections cannot be "
            "retrieved. See the README section 'Prerequisites' for how to obtain "
            "and set these values.",
            service=SERVICE_NAME,
            details={"missing": missing},
        )

    def _initialise(self) -> None:
        """Authenticate this process with Earth Engine, at most once.

        Runs on a worker thread. The lock makes concurrent first requests safe.

        Raises:
            ExternalServiceError: If authentication fails.
        """
        global _initialised
        with _init_lock:
            if _initialised:
                return

            import ee

            email = self._settings.earth_engine_service_account_email
            key_file = self._settings.earth_engine_service_account_file
            project = self._settings.earth_engine_project_id
            if email is None or key_file is None or project is None:
                # Unreachable: _require_configured runs first. Narrowing here keeps
                # the credential types honest rather than asserting them away.
                raise ExternalServiceUnconfiguredError(
                    "Earth Engine credentials went missing between the check and "
                    "the connection attempt.",
                    service=SERVICE_NAME,
                )

            try:
                credentials = ee.ServiceAccountCredentials(email, str(key_file))
                ee.Initialize(credentials, project=project)
            except Exception as error:
                # The ee package raises a wide range of types (auth, transport,
                # protobuf). Catching broadly and re-raising one typed error is the
                # only way to give callers something they can handle, and the
                # original is chained for diagnosis.
                logger.exception("earth_engine_init_failed", project=project)
                raise ExternalServiceError(
                    "Could not authenticate with Earth Engine. Check that the "
                    "service account has the Earth Engine Resource Viewer role and "
                    "that the project is registered for Earth Engine.",
                    service=SERVICE_NAME,
                    details={"project_id": project},
                ) from error

            _initialised = True
            logger.info("earth_engine_initialised", project=project)

    async def fetch_projections(
        self,
        *,
        longitude: float,
        latitude: float,
        start_year: int,
        end_year: int,
    ) -> dict[str, Any]:
        """Fetch annual hazard maxima for a point, per year and per model.

        One Earth Engine round trip is made for the whole horizon: building a
        feature per (year, model) and calling ``getInfo`` once is dramatically
        faster than a request per year, and Earth Engine bills per call.

        Args:
            longitude: WGS84 longitude of the site centroid.
            latitude: WGS84 latitude of the site centroid.
            start_year: First year of the horizon, inclusive.
            end_year: Last year of the horizon, inclusive.

        Returns:
            The upstream response, unconverted, ready to be cached verbatim.

        Raises:
            ExternalServiceUnconfiguredError: If credentials are missing.
            ExternalServiceTimeoutError: If the aggregation exceeded its budget.
            ExternalServiceError: If Earth Engine rejected or failed the request.
        """
        self._require_configured()

        logger.info(
            "earth_engine_fetch_started",
            longitude=longitude,
            latitude=latitude,
            start_year=start_year,
            end_year=end_year,
            scenario=constants.EARTH_ENGINE_CMIP6_SCENARIO,
        )

        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    self._fetch_blocking,
                    longitude=longitude,
                    latitude=latitude,
                    start_year=start_year,
                    end_year=end_year,
                ),
                timeout=constants.EARTH_ENGINE_TIMEOUT_SECONDS,
            )
        except TimeoutError as error:
            raise ExternalServiceTimeoutError(
                f"Earth Engine did not complete the aggregation within "
                f"{constants.EARTH_ENGINE_TIMEOUT_SECONDS:g}s.",
                service=SERVICE_NAME,
            ) from error

        logger.info("earth_engine_fetch_succeeded", records=len(payload.get("records", [])))
        return payload

    def _fetch_blocking(
        self,
        *,
        longitude: float,
        latitude: float,
        start_year: int,
        end_year: int,
    ) -> dict[str, Any]:
        """Run the Earth Engine query. Blocking; called on a worker thread.

        Raises:
            ExternalServiceError: If Earth Engine rejects or fails the request.
        """
        self._initialise()

        import ee

        bands = [
            constants.EARTH_ENGINE_BAND_MAX_TEMPERATURE,
            constants.EARTH_ENGINE_BAND_PRECIPITATION,
            constants.EARTH_ENGINE_BAND_WIND_SPEED,
            constants.EARTH_ENGINE_BAND_RELATIVE_HUMIDITY,
        ]

        try:
            point = ee.Geometry.Point([longitude, latitude])
            region = point.buffer(constants.EARTH_ENGINE_SAMPLE_RADIUS_M)

            collection = (
                ee.ImageCollection(constants.EARTH_ENGINE_CMIP6_DATASET)
                .filter(ee.Filter.eq("scenario", constants.EARTH_ENGINE_CMIP6_SCENARIO))
                .filter(ee.Filter.inList("model", list(constants.EARTH_ENGINE_CMIP6_MODELS)))
                .select(bands)
            )

            def annual_feature(
                year: Any,  # noqa: ANN401 — ee objects are dynamically constructed
                model: Any,  # noqa: ANN401
            ) -> Any:  # noqa: ANN401
                """Build one feature holding a model's annual maxima for a year."""
                year_number = ee.Number(year)
                start = ee.Date.fromYMD(year_number, 1, 1)
                end = start.advance(1, "year")

                yearly = collection.filter(ee.Filter.eq("model", model)).filterDate(start, end)

                # Annual maximum per band: the score is driven by peak stress, not
                # by the annual mean. A site fails in the worst storm of a year.
                maxima = yearly.max().reduceRegion(
                    reducer=ee.Reducer.mean(),  # spatial mean within the sample radius
                    geometry=region,
                    scale=constants.EARTH_ENGINE_SAMPLE_RADIUS_M,
                    maxPixels=1e9,
                    bestEffort=True,
                )
                return ee.Feature(None, maxima.set("year", year_number).set("model", model))

            features = []
            for model in constants.EARTH_ENGINE_CMIP6_MODELS:
                per_model = ee.List(list(range(start_year, end_year + 1))).map(
                    lambda year, bound_model=model: annual_feature(year, bound_model)
                )
                features.append(ee.FeatureCollection(per_model))

            merged = ee.FeatureCollection(features).flatten()
            raw = merged.getInfo()
        except ExternalServiceError:
            raise
        except Exception as error:
            logger.exception("earth_engine_query_failed")
            raise ExternalServiceError(
                "Earth Engine could not complete the climate projection query.",
                service=SERVICE_NAME,
                details={"dataset": constants.EARTH_ENGINE_CMIP6_DATASET},
            ) from error

        return self._normalise(raw)

    @staticmethod
    def _normalise(raw: dict[str, Any] | None) -> dict[str, Any]:
        """Flatten Earth Engine's FeatureCollection into a compact cacheable shape.

        Raises:
            ExternalServiceError: If the response is missing the expected structure,
                which would otherwise surface much later as a confusing KeyError.
        """
        if not isinstance(raw, dict) or "features" not in raw:
            raise ExternalServiceError(
                "Earth Engine returned an unexpected response shape.",
                service=SERVICE_NAME,
            )

        records: list[dict[str, Any]] = []
        for feature in raw["features"]:
            properties = feature.get("properties", {})
            if "year" not in properties or "model" not in properties:
                continue
            records.append(properties)

        if not records:
            raise ExternalServiceError(
                "Earth Engine returned no usable projection records for this "
                "location. The site may fall outside the dataset's coverage.",
                service=SERVICE_NAME,
                details={"dataset": constants.EARTH_ENGINE_CMIP6_DATASET},
            )

        return {
            "dataset": constants.EARTH_ENGINE_CMIP6_DATASET,
            "scenario": constants.EARTH_ENGINE_CMIP6_SCENARIO,
            "models": list(constants.EARTH_ENGINE_CMIP6_MODELS),
            "records": records,
        }


def reset_initialisation_state() -> None:
    """Forget that Earth Engine was initialised. Used between tests only."""
    global _initialised
    with _init_lock:
        _initialised = False
