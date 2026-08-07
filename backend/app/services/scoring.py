"""The score engine.

Combines climate profile, damage calibration and material resistance into a
deterministic, auditable Climate Lien Score.

Determinism, which is the property the whole product rests on:

* the climate profile is replayed from cache, so upstream changes cannot move a
  re-score;
* every calculation is a pure function in ``core/calculations``;
* the model artifacts are pinned and their versions are part of the input hash;
* scoring the same inputs twice returns the stored row rather than recomputing.

Every number in the response is traceable to an input. Nothing here is a black box.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from app.core import calculations, constants
from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_logger
from app.ml.damage_calibration import DamageCalibrationModel
from app.ml.material_ranker import MaterialRankerModel
from app.repositories.scores import ScoreRecord, ScoreRepository
from app.repositories.sites import SiteRepository
from app.schemas.climate import ClimateProfile, YearlyHazardProjection
from app.schemas.materials import MaterialSelection, ResolvedMaterial
from app.schemas.scoring import (
    ComponentBreakdown,
    HazardContribution,
    MaterialRecommendation,
    ProveResponse,
    ScoreBreakdown,
    ScoreResponse,
    YearBreakdown,
)
from app.services.climate_data import ClimateDataService
from app.services.materials import MaterialService

logger = get_logger(__name__)


class ScoringService:
    """Computes and persists Climate Lien Scores."""

    def __init__(
        self,
        *,
        sites: SiteRepository,
        scores: ScoreRepository,
        materials: MaterialService,
        climate: ClimateDataService,
        damage_model: DamageCalibrationModel,
        ranker_model: MaterialRankerModel,
    ) -> None:
        """Bind the engine to its collaborators."""
        self._sites = sites
        self._scores = scores
        self._materials = materials
        self._climate = climate
        self._damage_model = damage_model
        self._ranker_model = ranker_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def score(self, *, site_id: uuid.UUID, selection: MaterialSelection) -> ScoreResponse:
        """Compute the baseline score for a site and material selection.

        Raises:
            ResourceNotFoundError: If the site does not exist.
            UnknownMaterialError: If a material code cannot be resolved.
            ExternalServiceUnconfiguredError: If Earth Engine is not configured.
        """
        return await self._score_scenario(site_id=site_id, selection=selection, scenario="baseline")

    async def prove(self, *, site_id: uuid.UUID, selection: MaterialSelection) -> ProveResponse:
        """Score the site, recommend better materials, and re-score with them.

        Both scores come from the same engine and the same cached climate profile,
        so the two crossing years are directly comparable.
        """
        baseline = await self._score_scenario(
            site_id=site_id, selection=selection, scenario="baseline"
        )

        recommendations = await self._recommend(site_id=site_id, baseline=baseline)
        improved_selection = self._apply(selection, recommendations)

        improved = await self._score_scenario(
            site_id=site_id, selection=improved_selection, scenario="improved"
        )

        years_gained: int | None = None
        if baseline.crossing_year is not None and improved.crossing_year is not None:
            years_gained = improved.crossing_year - baseline.crossing_year

        logger.info(
            "prove_completed",
            site_id=str(site_id),
            baseline_year=baseline.crossing_year,
            improved_year=improved.crossing_year,
            years_gained=years_gained,
        )

        return ProveResponse(
            baseline=baseline,
            improved=improved,
            recommendations=recommendations,
            years_gained=years_gained,
        )

    # ------------------------------------------------------------------
    # Core engine
    # ------------------------------------------------------------------
    async def _score_scenario(
        self, *, site_id: uuid.UUID, selection: MaterialSelection, scenario: str
    ) -> ScoreResponse:
        """Compute one scenario, returning a stored score when inputs are unchanged."""
        site = await self._sites.get(site_id)
        if site is None:
            raise ResourceNotFoundError(
                "No site exists with that id.", details={"site_id": str(site_id)}
            )

        resolved = await self._materials.resolve_selection(selection)
        versions = {
            "damage_model": self._damage_model.version,
            "material_model": self._ranker_model.version,
        }
        input_hash = self._hash_inputs(site_id=site_id, selection=selection, versions=versions)

        existing = await self._scores.get_by_hash(input_hash=input_hash, scenario=scenario)
        if existing is not None:
            # Idempotency: identical inputs must return an identical score, not a
            # recomputed one that could differ by a floating-point hair.
            logger.info("score_served_from_store", site_id=str(site_id), scenario=scenario)
            return self._to_response(existing)

        profile = await self._climate.get_profile(
            longitude=site.centroid_longitude, latitude=site.centroid_latitude
        )
        resistances: dict[str, dict[str, float]] = {
            material.component: {
                "wind": material.resistance.wind,
                "flood": material.resistance.flood,
                "heat": material.resistance.heat,
            }
            for material in resolved
        }

        breakdown, crossing, lower, upper = self._evaluate(
            profile=profile,
            resistances=resistances,
            resolved=resolved,
            area_sq_ft=site.area_sq_ft,
        )

        interval_width = float(
            (upper if upper else constants.HORIZON_END_YEAR)
            - (lower if lower else constants.HORIZON_START_YEAR)
        )
        confidence = calculations.confidence_label(abs(interval_width))

        record = await self._scores.create(
            site_id=site_id,
            input_hash=input_hash,
            scenario=scenario,
            crossing_year=crossing,
            crossing_year_lower=lower,
            crossing_year_upper=upper,
            confidence_label=confidence,
            breakdown=breakdown.model_dump(mode="json"),
            damage_model_version=versions["damage_model"],
            material_model_version=versions["material_model"],
        )

        logger.info(
            "score_computed",
            site_id=str(site_id),
            scenario=scenario,
            crossing_year=crossing,
            confidence=confidence,
        )
        return self._to_response(record)

    def _evaluate(
        self,
        *,
        profile: ClimateProfile,
        resistances: dict[str, dict[str, float]],
        resolved: tuple[ResolvedMaterial, ...],
        area_sq_ft: float,
    ) -> tuple[ScoreBreakdown, int | None, int | None, int | None]:
        """Run the engine over the horizon.

        Returns:
            The breakdown, the crossing year, and the bounds of its 95% interval.
            A bound is ``None`` when that end of the interval never crosses.
        """
        area_factor = calculations.area_exposure_factor(area_sq_ft)

        rows: list[dict[str, float]] = []
        per_year_context: list[tuple[YearlyHazardProjection, calculations.StressBreakdown]] = []

        for projection in profile.projections:
            intensities = self._intensities(projection)
            stress = calculations.resistance_weighted_stress(intensities, resistances)

            rows.append(
                {
                    "stress_total": stress.total * area_factor,
                    "stress_wind": stress.by_hazard["wind"] * area_factor,
                    "stress_flood": stress.by_hazard["flood"] * area_factor,
                    "stress_heat": stress.by_hazard["heat"] * area_factor,
                    "area_factor": area_factor,
                }
            )
            per_year_context.append((projection, stress))

        predictions = self._damage_model.predict_many(rows)

        years: list[YearBreakdown] = []
        damage_by_year: dict[int, float] = {}
        lower_by_year: dict[int, float] = {}
        upper_by_year: dict[int, float] = {}

        for (projection, _stress), row, prediction in zip(
            per_year_context, rows, predictions, strict=True
        ):
            intensities = self._intensities(projection)

            # Wet-bulb above the survivability limit makes a site unlivable
            # regardless of construction, so it forces the damage ratio to the
            # threshold rather than letting good materials mask it.
            exceeds_survivability = (
                projection.max_wet_bulb_temperature_c >= constants.WET_BULB_SURVIVABILITY_LIMIT_C
            )
            damage = prediction.damage_ratio
            lower_damage = prediction.lower
            upper_damage = prediction.upper
            if exceeds_survivability:
                damage = max(damage, constants.UNINSURABLE_DAMAGE_RATIO)
                lower_damage = max(lower_damage, constants.UNINSURABLE_DAMAGE_RATIO)
                upper_damage = max(upper_damage, constants.UNINSURABLE_DAMAGE_RATIO)

            damage_by_year[projection.year] = damage
            # The interval on the crossing YEAR is inverted relative to the
            # interval on damage: more damage means an earlier crossing.
            lower_by_year[projection.year] = upper_damage
            upper_by_year[projection.year] = lower_damage

            years.append(
                YearBreakdown(
                    year=projection.year,
                    peak_wind_speed_ms=projection.peak_wind_speed_ms,
                    max_daily_rainfall_mm=projection.max_daily_rainfall_mm,
                    max_temperature_c=projection.max_temperature_c,
                    max_wet_bulb_temperature_c=projection.max_wet_bulb_temperature_c,
                    intensity_wind=intensities["wind"],
                    intensity_flood=intensities["flood"],
                    intensity_heat=intensities["heat"],
                    stress_total=row["stress_total"],
                    damage_ratio=damage,
                    damage_ratio_lower=lower_damage,
                    damage_ratio_upper=upper_damage,
                    is_uninsurable=calculations.is_uninsurable(damage),
                    exceeds_survivability_limit=exceeds_survivability,
                )
            )

        crossing = calculations.first_crossing_year(damage_by_year)
        lower = calculations.first_crossing_year(lower_by_year)
        upper = calculations.first_crossing_year(upper_by_year)

        # The component decomposition is reported at the year that actually decides
        # the score, which is the year a reviewer will want to interrogate.
        focus_year = crossing if crossing is not None else constants.HORIZON_END_YEAR
        focus_index = next(
            index
            for index, (projection, _) in enumerate(per_year_context)
            if projection.year == focus_year
        )
        _, focus_stress = per_year_context[focus_index]

        by_component: dict[str, ResolvedMaterial] = {
            material.component: material for material in resolved
        }
        components = tuple(
            ComponentBreakdown(
                component=contribution.component,
                material_code=by_component[contribution.component].code,
                material_name=by_component[contribution.component].name,
                total=contribution.total,
                by_hazard=tuple(
                    HazardContribution(hazard=hazard, contribution=value)
                    for hazard, value in contribution.hazard_contributions.items()
                ),
            )
            for contribution in focus_stress.by_component
        )

        breakdown = ScoreBreakdown(
            uninsurable_damage_threshold=constants.UNINSURABLE_DAMAGE_RATIO,
            area_sq_ft=area_sq_ft,
            area_exposure_factor=area_factor,
            materials=resolved,
            components=components,
            years=tuple(years),
        )
        return breakdown, crossing, lower, upper

    @staticmethod
    def _intensities(projection: YearlyHazardProjection) -> dict[str, float]:
        """Normalise one year's projected hazards against their design references."""
        return {
            "wind": calculations.normalise_hazard_intensity(
                projection.peak_wind_speed_ms, constants.WIND_REFERENCE_MS
            ),
            "flood": calculations.normalise_hazard_intensity(
                projection.max_daily_rainfall_mm, constants.RAINFALL_REFERENCE_MM_PER_DAY
            ),
            "heat": calculations.normalise_hazard_intensity(
                projection.max_temperature_c, constants.HEAT_REFERENCE_MAX_TEMP_C
            ),
        }

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------
    async def _recommend(
        self, *, site_id: uuid.UUID, baseline: ScoreResponse
    ) -> tuple[MaterialRecommendation, ...]:
        """Suggest a better material for each component, where one exists."""
        catalogue = await self._materials.get_catalogue()
        peak = self._peak_intensities(baseline)

        current: dict[str, ResolvedMaterial] = {
            material.component: material for material in baseline.breakdown.materials
        }
        grouped = {
            "foundation": catalogue.foundation,
            "walls": catalogue.walls,
            "roofing": catalogue.roofing,
        }

        recommendations: list[MaterialRecommendation] = []
        for component in constants.BUILDING_COMPONENTS:
            candidates = [
                {
                    "code": entry.code,
                    "component": entry.component,
                    "resistance": {
                        "wind": entry.resistance.wind,
                        "flood": entry.resistance.flood,
                        "heat": entry.resistance.heat,
                    },
                    "relative_cost_index": entry.relative_cost_index,
                }
                for entry in grouped[component]
            ]
            if not candidates:
                continue

            ranked = self._ranker_model.rank(hazard_intensities=peak, candidates=candidates)
            best = ranked[0]
            existing = current[component]

            # Only recommend a genuine change. Suggesting the material already in
            # use would make the prove step look like it did something when it
            # did not.
            if best.code == existing.code:
                continue

            by_code = {entry.code: entry for entry in grouped[component]}
            recommendations.append(
                MaterialRecommendation(
                    component=component,
                    current_code=existing.code,
                    current_name=existing.name,
                    recommended_code=best.code,
                    recommended_name=by_code[best.code].name,
                    predicted_damage_reduction=best.predicted_damage_reduction,
                    relative_cost_index=best.relative_cost_index,
                    rationale=self._rationale(component, peak),
                )
            )

        return tuple(recommendations)

    @staticmethod
    def _peak_intensities(baseline: ScoreResponse) -> dict[str, float]:
        """Peak normalised intensity per hazard across the horizon.

        Recommendations are made against the worst year, not the average: a
        material chosen for typical conditions is the one that fails in the storm.
        """
        return {
            "wind": max(year.intensity_wind for year in baseline.breakdown.years),
            "flood": max(year.intensity_flood for year in baseline.breakdown.years),
            "heat": max(year.intensity_heat for year in baseline.breakdown.years),
        }

    @staticmethod
    def _rationale(component: str, peak: dict[str, float]) -> str:
        """Explain in one sentence why a component is being upgraded."""
        dominant = max(
            peak,
            key=lambda hazard: peak[hazard]
            * constants.COMPONENT_HAZARD_SENSITIVITY[component][hazard],
        )
        readable = {
            "wind": "peak wind loading",
            "flood": "extreme rainfall and flooding",
            "heat": "extreme heat",
        }[dominant]
        return (
            f"For this site the {component} is dominated by {readable}; this option "
            f"removes the most damage per unit of additional cost."
        )

    @staticmethod
    def _apply(
        selection: MaterialSelection, recommendations: tuple[MaterialRecommendation, ...]
    ) -> MaterialSelection:
        """Return the selection with every recommendation applied."""
        updated = selection.as_mapping()
        for recommendation in recommendations:
            updated[recommendation.component] = recommendation.recommended_code
        return MaterialSelection(**updated)

    # ------------------------------------------------------------------
    # Idempotency and mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _hash_inputs(
        *, site_id: uuid.UUID, selection: MaterialSelection, versions: dict[str, str]
    ) -> str:
        """Hash everything a score depends on.

        Model versions are included deliberately: after retraining, the same site
        and materials must produce a NEW score rather than silently replaying one
        computed by a superseded model.
        """
        payload = {
            "site_id": str(site_id),
            "materials": selection.as_mapping(),
            "versions": versions,
            # Bumped when the engine's own maths changes, so old scores are not
            # replayed under new logic.
            "engine_version": 1,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_response(record: ScoreRecord) -> ScoreResponse:
        """Map a stored score onto the API response shape."""
        return ScoreResponse(
            id=record.id,
            site_id=record.site_id,
            scenario=record.scenario,
            crossing_year=record.crossing_year,
            crossing_year_lower=record.crossing_year_lower,
            crossing_year_upper=record.crossing_year_upper,
            confidence=record.confidence_label,
            breakdown=ScoreBreakdown.model_validate(record.breakdown),
            damage_model_version=record.damage_model_version,
            material_model_version=record.material_model_version,
            created_at=record.created_at,
        )
