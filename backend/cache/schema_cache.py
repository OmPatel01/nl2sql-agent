# In-memory schema cache with hashing
import hashlib
import json
import logging
import time
from typing import Any, Optional

from backend.config import get_settings
from backend.db.schema_extractor import extract_schema, format_schema_for_prompt

logger   = logging.getLogger(__name__)
settings = get_settings()


# ── In-memory cache store ─────────────────────────────────────
# Supports multiple DB connections (demo + any custom sessions)
# keyed by database_url so they don't collide.

_cache: dict[str, dict[str, Any]] = {}

# Cache entry shape:
# {
#     "schema":      dict,   # raw extracted schema
#     "prompt_text": str,    # formatted for LLM prompt
#     "fingerprint": str,    # md5 hash of schema JSON
#     "timestamp":   float,  # time.time() of last refresh
#     "version":     int,    # increments on every refresh
# }


# ── Helpers ───────────────────────────────────────────────────

def _make_fingerprint(schema: dict[str, Any]) -> str:
    """MD5 hash of the schema dict — used to detect schema changes."""
    schema_json = json.dumps(schema, sort_keys=True)
    return hashlib.md5(schema_json.encode()).hexdigest()


def _is_expired(entry: dict[str, Any]) -> bool:
    """Returns True if the cache entry is older than TTL."""
    age = time.time() - entry["timestamp"]
    return age > settings.SCHEMA_CACHE_TTL_SECS


def _cache_key(database_url: Optional[str] = None) -> str:
    """Consistent cache key — hashed URL so credentials aren't stored as plaintext keys."""
    url = database_url or settings.DATABASE_URL
    return hashlib.md5(url.encode()).hexdigest()


# ── Public API ────────────────────────────────────────────────

async def get_schema(database_url: Optional[str] = None) -> dict[str, Any]:
    """
    Returns cached schema if fresh.
    Automatically refreshes if expired or not yet loaded.
    """
    key = _cache_key(database_url)

    if key in _cache and not _is_expired(_cache[key]):
        logger.debug("Schema cache hit.")
        return _cache[key]["schema"]

    logger.info("Schema cache miss or expired — refreshing.")
    return await refresh_schema(database_url)


async def get_schema_prompt_text(database_url: Optional[str] = None) -> str:
    """
    Returns the LLM-ready formatted schema string.
    Refreshes cache if needed.
    """
    key = _cache_key(database_url)

    if key in _cache and not _is_expired(_cache[key]):
        return _cache[key]["prompt_text"]

    await refresh_schema(database_url)
    return _cache[key]["prompt_text"]


async def refresh_schema(database_url: Optional[str] = None) -> dict[str, Any]:
    """
    Forces a fresh schema extraction from the DB.
    Updates cache only if schema has changed (fingerprint check).
    Returns the fresh schema dict.
    """
    key     = _cache_key(database_url)
    schema  = await extract_schema()
    new_fp  = _make_fingerprint(schema)

    # If schema unchanged, just reset the timestamp (no version bump)
    if key in _cache and _cache[key]["fingerprint"] == new_fp:
        logger.info("Schema unchanged — resetting TTL only.")
        _cache[key]["timestamp"] = time.time()
        return schema

    # Schema changed (or first load) — full cache update
    version = (_cache[key]["version"] + 1) if key in _cache else 1

    _cache[key] = {
        "schema":      schema,
        "prompt_text": format_schema_for_prompt(schema),
        "fingerprint": new_fp,
        "timestamp":   time.time(),
        "version":     version,
    }

    logger.info(f"Schema cache updated — version {version}, fingerprint {new_fp[:8]}.")
    return schema


def get_cache_info(database_url: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Returns metadata about the current cache entry.
    Used by the /schema endpoint to show last refresh time and version.
    Returns None if cache is empty for this DB.
    """
    key = _cache_key(database_url)

    if key not in _cache:
        return None

    entry = _cache[key]
    age   = time.time() - entry["timestamp"]

    return {
        "version":          entry["version"],
        "fingerprint":      entry["fingerprint"],
        "cached_at":        entry["timestamp"],
        "age_seconds":      round(age),
        "ttl_seconds":      settings.SCHEMA_CACHE_TTL_SECS,
        "expires_in":       max(0, round(settings.SCHEMA_CACHE_TTL_SECS - age)),
        "is_expired":       _is_expired(entry),
        "table_count":      len(entry["schema"]["tables"]),
    }


def clear_cache(database_url: Optional[str] = None) -> None:
    """Removes cache entry for a given DB. Used on session reset."""
    key = _cache_key(database_url)
    if key in _cache:
        del _cache[key]
        logger.info("Schema cache cleared.")