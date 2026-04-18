# backend/api/routes/admin.py
# Internal monitoring endpoints — NOT for end users.
#
# These endpoints expose query logs, aggregate metrics, and
# active session counts for debugging and observability.
#
# In production you would protect these with an API key or
# IP allowlist. For now they are open (demo project only).

import logging
from fastapi import APIRouter, Query

from backend.services.query_logger import query_logger
from backend.services.session_manager import active_session_count, _sessions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ── GET /admin/logs ───────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    limit : int  = Query(default=50,  ge=1,  le=500, description="Max entries to return (most recent first)."),
    status: str  = Query(default="",         description="Filter by status: success | failed | rejected"),
    errors_only: bool = Query(default=False, description="Show only failed/rejected entries."),
) -> dict:
    """
    Returns recent query log entries, most recent first.

    Query params:
      - limit      : max entries (default 50, max 500)
      - status     : filter by success / failed / rejected
      - errors_only: shorthand for status != success
    """
    entries = query_logger.read_all(limit=max(limit, 500))

    # Apply filters
    if errors_only:
        entries = [e for e in entries if e.get("status") != "success"]
    elif status:
        entries = [e for e in entries if e.get("status") == status]

    # Cap after filtering
    entries = entries[:limit]

    logger.info(f"Admin: /logs returned {len(entries)} entries (limit={limit})")

    return {
        "count"  : len(entries),
        "entries": entries,
    }


# ── GET /admin/metrics ────────────────────────────────────────

@router.get("/metrics")
async def get_metrics() -> dict:
    """
    Returns aggregate metrics computed from the full log file.

    Includes:
      - total queries, success/failure/rejection counts
      - success rate (%)
      - average and p95 latency (total, LLM, DB)
      - top error stages
      - top warning codes
      - LLM fallback count
    """
    metrics = query_logger.compute_metrics()
    logger.info("Admin: /metrics requested.")
    return metrics


# ── GET /admin/sessions ───────────────────────────────────────

@router.get("/sessions")
async def get_sessions() -> dict:
    """
    Returns a summary of currently active in-memory sessions.

    Shows:
      - total active session count
      - per-session turn count and mode (credentials masked)
    """
    summaries = []

    for sid, session in _sessions.items():
        summaries.append({
            "session_id"  : sid,
            "turn_count"  : len(session.history),
            "has_custom_creds": bool(session.gemini_api_key),
        })

    return {
        "active_sessions": len(_sessions),
        "sessions"       : summaries,
    }


# ── GET /admin/health ─────────────────────────────────────────

@router.get("/health")
async def admin_health() -> dict:
    """
    Quick sanity check for the admin layer.
    Shows log file path and whether it exists.
    """
    log_file = query_logger.log_file
    return {
        "log_file"  : str(log_file),
        "log_exists": log_file.exists(),
        "log_size_kb": round(log_file.stat().st_size / 1024, 1) if log_file.exists() else 0,
    }