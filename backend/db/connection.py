# Async PostgreSQL connection setup (asyncpg)
import asyncpg
import logging
from typing import Optional
from backend.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Module-level pool (one pool for the whole app lifetime) ──
_pool: Optional[asyncpg.Pool] = None


async def create_pool(database_url: Optional[str] = None) -> asyncpg.Pool:
    """
    Create and return an asyncpg connection pool.
    Uses DATABASE_URL from settings by default.
    Custom mode passes a user-supplied URL at runtime.
    """
    global _pool

    url = database_url or settings.DATABASE_URL

    if not url:
        raise ValueError(
            "No DATABASE_URL provided. "
            "Set it in .env (demo mode) or pass credentials (custom mode)."
        )

    # Strip SQLAlchemy-style prefix if present — asyncpg needs plain postgres://
    url = url.replace("postgresql+asyncpg://", "postgresql://")

    logger.info("Creating database connection pool...")

    _pool = await asyncpg.create_pool(
        dsn             = url,
        min_size        = settings.DB_POOL_MIN_SIZE,
        max_size        = settings.DB_POOL_MAX_SIZE,
        command_timeout = settings.DB_COMMAND_TIMEOUT,
    )

    logger.info("Database pool created successfully.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """
    Return the existing pool.
    Raises clearly if called before create_pool().
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. "
            "Call create_pool() during app startup."
        )
    return _pool


async def close_pool() -> None:
    """
    Gracefully close the pool on app shutdown.
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")


async def check_connection() -> bool:
    """
    Ping the DB — used for health checks.
    Returns True if reachable, False otherwise.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False