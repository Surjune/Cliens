"""Tests for the score engine, against the real trained models and test database.

The climate service is stubbed so hazard projections can be dialled to exact
values — that is the only way to test the engine at minimum risk, maximum risk and
both horizon boundaries, which the brief requires. Everything else is real: real
material catalogue, real damage model, real persistence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import constants
from app.core.exceptions import ResourceNotFoundError, UnknownMaterialError
from app.ml.damage_calibration import DamageCalibrationModel
from app.ml.material_ranker import MaterialRankerModel
from app.ml.registry import get_registry
from app.repositories.materials import MaterialRepository
from app.repositories.scores import ScoreRepository
from app.repositories.sites import SiteRepository
from app.schemas.climate import ClimateProfile, DataProvenance, YearlyHazardProjection
from app.schemas.common import Centroid
from app.schemas.materials import MaterialSelection
from app.services.materials import MaterialService
from app.services.scoring import ScoringService

pytestmark = pytest.mark.integration

WEAK_BUILD = MaterialSelection(
    foundation="shallow_strip_footing_masonry",
    walls="fired_clay_brick_masonry",
    roofing="gi_sheet_roof",
)
STRONG_BUILD = MaterialSelection(
    foundation="rcc_pile_elevated",
    walls="rcc_shear_wall",
    roofing="rcc_sloped_slab",
)


class StubClimate:
    """A climate service returning projections the test dictates exactly."""

    def __init__(
        self,
        *,
        wind_ms: float,
        rainfall_mm: float,
        temperature_c: float,
        wet_bulb_c: float = 20.0,
        ramp: bool = False,
    ) -> None:
        self.wind_ms = wind_ms
        self.rainfall_mm = rainfall_mm
        self.temperature_c = temperature_c
        self.wet_bulb_c = wet_bulb_c
        self.ramp = ramp
        self.call_count = 0

    async def get_profile(self, *, longitude: float, latitude: float) -> ClimateProfile:
        self.call_count += 1
        projections = []
        span = len(constants.HORIZON_YEARS) - 1
        for index, year in enumerate(constants.HORIZON_YEARS):
            # A ramp lets a crossing land partway through the horizon instead of
            # at one extreme.
            factor = (index / span) if self.ramp else 1.0
            projections.append(
                YearlyHazardProjection(
                    year=year,
                    peak_wind_speed_ms=self.wind_ms * factor,
                    max_daily_rainfall_mm=self.rainfall_mm * factor,
                    max_temperature_c=self.temperature_c * factor,
                    max_wet_bulb_temperature_c=self.wet_bulb_c,
                )
            )
        return ClimateProfile(
            centroid=Centroid(longitude=longitude, latitude=latitude),
            projections=tuple(projections),
            historical=None,
            provenance=(
                DataProvenance(
                    service="earth_engine",
                    dataset="test",
                    retrieved_at=datetime.now(UTC),
                    served_from_cache=False,
                    notes=None,
                ),
            ),
        )


async def build_service(session: AsyncSession, climate: StubClimate) -> ScoringService:
    """Wire the engine with real collaborators and a stubbed climate source."""
    registry = get_registry()
    return ScoringService(
        sites=SiteRepository(session),
        scores=ScoreRepository(session),
        materials=MaterialService(MaterialRepository(session)),
        climate=climate,  # type: ignore[arg-type]  # structural stand-in
        damage_model=DamageCalibrationModel(registry.damage),
        ranker_model=MaterialRankerModel(registry.ranker),
    )


async def create_site(session: AsyncSession, area_sq_ft: float = 2000.0) -> uuid.UUID:
    """Insert a site directly, bypassing HTTP."""
    record = await SiteRepository(session).create(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [80.27, 13.01],
                    [80.2704, 13.01],
                    [80.2704, 13.0104],
                    [80.27, 13.0104],
                    [80.27, 13.01],
                ]
            ],
        },
        area_sq_ft=area_sq_ft,
        centroid_longitude=80.2702,
        centroid_latitude=13.0102,
        label="Test site",
    )
    return record.id


def calm_climate() -> StubClimate:
    """Benign conditions well below every design reference."""
    return StubClimate(wind_ms=5.0, rainfall_mm=10.0, temperature_c=28.0)


def severe_climate() -> StubClimate:
    """Conditions at or beyond every design reference."""
    return StubClimate(wind_ms=90.0, rainfall_mm=450.0, temperature_c=48.0)


class TestScoreBoundaries:
    """Minimum risk, maximum risk, and both horizon boundaries."""

    async def test_minimum_risk_never_crosses(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """A calm site with strong materials must survive the horizon."""
        service = await build_service(session, calm_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=STRONG_BUILD)

        assert score.crossing_year is None
        assert not any(year.is_uninsurable for year in score.breakdown.years)

    async def test_maximum_risk_crosses_in_the_first_year(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """Extreme hazards with the weakest build cross immediately."""
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert score.crossing_year == constants.HORIZON_START_YEAR

    async def test_covers_every_year_of_the_horizon(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, calm_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        years = [year.year for year in score.breakdown.years]
        assert years[0] == constants.HORIZON_START_YEAR
        assert years[-1] == constants.HORIZON_END_YEAR
        assert years == sorted(years)
        assert len(years) == len(constants.HORIZON_YEARS)

    async def test_a_rising_hazard_crosses_partway_through(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """The interesting case: a year strictly inside the horizon."""
        climate = StubClimate(wind_ms=95.0, rainfall_mm=430.0, temperature_c=47.0, ramp=True)
        service = await build_service(session, climate)
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert score.crossing_year is not None
        assert constants.HORIZON_START_YEAR < score.crossing_year <= constants.HORIZON_END_YEAR


class TestMaterialsMoveTheScore:
    """The product's central claim: better materials buy years."""

    async def test_stronger_materials_never_score_worse(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        climate = StubClimate(wind_ms=95.0, rainfall_mm=430.0, temperature_c=47.0, ramp=True)
        service = await build_service(session, climate)
        site_id = await create_site(session)

        weak = await service.score(site_id=site_id, selection=WEAK_BUILD)
        strong = await service.score(site_id=site_id, selection=STRONG_BUILD)

        weak_year = weak.crossing_year or constants.HORIZON_END_YEAR + 1
        strong_year = strong.crossing_year or constants.HORIZON_END_YEAR + 1
        assert strong_year >= weak_year

    async def test_prove_moves_the_year_later_and_explains_why(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        climate = StubClimate(wind_ms=95.0, rainfall_mm=430.0, temperature_c=47.0, ramp=True)
        service = await build_service(session, climate)
        site_id = await create_site(session)

        result = await service.prove(site_id=site_id, selection=WEAK_BUILD)

        assert result.recommendations
        assert all(r.rationale for r in result.recommendations)
        baseline_year = result.baseline.crossing_year or constants.HORIZON_END_YEAR + 1
        improved_year = result.improved.crossing_year or constants.HORIZON_END_YEAR + 1
        assert improved_year >= baseline_year

    async def test_prove_never_recommends_the_material_already_in_use(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """Otherwise the prove step looks like it acted when it did not."""
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        result = await service.prove(site_id=site_id, selection=WEAK_BUILD)

        for recommendation in result.recommendations:
            assert recommendation.recommended_code != recommendation.current_code


class TestSurvivabilityOverride:
    """No material choice defeats a wet-bulb temperature above 35 °C."""

    async def test_wet_bulb_above_the_limit_forces_uninsurability(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        climate = StubClimate(
            wind_ms=5.0,
            rainfall_mm=10.0,
            temperature_c=28.0,
            wet_bulb_c=constants.WET_BULB_SURVIVABILITY_LIMIT_C + 1.0,
        )
        service = await build_service(session, climate)
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=STRONG_BUILD)

        assert score.crossing_year == constants.HORIZON_START_YEAR
        assert all(year.exceeds_survivability_limit for year in score.breakdown.years)

    async def test_below_the_limit_does_not_trigger_the_override(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, calm_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=STRONG_BUILD)

        assert not any(year.exceeds_survivability_limit for year in score.breakdown.years)


class TestDeterminism:
    """`/score` must be a pure function of its inputs."""

    async def test_identical_inputs_return_the_identical_stored_score(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        climate = severe_climate()
        service = await build_service(session, climate)
        site_id = await create_site(session)

        first = await service.score(site_id=site_id, selection=WEAK_BUILD)
        second = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert first.id == second.id
        assert first.crossing_year == second.crossing_year
        # The second call was served from storage, so the climate source was not
        # consulted again — which is what guarantees no drift.
        assert climate.call_count == 1

    async def test_different_materials_produce_a_different_score(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        weak = await service.score(site_id=site_id, selection=WEAK_BUILD)
        strong = await service.score(site_id=site_id, selection=STRONG_BUILD)

        assert weak.id != strong.id


class TestAuditability:
    """The number has to be defensible, not just correct."""

    async def test_breakdown_reports_every_component_and_its_material(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        components = {c.component: c for c in score.breakdown.components}
        assert set(components) == set(constants.BUILDING_COMPONENTS)
        assert components["roofing"].material_code == WEAK_BUILD.roofing

    async def test_breakdown_reports_hazard_contributions(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        roofing = next(c for c in score.breakdown.components if c.component == "roofing")
        hazards = {h.hazard for h in roofing.by_hazard}
        assert hazards == set(constants.HAZARDS)

    async def test_every_year_carries_an_uncertainty_interval(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """The brief forbids presenting a point estimate as certain."""
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        for year in score.breakdown.years:
            assert year.damage_ratio_lower <= year.damage_ratio <= year.damage_ratio_upper

    async def test_records_the_model_versions_that_produced_it(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """An old score stays interpretable only if its artifacts are named."""
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert "damage_calibration" in score.damage_model_version
        assert "material_ranker" in score.material_model_version

    async def test_reports_the_threshold_it_judged_against(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, severe_climate())
        site_id = await create_site(session)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert score.breakdown.uninsurable_damage_threshold == (constants.UNINSURABLE_DAMAGE_RATIO)


class TestFailureModes:
    """Bad input fails loudly."""

    async def test_unknown_site_raises_not_found(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, calm_climate())

        with pytest.raises(ResourceNotFoundError):
            await service.score(site_id=uuid.uuid4(), selection=WEAK_BUILD)

    async def test_unknown_material_raises_before_any_climate_call(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        """Validation must precede the expensive upstream call."""
        climate = calm_climate()
        service = await build_service(session, climate)
        site_id = await create_site(session)

        bad = MaterialSelection(
            foundation="shallow_strip_footing_masonry",
            walls="unobtainium_panel",
            roofing="gi_sheet_roof",
        )
        with pytest.raises(UnknownMaterialError):
            await service.score(site_id=site_id, selection=bad)

        assert climate.call_count == 0


class TestAreaEffect:
    """Footprint scales exposure, but weakly."""

    async def test_a_larger_footprint_never_scores_later(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        climate = StubClimate(wind_ms=95.0, rainfall_mm=430.0, temperature_c=47.0, ramp=True)
        service = await build_service(session, climate)

        small = await create_site(session, area_sq_ft=500.0)
        large = await create_site(session, area_sq_ft=50_000.0)

        small_score = await service.score(site_id=small, selection=WEAK_BUILD)
        large_score = await service.score(site_id=large, selection=WEAK_BUILD)

        small_year = small_score.crossing_year or constants.HORIZON_END_YEAR + 1
        large_year = large_score.crossing_year or constants.HORIZON_END_YEAR + 1
        assert large_year <= small_year

    async def test_area_factor_is_reported_in_the_breakdown(
        self, session: AsyncSession, seeded_catalogue: None
    ) -> None:
        service = await build_service(session, calm_climate())
        site_id = await create_site(session, area_sq_ft=constants.REFERENCE_FLOOR_AREA_SQ_FT)

        score = await service.score(site_id=site_id, selection=WEAK_BUILD)

        assert score.breakdown.area_exposure_factor == pytest.approx(1.0)
