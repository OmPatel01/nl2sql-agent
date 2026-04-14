# Handles GET /schema and POST /schema/refresh
import logging
from fastapi import APIRouter, HTTPException

from backend.models.request import SchemaRefreshRequest
from backend.models.response import SchemaResponse
from backend.services.schema_service import SchemaService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schema", tags=["Schema"])

_demo_schema = None


def _get_demo_schema() -> SchemaService:
    global _demo_schema
    if _demo_schema is None:
        _demo_schema = SchemaService()
    return _demo_schema


# ── Routes ────────────────────────────────────────────────────

@router.get("", response_model=SchemaResponse)
async def get_schema() -> SchemaResponse:
    """
    Returns the current cached schema metadata.
    Shows tables, columns, PKs, FKs, cache version and expiry.
    """
    try:
        return await _get_demo_schema().get_schema_response()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/refresh")
async def refresh_schema(body: SchemaRefreshRequest) -> dict:
    """
    Forces a fresh schema extraction from the database.
    Returns a summary of what changed.
    """
    try:
        result = await _get_demo_schema().refresh()
        logger.info(f"Schema refreshed via API: {result}")
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))