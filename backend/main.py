# Entry point for FastAPI application
import logging
import logging.config

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_settings
from backend.db.connection import create_pool, close_pool, check_connection
from backend.cache.schema_cache import get_cache_info, refresh_schema
from backend.api.middleware import RequestLoggingMiddleware, setup_cors
from backend.api.routes import query, schema, session
from backend.api.routes.explain import router as explain_router   # ← NEW

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger   = logging.getLogger(__name__)
settings = get_settings()


# ── App factory ───────────────────────────────────────────────
def create_app() -> FastAPI:

    app = FastAPI(
        title       = settings.APP_NAME,
        description = "Natural language to SQL — powered by Gemini",
        version     = "1.0.0",
        docs_url    = "/docs",
        redoc_url   = "/redoc",
    )

    # ── Middleware ────────────────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)
    setup_cors(app, settings.ALLOWED_ORIGINS)

    # ── Routers ───────────────────────────────────────────────
    app.include_router(query.router)
    app.include_router(schema.router)
    app.include_router(session.router)
    app.include_router(explain_router)   # ← NEW: POST /explain

    # ── Static frontend files ─────────────────────────────────
    app.mount(
        "/static",
        StaticFiles(directory="frontend"),
        name="static",
    )

    # ── Startup ───────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup():
        logger.info(f"Starting {settings.APP_NAME} in {settings.APP_MODE} mode...")

        await create_pool()
        logger.info("Database pool ready.")

        try:
            await refresh_schema()
            logger.info("Schema cache pre-warmed.")
        except Exception as e:
            logger.warning(f"Schema pre-warm failed (will retry on first request): {e}")

        logger.info(f"{settings.APP_NAME} startup complete.")


    # ── Shutdown ──────────────────────────────────────────────
    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("Shutting down — closing DB pool...")
        await close_pool()
        logger.info("Shutdown complete.")


    # ── Health check ──────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        db_ok      = await check_connection()
        cache_info = get_cache_info()
        cache_ok   = cache_info is not None

        status = "ok" if (db_ok and cache_ok) else "degraded"

        return {
            "status" : status,
            "db"     : db_ok,
            "cache"  : cache_ok,
            "version": "1.0.0",
            "mode"   : settings.APP_MODE,
        }


    # ── Frontend root ─────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse("frontend/index.html")


    return app


# ── Entry point ───────────────────────────────────────────────
app = create_app()