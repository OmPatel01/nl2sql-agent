# backend/services/query_executor.py
# Executes SQL queries on PostgreSQL
import logging
import re
from typing import Any, Optional

import asyncpg

from backend.config import get_settings
from backend.db.connection import get_pool

logger   = logging.getLogger(__name__)
settings = get_settings()


def _inject_limit(sql: str, max_rows: int) -> str:
    """
    Safely injects a LIMIT clause into a SELECT or CTE query.

    The key problem this solves: naively appending LIMIT to a CTE like
        WITH x AS (SELECT ... ORDER BY price DESC   ← truncated here by LIMIT
    breaks the query. LIMIT must go on the OUTER SELECT, after the CTE body.

    Strategy:
      1. If SQL already has a LIMIT → cap it to max_rows if it exceeds, else leave it.
      2. If no LIMIT → find the correct position to inject it.
         For CTEs: after the final closing paren of the CTE definition, on the outer SELECT.
         For plain SELECTs: append before the trailing semicolon.
    """
    normalised = sql.strip().rstrip(";").strip()
    upper      = normalised.upper()

    # ── Case 1: SQL already has a LIMIT ──────────────────────
    existing = re.search(r"\bLIMIT\s+(\d+)", upper)
    if existing:
        user_limit = int(existing.group(1))
        if user_limit > max_rows:
            # Cap it — replace the existing LIMIT value
            capped = re.sub(
                r"\bLIMIT\s+\d+",
                f"LIMIT {max_rows}",
                normalised,
                flags=re.IGNORECASE,
            )
            return capped.rstrip(";") + ";"
        else:
            return normalised + ";"   # user limit is fine, respect it

    # ── Case 2: No LIMIT — must inject one ───────────────────
    fetch_limit = max_rows + 1   # fetch one extra to detect truncation

    is_cte = bool(re.match(r"^\s*WITH\b", normalised, re.IGNORECASE))

    if not is_cte:
        # Plain SELECT — just append before semicolon
        return normalised + f"\nLIMIT {fetch_limit};"

    # CTE: find the outer SELECT (the one after all CTE definitions end).
    # We track paren depth — the outer SELECT starts when depth returns to 0
    # after the WITH block's closing paren.
    depth         = 0
    in_with_block = True   # True until we've seen WITH x AS (...) close
    outer_select_pos = -1

    i = 0
    while i < len(normalised):
        ch = normalised[i]

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            # When depth returns to 0 we've closed a CTE definition
            if depth == 0 and in_with_block:
                # The outer SELECT should start after this point
                # (possibly after a comma for multi-CTEs, or directly)
                tail = normalised[i + 1:].lstrip()
                # If next non-whitespace token is a comma, there's another CTE
                if tail.startswith(","):
                    pass   # keep scanning
                else:
                    # Next token after optional whitespace should be SELECT
                    in_with_block = False
                    outer_select_pos = i + 1

        i += 1

    if outer_select_pos == -1:
        # Couldn't find a clear split point — fall back to appending
        logger.warning("Could not locate outer SELECT in CTE — appending LIMIT at end.")
        return normalised + f"\nLIMIT {fetch_limit};"

    # Split: CTE body | outer SELECT
    cte_body     = normalised[:outer_select_pos].rstrip()
    outer_select = normalised[outer_select_pos:].strip()

    # Check if outer SELECT itself already has ORDER BY (common in ranking queries)
    # Append LIMIT after ORDER BY if present, otherwise at the end.
    result = cte_body + "\n" + outer_select + f"\nLIMIT {fetch_limit};"

    logger.debug(f"CTE-aware LIMIT injection result:\n{result}")
    return result


class QueryExecutor:
    """
    Executes a validated SELECT query against PostgreSQL
    and returns results in a clean, serialisable format.

    Never receives raw SQL — only sanitised_sql from SQLValidator.
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url   # None = demo mode


    async def execute(self, sql: str) -> dict[str, Any]:
        """
        Runs the SQL query and returns:
        {
            "columns"      : ["col1", "col2", ...],
            "rows"         : [[val1, val2], ...],
            "row_count"    : int,
            "returned_rows": int,
            "total_rows"   : int | str,
            "truncated"    : bool
        }
        """
        pool = await get_pool()

        try:
            async with pool.acquire() as conn:

                await conn.execute("SET TRANSACTION READ ONLY")

                # Build the final SQL with a safe, CTE-aware LIMIT injection
                final_sql = _inject_limit(sql, settings.MAX_RESULT_ROWS)

                logger.info(f"Final SQL being executed:\n{final_sql}")

                rows = await conn.fetch(final_sql)

                return self._format_results(rows)

        except asyncpg.PostgresError as e:
            logger.error(f"PostgreSQL error executing query: {e}\nSQL: {sql}")
            raise RuntimeError(self._friendly_db_error(e)) from e

        except Exception as e:
            logger.error(f"Unexpected error during query execution: {e}")
            raise RuntimeError(f"Query execution failed: {str(e)}") from e


    # ── Private ───────────────────────────────────────────────

    def _format_results(self, rows: list[asyncpg.Record]) -> dict[str, Any]:
        if not rows:
            return {
                "columns"      : [],
                "rows"         : [],
                "row_count"    : 0,
                "returned_rows": 0,
                "total_rows"   : 0,
                "truncated"    : False,
            }

        columns       = list(rows[0].keys())
        total_fetched = len(rows)
        truncated     = total_fetched > settings.MAX_RESULT_ROWS
        capped_rows   = rows[:settings.MAX_RESULT_ROWS]
        total_rows    = f">{settings.MAX_RESULT_ROWS}" if truncated else total_fetched

        serialised_rows = [
            [self._serialise(val) for val in row.values()]
            for row in capped_rows
        ]

        logger.info(
            f"Query returned {total_fetched} row(s)"
            f"{' (truncated to ' + str(settings.MAX_RESULT_ROWS) + ')' if truncated else ''}."
        )

        return {
            "columns"      : columns,
            "rows"         : serialised_rows,
            "row_count"    : len(capped_rows),
            "returned_rows": len(capped_rows),
            "total_rows"   : total_rows,
            "truncated"    : truncated,
        }


    @staticmethod
    def _serialise(value: Any) -> Any:
        import datetime
        import decimal

        if value is None:
            return None
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.isoformat()
        if isinstance(value, datetime.timedelta):
            return str(value)
        if isinstance(value, decimal.Decimal):
            return float(value)
        return value


    @staticmethod
    def _friendly_db_error(e: asyncpg.PostgresError) -> str:
        code = getattr(e, "sqlstate", None)

        messages = {
            "42P01": "Query references a table that does not exist.",
            "42703": "Query references a column that does not exist.",
            "42883": "Query uses a function that does not exist.",
            "42601": "Generated SQL has a syntax error.",
            "53300": "Too many database connections. Please try again shortly.",
            "57014": "Query took too long and was cancelled.",
        }

        return messages.get(code, f"Database error: {e.args[0] if e.args else str(e)}")