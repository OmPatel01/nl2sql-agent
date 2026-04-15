# Configuration and environment variables
# Configuration and environment variables
from pydantic_settings import BaseSettings
from functools import lru_cache
from enum import Enum


class AppMode(str, Enum):
    DEMO   = "demo"
    CUSTOM = "custom"


class Settings(BaseSettings):

    # ── App ──────────────────────────────────────────────────
    APP_NAME  : str     = "NL to SQL"
    DEBUG     : bool    = False
    APP_MODE  : AppMode = AppMode.DEMO

    # ── Database ─────────────────────────────────────────────
    # Demo mode uses this directly.
    # Custom mode: user supplies credentials at runtime via API.
    DATABASE_URL          : str = ""          # postgres+asyncpg://user:pass@host:port/db
    DB_POOL_MIN_SIZE      : int = 2
    DB_POOL_MAX_SIZE      : int = 10
    DB_COMMAND_TIMEOUT    : int = 30          # seconds

    # ── Gemini ───────────────────────────────────────────────
    GEMINI_API_KEY        : str = ""
    # Updated to the currently supported model (April 2026)
    GEMINI_MODEL          : str = "gemini-2.5-flash"
    GEMINI_MAX_TOKENS     : int = 1024
    GEMINI_TEMPERATURE    : float = 0.0       # deterministic SQL generation

    # ── Gemini Reliability ───────────────────────────────────
    GEMINI_MAX_RETRIES       : int = 3
    GEMINI_RETRY_BASE_DELAY  : int = 1   # seconds (exponential backoff)
    GEMINI_FALLBACK_MODEL    : str = "gemini-2.0-flash-lite"

    # ── Schema cache ─────────────────────────────────────────
    SCHEMA_CACHE_TTL_SECS : int = 3600        # auto-refresh every 1 hour

    # ── Session ──────────────────────────────────────────────
    SESSION_MAX_HISTORY   : int = 5           # last N query/response pairs kept

    # ── SQL guardrails ───────────────────────────────────────
    MAX_RESULT_ROWS       : int = 500         # cap rows returned to frontend

    # ── CORS ─────────────────────────────────────────────────
    ALLOWED_ORIGINS       : list[str] = ["*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()