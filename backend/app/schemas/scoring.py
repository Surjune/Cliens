"""Score request/response schemas including the auditable score breakdown.

The breakdown is not decoration. The brief requires every score to be traceable
back to the inputs that produced it, because this number is meant to inform a
permit decision — so the response carries the per-year damage ratios, the
per-component and per-hazard stress contributions, the resolved materials, and the
model versions that produced it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import (
    ConfidenceLabel,
    HorizonYear,
    SchemaBase,
    UnitInterval,
)
from app.schemas.materials import MaterialSelection, ResolvedMaterial

Scenario = Literal["baseline", "improved"]


class ScoreRequest(SchemaBase):
    """Request a Climate Lien Score for a stored site."""

    site_id: uuid.UUID = Field(description="Identifier returned when the site was created.")
    materials: MaterialSelection = Field(description="One material per building component.")


class HazardContribution(SchemaBase):
    """How much one hazard contributed to a component's stress."""

    hazard: Literal["wind", "flood", "heat"]
    contribution: float = Field(
        ge=0.0, description="Weighted stress this hazard placed on this component."
    )


class ComponentBreakdown(SchemaBase):
    """One component's contribution to total structural stress."""

    component: Literal["foundation", "walls", "roofing"]
    material_code: str
    material_name: str
    total: float = Field(ge=0.0, description="Total stress reaching this component.")
    by_hazard: tuple[HazardContribution, ...]


class YearBreakdown(SchemaBase):
    """The full picture for one year of the horizon."""

    year: HorizonYear
    peak_wind_speed_ms: float
    max_daily_rainfall_mm: float
    max_temperature_c: float
    max_wet_bulb_temperature_c: float

    intensity_wind: float = Field(ge=0.0, description="Wind intensity, normalised to design load.")
    intensity_flood: float = Field(ge=0.0, description="Flood intensity, normalised.")
    intensity_heat: float = Field(ge=0.0, description="Heat intensity, normalised.")

    stress_total: float = Field(ge=0.0, description="Resistance-weighted stress for this year.")
    damage_ratio: UnitInterval = Field(description="Predicted damage ratio.")
    damage_ratio_lower: UnitInterval = Field(description="Lower bound of the 95% interval.")
    damage_ratio_upper: UnitInterval = Field(description="Upper bound of the 95% interval.")
    is_uninsurable: bool = Field(description="Whether this year crosses the threshold.")
    exceeds_survivability_limit: bool = Field(
        description=(
            "Whether wet-bulb temperature exceeds the 35 °C human survivability "
            "limit. No material choice mitigates this."
        )
    )


class ScoreBreakdown(SchemaBase):
    """Everything needed to audit a score."""

    uninsurable_damage_threshold: UnitInterval = Field(
        description="The damage ratio at which a site is treated as uninsurable."
    )
    area_sq_ft: float = Field(description="Footprint used, computed by PostGIS from the polygon.")
    area_exposure_factor: float = Field(description="Multiplier applied to stress for footprint.")
    materials: tuple[ResolvedMaterial, ...]
    components: tuple[ComponentBreakdown, ...] = Field(
        description="Stress decomposition at the first crossing year, or the final year."
    )
    years: tuple[YearBreakdown, ...] = Field(description="One entry per year, ascending.")


class MaterialRecommendation(SchemaBase):
    """A suggested replacement for one component."""

    component: Literal["foundation", "walls", "roofing"]
    current_code: str
    current_name: str
    recommended_code: str
    recommended_name: str
    predicted_damage_reduction: float = Field(
        ge=0.0, description="Damage ratio removed by this change, per the ranking model."
    )
    relative_cost_index: float = Field(
        gt=0, description="Cost of the recommendation relative to the conventional option."
    )
    rationale: str = Field(description="Why this material was suggested for this site.")


class ScoreResponse(SchemaBase):
    """A Climate Lien Score with its full provenance.

    ``crossing_year`` is null when the site never crosses the threshold within the
    horizon. That is materially different from crossing in 2055 and clients must
    present it differently.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    scenario: Scenario

    crossing_year: HorizonYear | None = Field(
        description="First year the site becomes uninsurable, or null if never within the horizon."
    )
    crossing_year_lower: HorizonYear | None = Field(
        description="Earliest plausible crossing year at the 95% level."
    )
    crossing_year_upper: HorizonYear | None = Field(
        description="Latest plausible crossing year at the 95% level."
    )
    confidence: ConfidenceLabel

    breakdown: ScoreBreakdown
    damage_model_version: str
    material_model_version: str
    created_at: datetime


class ProveResponse(SchemaBase):
    """Baseline and improved scores side by side, with what changed.

    Both are computed by the same engine from the same climate profile, so the two
    years are directly comparable — which is the entire point of the prove step.
    """

    baseline: ScoreResponse
    improved: ScoreResponse
    recommendations: tuple[MaterialRecommendation, ...]
    years_gained: int | None = Field(
        description=(
            "How many years later the improved build crosses the threshold. Null "
            "when either scenario never crosses within the horizon, since the "
            "difference would be unbounded."
        )
    )
