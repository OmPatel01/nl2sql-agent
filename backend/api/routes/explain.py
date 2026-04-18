# backend/api/routes/explain.py
# Handles POST /explain — on-demand SQL explanation
#
# This route is intentionally separate from POST /query.
# Explanation is generated ONLY when the user explicitly clicks
# the "Explain" button, avoiding unnecessary LLM calls on every query.

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from backend.config import get_settings, AppMode
from backend.llm.gemini_provider import GeminiProvider
from backend.services.nl_to_sql import NLToSQLService
from backend.services.session_manager import get_session_credentials

logger   = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/explain", tags=["Explain"])


class ExplainRequest(BaseModel):
    """Payload for POST /explain"""
    question  : str = Field(..., description="The original natural language question.")
    sql       : str = Field(..., description="The generated SQL to explain.")
    session_id: str = Field(..., description="Session ID (used to resolve credentials in custom mode).")
    mode      : Optional[str] = Field(default="demo", description="demo | custom")


class ExplainResponse(BaseModel):
    """Response for POST /explain"""
    explanation: str = Field(..., description="Plain-English explanation of what the SQL does.")


# ── Shared demo instance ──────────────────────────────────────
_demo_gemini: Optional[GeminiProvider] = None


def _get_demo_gemini() -> GeminiProvider:
    global _demo_gemini
    if _demo_gemini is None:
        _demo_gemini = GeminiProvider()
        logger.info("Explain route: demo GeminiProvider initialised.")
    return _demo_gemini


# ── Route ─────────────────────────────────────────────────────

@router.post("", response_model=ExplainResponse)
async def explain_query(body: ExplainRequest) -> ExplainResponse:
    """
    Generates a plain-English explanation of a generated SQL query.

    Called ONLY when the user explicitly clicks the "Explain" button.
    Never called automatically during query execution — this keeps
    LLM costs low by avoiding explanations nobody asked for.

    Returns a single sentence describing what the SQL does,
    written for a non-technical audience.
    """
    if not body.question or not body.sql:
        raise HTTPException(
            status_code=400,
            detail="Both 'question' and 'sql' fields are required."
        )

    # ── Resolve Gemini provider ───────────────────────────────
    if body.mode == "custom":
        creds = get_session_credentials(body.session_id)
        if not creds:
            raise HTTPException(
                status_code=401,
                detail="Session credentials not found. Call /session/init first."
            )
        _, gemini_api_key = creds
        gemini = GeminiProvider(api_key=gemini_api_key)
    else:
        gemini = _get_demo_gemini()

    # ── Build NLToSQLService and generate explanation ─────────
    nl_to_sql = NLToSQLService(
        gemini=gemini,
        database_url=None  # explanation doesn't need DB access
    )

    try:
        explanation = await nl_to_sql.explain(body.question, body.sql)
    except Exception as e:
        logger.error(f"Explanation generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not generate explanation. Please try again."
        )

    if not explanation:
        explanation = "This query retrieves data from the database based on your question."

    logger.info(f"Explanation generated for session={body.session_id}")

    return ExplainResponse(explanation=explanation)