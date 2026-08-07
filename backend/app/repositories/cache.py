"""Durable cache for external API responses, keyed by spatial and temporal parameters.

Two jobs, and the first is the important one:

1. **Determinism.** The brief requires that re-scoring the same site cannot drift
   because an upstream changed between calls. Replaying the stored response makes
   the score a pure function of its inputs, which is what makes it defensible in a
   permit context.
2. **Quota.** Earth Engine and Gemini both have free-tier limits that a handful of
   users could otherwise exhaust.

Cache keys are built here rather than by callers, so the same request always
resolves to the same key regardless of which service asks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import calculations, constants
from app.core.logging import get_logger
from app.repositories.models import ExternalResponseCache

logger = get_logger(__name__)


def build_location_cache_key(
    *,
    dataset: str,
    longitude: float,
    latitude: float,
    start_year: int,
    end_year: int,
) -> str:
    """Build the cache key for a location-and-period request.

    Coordinates are rounded to the configured precision so two sites a metre apart
    share one upstream response. That precision is far finer than any climate grid
    cell, so it cannot merge genuinely different climate conditions.

    The dataset identifier is part of the key: switching CMIP6 scenario or model
    set must produce a cache miss, not silently replay the previous scenario's
    numbers.
    """
    lon = calculations.round_coordinate(longitude)
    lat = calculations.round_coordinate(latitude)
    return f"{dataset}:{lon}:{lat}:{start_year}-{end_year}"


class ExternalCacheRepository:
    """Reads and writes cached third-party responses."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def get(self, *, service: str, cache_key: str) -> dict[str, Any] | None:
        """Return a live cached payload, or ``None`` on a miss or expiry.

        An expired row is left in place rather than deleted here; ``purge_expired``
        handles removal so a read stays a read.
        """
        statement = select(ExternalResponseCache.payload).where(
            ExternalResponseCache.service == service,
            ExternalResponseCache.cache_key == cache_key,
            ExternalResponseCache.expires_at > datetime.now(UTC),
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        payload: dict[str, Any] | None = row

        if payload is None:
            logger.info("external_cache_miss", service=service, cache_key=cache_key)
            return None

        logger.info("external_cache_hit", service=service, cache_key=cache_key)
        return payload

    async def put(
        self,
        *,
        service: str,
        cache_key: str,
        payload: dict[str, Any],
        ttl_days: int = constants.CACHE_TTL_DAYS,
    ) -> None:
        """Store a payload, replacing any existing entry for the same key.

        Uses an upsert rather than delete-then-insert so two requests racing on the
        same cold key cannot violate the uniqueness constraint.
        """
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)

        statement = (
            postgres_insert(ExternalResponseCache)
            .values(
                service=service,
                cache_key=cache_key,
                payload=payload,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="uq_external_cache_service_key",
                set_={"payload": payload, "expires_at": expires_at},
            )
        )
        await self._session.execute(statement)
        await self._session.flush()

        logger.info(
            "external_cache_stored",
            service=service,
            cache_key=cache_key,
            expires_at=expires_at.isoformat(),
        )

    async def purge_expired(self) -> int:
        """Delete every expired entry and return how many were removed."""
        statement = delete(ExternalResponseCache).where(
            ExternalResponseCache.expires_at <= datetime.now(UTC)
        )
        result = await self._session.execute(statement)
        await self._session.flush()

        removed = result.rowcount or 0
        logger.info("external_cache_purged", removed=removed)
        return removed
