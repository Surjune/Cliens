"""FastAPI dependency wiring.

Routes declare which service they need; this module is the only place that knows
how to build one. Keeping construction here means a route never imports a
repository, which is what stops the layering being quietly bypassed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.ml.quality_score import QualityScoreModel
from app.ml.registry import get_registry
from app.repositories.knowledge_base import load_knowledge_base
from app.repositories.materials import MaterialRepository
from app.services.climate_data import ClimateDataService
from app.services.materials import MaterialService
from app.services.scoring import QualityScoringService

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_material_service(session: SessionDep) -> MaterialService:
    """Build the material service for one request."""
    return MaterialService(MaterialRepository(session))


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]


def get_climate_service() -> ClimateDataService:
    """Build the climate service.

    Backed entirely by the bundled GRIB-derived profiles, so it needs no session
    and makes no network call.
    """
    return ClimateDataService()


ClimateServiceDep = Annotated[ClimateDataService, Depends(get_climate_service)]


def get_scoring_service(climate: ClimateServiceDep) -> QualityScoringService:
    """Build the quality score engine for one request.

    The model registry is process-wide and loaded at startup, so this only wraps
    already-loaded artifacts — nothing is read from disk per request.
    """
    knowledge_base = load_knowledge_base()
    absorption = {
        item.id: item.max_water_absorption_percent for item in knowledge_base.masonry_properties
    }
    return QualityScoringService(
        climate=climate,
        model=QualityScoreModel(get_registry().quality, absorption),
        knowledge_base=knowledge_base,
    )


ScoringServiceDep = Annotated[QualityScoringService, Depends(get_scoring_service)]
