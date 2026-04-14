# Handles session retrieval and reset
import logging
from fastapi import APIRouter, HTTPException

from backend.models.response import SessionInfo
from backend.services.session_manager import (
    get_session_info,
    reset_session,
    delete_session,
    active_session_count,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["Session"])


# ── Routes ────────────────────────────────────────────────────

@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str) -> SessionInfo:
    """
    Returns metadata about a session —
    how many turns are stored and the questions asked so far.
    """
    info = get_session_info(session_id)

    if not info:
        raise HTTPException(
            status_code = 404,
            detail      = f"Session '{session_id}' not found.",
        )

    return SessionInfo(**info)


@router.delete("/{session_id}/reset")
async def reset_session_route(session_id: str) -> dict:
    """
    Clears conversation history for a session.
    The session remains active — history resets to empty.
    User can continue asking questions with a fresh context.
    """
    cleared = reset_session(session_id)

    if not cleared:
        raise HTTPException(
            status_code = 404,
            detail      = f"Session '{session_id}' not found.",
        )

    logger.info(f"Session '{session_id}' reset via API.")
    return {"reset": True, "session_id": session_id}


@router.delete("/{session_id}")
async def delete_session_route(session_id: str) -> dict:
    """
    Fully removes a session from memory.
    Used when a user closes the app or ends their custom mode session.
    """
    removed = delete_session(session_id)

    if not removed:
        raise HTTPException(
            status_code = 404,
            detail      = f"Session '{session_id}' not found.",
        )

    logger.info(f"Session '{session_id}' deleted via API.")
    return {"deleted": True, "session_id": session_id}


@router.get("")
async def list_sessions() -> dict:
    """
    Returns total number of active sessions.
    Lightweight monitoring endpoint — no sensitive data exposed.
    """
    return {"active_sessions": active_session_count()}