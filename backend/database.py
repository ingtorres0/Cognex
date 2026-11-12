"""Async SQLAlchemy engine and session factory.

The application starts even when Postgres is down. Callers check
``ping_database`` / ``ensure_schema`` and surface a disconnected state to the
dashboard instead of crashing the process on a transient outage.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session and roll back if the request fails."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ensure_schema() -> tuple[bool, str | None]:
    """Create tables when they are missing. Safe to call repeatedly."""
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return True, None
    except Exception as exc:
        logger.debug("Schema setup failed", exc_info=True)
        return False, str(exc)


async def ping_database() -> tuple[bool, str | None]:
    """Return whether a round-trip to Postgres succeeded."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:
        logger.debug("Database ping failed", exc_info=True)
        return False, str(exc)


async def dispose_engine() -> None:
    """Close the pool during application shutdown."""
    await engine.dispose()
