# Maintains short query history in memory
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from backend.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class Turn:
    """A single conversation turn — one question and its generated SQL."""
    question: str
    sql     : str


@dataclass
class Session:
    """Holds conversation history + user credentials for custom mode."""
    session_id    : str
    database_url  : Optional[str] = None     # ← ADD THIS
    gemini_api_key: Optional[str] = None     # ← ADD THIS
    history       : deque = field(...)

# Update get_session_info to return credentials
def get_session_credentials(session_id: str) -> Optional[tuple[str, str]]:
    """Returns (database_url, gemini_api_key) or None."""
    if session_id not in _sessions:
        return None
    
    session = _sessions[session_id]
    if session.database_url and session.gemini_api_key:
        return (session.database_url, session.gemini_api_key)
    
    return None

# Store credentials
def set_session_credentials(
    session_id: str, 
    database_url: str, 
    gemini_api_key: str
) -> None:
    """Stores credentials for a session."""
    if session_id not in _sessions:
        _sessions[session_id] = Session(session_id=session_id)
    
    _sessions[session_id].database_url   = database_url
    _sessions[session_id].gemini_api_key = gemini_api_key
    logger.info(f"Credentials stored for session {session_id}")


# ── Module-level session store ────────────────────────────────
# Keyed by session_id (client-generated UUID).
# Lives in memory — resets on server restart (by design for this app).

_sessions: dict[str, Session] = {}


# ── Public API ────────────────────────────────────────────────

def get_history(session_id: str) -> list[dict]:
    """
    Returns the conversation history for a session as a list of dicts.
    Each dict has keys: 'question', 'sql'.
    Returns an empty list if session does not exist yet.
    Used by NLToSQLService to inject history into the prompt.
    """
    if session_id not in _sessions:
        return []

    return [
        {"question": turn.question, "sql": turn.sql}
        for turn in _sessions[session_id].history
    ]


def add_turn(session_id: str, question: str, sql: str) -> None:
    """
    Appends a completed question + SQL pair to the session history.
    Creates the session automatically if it does not exist.
    Old turns beyond SESSION_MAX_HISTORY are dropped automatically.
    """
    if session_id not in _sessions:
        _sessions[session_id] = Session(session_id=session_id)
        logger.info(f"New session created: {session_id}")

    turn = Turn(question=question, sql=sql)
    _sessions[session_id].history.append(turn)

    logger.debug(
        f"Session '{session_id}' — turn added. "
        f"History length: {len(_sessions[session_id].history)}"
    )


def get_session_info(session_id: str) -> Optional[dict]:
    """
    Returns metadata about a session.
    Used by GET /session endpoint.
    Returns None if session does not exist.
    """
    if session_id not in _sessions:
        return None

    session = _sessions[session_id]

    return {
        "session_id"   : session_id,
        "history_count": len(session.history),
        "questions"    : [turn.question for turn in session.history],
    }


def reset_session(session_id: str) -> bool:
    """
    Clears history for a session.
    Returns True if session existed and was cleared, False if not found.
    Called by DELETE /session/reset.
    """
    if session_id not in _sessions:
        logger.warning(f"Reset requested for unknown session: {session_id}")
        return False

    _sessions[session_id].history.clear()
    logger.info(f"Session '{session_id}' history cleared.")
    return True


def delete_session(session_id: str) -> bool:
    """
    Fully removes a session from memory.
    Called when a custom mode user disconnects or closes the app.
    """
    if session_id not in _sessions:
        return False

    del _sessions[session_id]
    logger.info(f"Session '{session_id}' deleted.")
    return True


def active_session_count() -> int:
    """Returns total number of active sessions — used in health/monitoring."""
    return len(_sessions)