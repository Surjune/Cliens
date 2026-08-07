"""FastAPI dependency wiring.

Routes declare which service they need; this module is the only place that knows
how to build one. Keeping the construction here means a route never imports a
repository, which is what stops the layering from being quietly bypassed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.external.earth_engine import EarthEngineClient
from app.external.gemini import GeminiClient
from app.external.imd import IMDClient
from app.ml.damage_calibration import DamageCalibrationModel
from app.ml.material_ranker import MaterialRankerModel
from app.ml.registry import get_registry
from app.repositories.cache import ExternalCacheRepository
from app.repositories.materials import MaterialRepository
from app.repositories.reports import ReportRepository
from app.repositories.scores import ScoreRepository
from app.repositories.sites import SiteRepository
from app.services.climate_data import ClimateDataService
from app.services.materials import MaterialService
from app.services.reporting import ReportingService
from app.services.scoring import ScoringService
from app.services.sites import SiteService

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_site_service(session: SessionDep) -> SiteService:
    """Build the site service for one request."""
    return SiteService(SiteRepository(session))


SiteServiceDep = Annotated[SiteService, Depends(get_site_service)]


def get_climate_service(session: SessionDep, settings: SettingsDep) -> ClimateDataService:
    """Build the climate data service for one request.

    The external clients are cheap to construct and hold no connection state —
    Earth Engine's authentication is process-wide, not per-instance — so building
    them per request keeps the wiring simple without a per-request cost.
    """
    return ClimateDataService(
        earth_engine=EarthEngineClient(settings),
        imd=IMDClient(settings),
        cache=ExternalCacheRepository(session),
    )


ClimateServiceDep = Annotated[ClimateDataService, Depends(get_climate_service)]


def get_material_service(session: SessionDep) -> MaterialService:
    """Build the material service for one request."""
    return MaterialService(MaterialRepository(session))


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]


def get_scoring_service(
    session: SessionDep, settings: SettingsDep, climate: ClimateServiceDep
) -> ScoringService:
    """Build the score engine for one request.

    The model registry is process-wide and loaded at startup, so this only wraps
    the already-loaded artifacts — no model is read from disk per request.
    """
    registry = get_registry()
    return ScoringService(
        sites=SiteRepository(session),
        scores=ScoreRepository(session),
        materials=MaterialService(MaterialRepository(session)),
        climate=climate,
        damage_model=DamageCalibrationModel(registry.damage),
        ranker_model=MaterialRankerModel(registry.ranker),
    )


ScoringServiceDep = Annotated[ScoringService, Depends(get_scoring_service)]


def get_reporting_service(session: SessionDep, settings: SettingsDep) -> ReportingService:
    """Build the reporting service for one request."""
    return ReportingService(
        reports=ReportRepository(session),
        scores=ScoreRepository(session),
        gemini=GeminiClient(settings),
    )


ReportingServiceDep = Annotated[ReportingService, Depends(get_reporting_service)]
