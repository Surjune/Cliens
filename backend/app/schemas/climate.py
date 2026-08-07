"""Climate risk profile schemas: CMIP6 projections, hazard layers, IMD historical context.

Every figure that reaches a client carries its provenance. In a permit-approval
context the reader needs to know which dataset a number came from, when it was
retrieved, and whether it was served from cache — otherwise the score is an
unauditable assertion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import Centroid, HorizonYear, SchemaBase

ServiceName = Literal["earth_engine", "imd", "gemini"]


class YearlyHazardProjection(SchemaBase):
    """Projected hazard intensities for one year at one location.

    Units are the canonical internal ones from CLAUDE.md: m/s, mm, °C.
    """

    year: HorizonYear
    peak_wind_speed_ms: float = Field(
        ge=0.0,
        description="Annual maximum sustained wind speed, metres per second.",
    )
    max_daily_rainfall_mm: float = Field(
        ge=0.0,
        description="Annual maximum single-day rainfall, millimetres.",
    )
    max_temperature_c: float = Field(
        description="Annual maximum daily temperature, degrees Celsius.",
    )
    max_wet_bulb_temperature_c: float = Field(
        description=(
            "Annual maximum wet-bulb temperature, degrees Celsius. Above 35 °C a "
            "site is unlivable regardless of construction, so this can override "
            "the material-based score."
        ),
    )


class HistoricalContext(SchemaBase):
    """Observed cyclone and rainfall history for the district containing the site.

    Grounds the projection in what has already happened locally. Optional: IMD
    coverage is uneven, and an absent record is reported as absent rather than
    filled in with a plausible-looking number.
    """

    district: str | None = Field(description="District the site falls in, as IMD names it.")
    state: str | None = Field(description="State or union territory.")
    cyclone_events_recorded: int = Field(
        ge=0, description="Cyclonic storms or stronger recorded over the record period."
    )
    strongest_recorded_wind_ms: float = Field(
        ge=0.0, description="Strongest sustained wind on record, metres per second."
    )
    strongest_recorded_category: str = Field(
        description="IMD category corresponding to the strongest recorded wind."
    )
    wettest_recorded_day_mm: float = Field(
        ge=0.0, description="Highest single-day rainfall on record, millimetres."
    )
    record_period_start_year: int
    record_period_end_year: int


class DataProvenance(SchemaBase):
    """Where one part of a profile came from."""

    service: ServiceName
    dataset: str = Field(description="Dataset or endpoint identifier within that service.")
    retrieved_at: datetime = Field(description="When the upstream was last actually called.")
    served_from_cache: bool = Field(
        description=(
            "True when replayed from the durable cache. Re-scoring reuses the "
            "cached response so a score cannot drift because an upstream changed."
        )
    )
    notes: str | None = Field(
        default=None,
        description="Caveats a reader needs, such as known coverage gaps.",
    )


class ClimateProfile(SchemaBase):
    """The full climate risk picture for one site across the scoring horizon."""

    centroid: Centroid
    projections: tuple[YearlyHazardProjection, ...] = Field(
        description="One entry per year from 2025 to 2055, ascending."
    )
    historical: HistoricalContext | None = Field(
        description="Observed local history, or null where IMD has no coverage."
    )
    provenance: tuple[DataProvenance, ...] = Field(
        description="Provenance for every upstream contributing to this profile."
    )


class ClimateProfileRequest(SchemaBase):
    """Request a climate profile for a stored site's centroid."""

    longitude: float = Field(ge=-180.0, le=180.0, description="WGS84 longitude.")
    latitude: float = Field(ge=-90.0, le=90.0, description="WGS84 latitude.")
