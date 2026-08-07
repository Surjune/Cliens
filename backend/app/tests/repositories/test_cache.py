"""Tests for the external response cache, against the real test database.

This cache is what makes ``/score`` deterministic, so its behaviour is verified
against PostgreSQL rather than a stub: the upsert relies on a named unique
constraint, and expiry relies on the database's own clock comparison.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import constants
from app.repositories.cache import ExternalCacheRepository, build_location_cache_key
from app.repositories.models import ExternalResponseCache

pytestmark = pytest.mark.integration

SERVICE = "earth_engine"
KEY = "NASA/GDDP-CMIP6:80.27:13.01:2025-2055"


@pytest.fixture
def repository(session: AsyncSession) -> ExternalCacheRepository:
    """A cache repository bound to the test session."""
    return ExternalCacheRepository(session)


class TestCacheKeyConstruction:
    """Keys decide what counts as "the same request"."""

    def test_is_deterministic(self) -> None:
        first = build_location_cache_key(
            dataset="d", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        second = build_location_cache_key(
            dataset="d", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        assert first == second

    def test_rounds_nearby_coordinates_together(self) -> None:
        """Sub-metre differences must not each trigger their own upstream call."""
        first = build_location_cache_key(
            dataset="d", longitude=80.270721, latitude=13.01, start_year=2025, end_year=2055
        )
        second = build_location_cache_key(
            dataset="d", longitude=80.2707214, latitude=13.01, start_year=2025, end_year=2055
        )
        assert first == second

    def test_distinguishes_genuinely_different_locations(self) -> None:
        first = build_location_cache_key(
            dataset="d", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        second = build_location_cache_key(
            dataset="d", longitude=80.37, latitude=13.01, start_year=2025, end_year=2055
        )
        assert first != second

    def test_distinguishes_datasets(self) -> None:
        """Changing CMIP6 scenario must miss, not replay the previous scenario."""
        ssp245 = build_location_cache_key(
            dataset="cmip6/ssp245", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        ssp585 = build_location_cache_key(
            dataset="cmip6/ssp585", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        assert ssp245 != ssp585

    def test_distinguishes_year_ranges(self) -> None:
        short = build_location_cache_key(
            dataset="d", longitude=80.27, latitude=13.01, start_year=2025, end_year=2030
        )
        full = build_location_cache_key(
            dataset="d", longitude=80.27, latitude=13.01, start_year=2025, end_year=2055
        )
        assert short != full


class TestRoundTrip:
    """Storing then reading must return exactly what went in."""

    async def test_stores_and_returns_a_payload(self, repository: ExternalCacheRepository) -> None:
        payload = {"records": [{"year": 2025, "tasmax": 310.5}], "scenario": "ssp245"}

        await repository.put(service=SERVICE, cache_key=KEY, payload=payload)
        result = await repository.get(service=SERVICE, cache_key=KEY)

        assert result == payload

    async def test_returns_none_on_a_miss(self, repository: ExternalCacheRepository) -> None:
        assert await repository.get(service=SERVICE, cache_key="never-stored") is None

    async def test_keys_are_scoped_per_service(self, repository: ExternalCacheRepository) -> None:
        """Two services must be able to use the same key without colliding."""
        await repository.put(service="earth_engine", cache_key=KEY, payload={"from": "ee"})
        await repository.put(service="imd", cache_key=KEY, payload={"from": "imd"})

        assert await repository.get(service="earth_engine", cache_key=KEY) == {"from": "ee"}
        assert await repository.get(service="imd", cache_key=KEY) == {"from": "imd"}

    async def test_preserves_nested_structures(self, repository: ExternalCacheRepository) -> None:
        """A cached response must be interpreted by the same code path as a fresh one."""
        payload = {
            "models": ["ACCESS-CM2", "MRI-ESM2-0"],
            "records": [{"year": 2025, "bands": {"pr": 0.001, "sfcWind": 12.0}}],
            "nested": {"deep": {"value": None}},
        }

        await repository.put(service=SERVICE, cache_key=KEY, payload=payload)

        assert await repository.get(service=SERVICE, cache_key=KEY) == payload


class TestUpsert:
    """Two requests racing on a cold key must not violate the unique constraint."""

    async def test_replaces_an_existing_entry(self, repository: ExternalCacheRepository) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={"version": 1})
        await repository.put(service=SERVICE, cache_key=KEY, payload={"version": 2})

        assert await repository.get(service=SERVICE, cache_key=KEY) == {"version": 2}

    async def test_does_not_create_a_duplicate_row(
        self, repository: ExternalCacheRepository, session: AsyncSession
    ) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={"version": 1})
        await repository.put(service=SERVICE, cache_key=KEY, payload={"version": 2})

        rows = (
            (
                await session.execute(
                    select(ExternalResponseCache).where(ExternalResponseCache.cache_key == KEY)
                )
            )
            .scalars()
            .all()
        )

        assert len(rows) == 1

    async def test_extends_the_expiry_on_replacement(
        self, repository: ExternalCacheRepository, session: AsyncSession
    ) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={"v": 1}, ttl_days=1)
        first_expiry = await _expiry_of(session, KEY)

        await repository.put(service=SERVICE, cache_key=KEY, payload={"v": 2}, ttl_days=30)
        second_expiry = await _expiry_of(session, KEY)

        assert second_expiry > first_expiry


class TestExpiry:
    """An expired entry must not be replayed as if it were live."""

    async def test_an_expired_entry_is_a_miss(
        self, repository: ExternalCacheRepository, session: AsyncSession
    ) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={"stale": True})
        await _force_expiry(session, KEY, datetime.now(UTC) - timedelta(seconds=1))

        assert await repository.get(service=SERVICE, cache_key=KEY) is None

    async def test_default_ttl_matches_the_configured_constant(
        self, repository: ExternalCacheRepository, session: AsyncSession
    ) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={})

        expiry = await _expiry_of(session, KEY)
        expected = datetime.now(UTC) + timedelta(days=constants.CACHE_TTL_DAYS)

        assert abs((expiry - expected).total_seconds()) < 60

    async def test_purge_removes_only_expired_entries(
        self, repository: ExternalCacheRepository, session: AsyncSession
    ) -> None:
        await repository.put(service=SERVICE, cache_key="live", payload={"keep": True})
        await repository.put(service=SERVICE, cache_key="dead", payload={"drop": True})
        await _force_expiry(session, "dead", datetime.now(UTC) - timedelta(days=1))

        removed = await repository.purge_expired()

        assert removed == 1
        assert await repository.get(service=SERVICE, cache_key="live") == {"keep": True}

    async def test_purge_on_a_clean_cache_removes_nothing(
        self, repository: ExternalCacheRepository
    ) -> None:
        await repository.put(service=SERVICE, cache_key=KEY, payload={})

        assert await repository.purge_expired() == 0


async def _expiry_of(session: AsyncSession, cache_key: str) -> datetime:
    """Read an entry's expiry directly, bypassing the repository."""
    statement = select(ExternalResponseCache.expires_at).where(
        ExternalResponseCache.cache_key == cache_key
    )
    return (await session.execute(statement)).scalar_one()


async def _force_expiry(session: AsyncSession, cache_key: str, when: datetime) -> None:
    """Backdate an entry's expiry, so expiry is tested without waiting for it."""
    entry = (
        await session.execute(
            select(ExternalResponseCache).where(ExternalResponseCache.cache_key == cache_key)
        )
    ).scalar_one()
    entry.expires_at = when
    await session.flush()
