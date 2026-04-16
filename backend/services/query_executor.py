# Executes SQL queries on PostgreSQL
import logging
from typing import Any, Optional

import asyncpg
import re
from backend.config import get_settings
from backend.db.connection import get_pool

logger   = logging.getLogger(__name__)
settings = get_settings()


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
            "columns"  : ["col1", "col2", ...],
            "rows"     : [[val1, val2], [val1, val2], ...],
            "row_count": int,
            "truncated": bool   # True if MAX_RESULT_ROWS was hit
        }

        Raises RuntimeError on DB errors with a clean message
        (raw asyncpg errors are caught and re-raised to avoid
        leaking internal DB details to the frontend).
        """
        pool = await get_pool()

        try:
            async with pool.acquire() as conn:

                # Read-only safety net at the DB level
                await conn.execute("SET TRANSACTION READ ONLY")

                # limit_plus_one_sql = sql.rstrip(";") + f"\nLIMIT {settings.MAX_RESULT_ROWS + 1};"
                sql_upper = sql.upper()

                limit_match = re.search(r"\bLIMIT\s+(\d+)", sql_upper)

                if limit_match:
                    user_limit = int(limit_match.group(1))

                    if user_limit > settings.MAX_RESULT_ROWS:
                        # Cap to max limit
                        final_sql = re.sub(
                            r"\bLIMIT\s+\d+",
                            f"LIMIT {settings.MAX_RESULT_ROWS}",
                            sql,
                            flags=re.IGNORECASE
                        )
                    else:
                        # Respect user's limit
                        final_sql = sql
                else:
                    # No LIMIT → apply safety limit +1
                    final_sql = sql.rstrip(";") + f"\nLIMIT {settings.MAX_RESULT_ROWS + 1};"

                logger.warning(f"FINAL SQL BEING EXECUTED:\n{final_sql}")

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
        """
        Converts asyncpg Records into plain Python lists
        safe for JSON serialisation.

        Applies MAX_RESULT_ROWS cap and flags truncation.
        """
        if not rows:
            return {
                "columns"  : [],
                "rows"     : [],
                "row_count": 0,
                "truncated": False,
            }

        # Column names from the first record
        columns = list(rows[0].keys())

        # Cap rows to MAX_RESULT_ROWS
        total_fetched = len(rows)
        truncated = total_fetched > settings.MAX_RESULT_ROWS
        capped_rows = rows[:settings.MAX_RESULT_ROWS]

        total_rows = total_fetched

        # If truncated, we only know "at least N"
        if truncated:
            total_rows = f">{settings.MAX_RESULT_ROWS}"

        # Convert each Record to a plain list, serialising non-JSON types
        serialised_rows = [
            [self._serialise(val) for val in row.values()]
            for row in capped_rows
        ]

        logger.info(
            f"Query returned {len(rows)} row(s)"
            f"{' (truncated to ' + str(settings.MAX_RESULT_ROWS) + ')' if truncated else ''}."
        )

        return {
            "columns": columns,
            "rows": serialised_rows,
            "row_count": len(capped_rows),
            "returned_rows": len(capped_rows),
            "total_rows": total_rows,
            "truncated": truncated,
        }


    @staticmethod
    def _serialise(value: Any) -> Any:
        """
        Converts Python / PostgreSQL types that are not
        JSON-serialisable into safe primitives.
        """
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
        if isinstance(value, (list, dict)):
            return value   # asyncpg returns these as native Python already
        return value       # int, float, str, bool — already JSON safe


    @staticmethod
    def _friendly_db_error(e: asyncpg.PostgresError) -> str:
        """
        Maps raw PostgreSQL error codes to user-friendly messages.
        Avoids leaking table structures or internal details.
        """
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