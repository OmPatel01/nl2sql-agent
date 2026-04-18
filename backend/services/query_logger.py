# backend/services/query_logger.py
# Structured per-request logging for the NL-to-SQL pipeline.
#
# Design decisions:
#   - One JSON object per line (JSONL) → easy to tail, grep, or parse
#   - File append is atomic enough for single-process usage
#   - Never raises — logging failure must NEVER break the main pipeline
#   - Called via FastAPI BackgroundTasks so it runs after the response is sent

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from backend.config import get_settings

logger = logging.getLogger(__name__)

# ── Log file location ─────────────────────────────────────────
# Relative to wherever the server process runs (project root).
# Override via LOG_FILE env var if needed.
settings = get_settings()
LOG_DIR  = Path(settings.LOG_DIR)
LOG_FILE = LOG_DIR / "query_logs.jsonl"


# ── LogEntry — one record per query request ───────────────────

@dataclass
class LogEntry:
    # ── Identity ──────────────────────────────────────────────
    session_id    : str
    mode          : str                   # "demo" | "custom"
    timestamp     : float = field(default_factory=time.time)

    # ── Question ──────────────────────────────────────────────
    question      : str   = ""

    # ── Outcome ───────────────────────────────────────────────
    status        : str   = "unknown"     # "success" | "failed" | "rejected"
    generated_sql : Optional[str] = None
    error         : Optional[str] = None
    error_stage   : Optional[str] = None  # which step failed

    # ── Results ───────────────────────────────────────────────
    row_count     : int  = 0
    truncated     : bool = False

    # ── Warnings ──────────────────────────────────────────────
    warning_codes : list[str] = field(default_factory=list)

    # ── Latency breakdown (seconds) ───────────────────────────
    latency_total       : Optional[float] = None
    latency_classify    : Optional[float] = None
    latency_generate    : Optional[float] = None
    latency_execute     : Optional[float] = None

    # ── LLM metadata ─────────────────────────────────────────
    fallback_used : bool = False          # True if retry/fallback model was used

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── QueryLogger ───────────────────────────────────────────────

class QueryLogger:
    """
    Writes one JSONL line per query to logs/query_logs.jsonl.

    Usage:
        # Build the entry during request handling:
        entry = LogEntry(session_id=..., mode=..., question=...)
        entry.status = "success"
        entry.row_count = 10

        # Fire-and-forget AFTER returning the response:
        background_tasks.add_task(query_logger.write, entry)

    Never raises — a logging failure is caught and emitted to
    the application logger only, never surfaced to the user.
    """

    def __init__(self, log_file: Path = LOG_FILE):
        self.log_file = log_file
        self._ensure_dir()
        print(f"LOG FILE PATH: {self.log_file}")

    def _ensure_dir(self) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"QueryLogger: could not create log directory: {e}")

    def write(self, entry: LogEntry) -> None:
        """
        Appends a single JSON line to the log file.
        Safe to call from BackgroundTasks — never raises.
        """
        try:
            line = json.dumps(entry.to_dict(), default=str)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            logger.debug(
                f"Logged query | session={entry.session_id} "
                f"status={entry.status} latency={entry.latency_total:.2f}s"
                if entry.latency_total else
                f"Logged query | session={entry.session_id} status={entry.status}"
            )
        except Exception as e:
            # Logging must never crash the app
            logger.error(f"QueryLogger.write() failed silently: {e}")

    # ── Read helpers (used by /admin routes) ──────────────────

    def read_all(self, limit: int = 200) -> list[dict[str, Any]]:
        """
        Reads up to `limit` most-recent log entries.
        Returns an empty list if the file doesn't exist yet.
        """
        if not self.log_file.exists():
            return []

        try:
            lines = self.log_file.read_text(encoding="utf-8").splitlines()
            # Most recent first
            recent = lines[-limit:] if len(lines) > limit else lines
            entries = []
            for line in reversed(recent):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # skip malformed lines
            return entries
        except Exception as e:
            logger.error(f"QueryLogger.read_all() failed: {e}")
            return []

    def compute_metrics(self) -> dict[str, Any]:
        """
        Scans the full log file and returns aggregate metrics.
        Designed for the /admin/metrics endpoint.
        """
        if not self.log_file.exists():
            return _empty_metrics()

        try:
            lines = self.log_file.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.error(f"QueryLogger.compute_metrics() failed: {e}")
            return _empty_metrics()

        total         = 0
        successes     = 0
        failures      = 0
        rejections    = 0
        latencies     = []
        llm_latencies = []
        db_latencies  = []
        error_counts: dict[str, int] = {}
        warning_counts: dict[str, int] = {}
        fallback_used = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            status = e.get("status", "unknown")

            if status == "success":
                successes += 1
            elif status == "rejected":
                rejections += 1
            else:
                failures += 1

            if e.get("latency_total") is not None:
                latencies.append(e["latency_total"])
            if e.get("latency_generate") is not None:
                llm_latencies.append(e["latency_generate"])
            if e.get("latency_execute") is not None:
                db_latencies.append(e["latency_execute"])

            if e.get("error_stage"):
                stage = e["error_stage"]
                error_counts[stage] = error_counts.get(stage, 0) + 1

            for code in e.get("warning_codes", []):
                warning_counts[code] = warning_counts.get(code, 0) + 1

            if e.get("fallback_used"):
                fallback_used += 1

        def _avg(lst): return round(sum(lst) / len(lst), 3) if lst else None
        def _p95(lst):
            if not lst: return None
            s = sorted(lst)
            return round(s[int(len(s) * 0.95)], 3)

        success_rate = round(successes / total * 100, 1) if total else 0

        return {
            "total_queries"   : total,
            "successes"       : successes,
            "failures"        : failures,
            "rejections"      : rejections,
            "success_rate_pct": success_rate,
            "latency": {
                "avg_total_s"   : _avg(latencies),
                "p95_total_s"   : _p95(latencies),
                "avg_llm_s"     : _avg(llm_latencies),
                "avg_db_s"      : _avg(db_latencies),
            },
            "top_error_stages"  : _top(error_counts, 5),
            "top_warnings"      : _top(warning_counts, 5),
            "llm_fallback_count": fallback_used,
        }


# ── Helpers ───────────────────────────────────────────────────

def _top(counts: dict[str, int], n: int) -> list[dict]:
    return [
        {"key": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda x: -x[1])[:n]
    ]


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_queries"   : 0,
        "successes"       : 0,
        "failures"        : 0,
        "rejections"      : 0,
        "success_rate_pct": 0,
        "latency"         : {
            "avg_total_s": None,
            "p95_total_s": None,
            "avg_llm_s"  : None,
            "avg_db_s"   : None,
        },
        "top_error_stages"  : [],
        "top_warnings"      : [],
        "llm_fallback_count": 0,
    }


# ── Module-level singleton ────────────────────────────────────
# Import this wherever you need to write or read logs.
query_logger = QueryLogger()