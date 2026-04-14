# Validates SQL (only SELECT, prevents injection)
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    is_valid      : bool
    reason        : str
    sanitised_sql : str | None = None   # cleaned SQL if valid, else None


class SQLValidator:
    """
    Safety gate between SQL generation and execution.

    Enforces hard rules — queries that fail here are
    rejected outright and never reach the database.

    Rules enforced:
      1. Only SELECT statements allowed
      2. No stacked statements (no semicolons mid-query)
      3. No dangerous keywords regardless of position
      4. No SQL comment injections (-- or /* */)
      5. Query must not be empty after cleaning
      6. Basic length sanity check
    """

    # These keywords must never appear anywhere in the query
    BLOCKED_KEYWORDS = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "REPLACE",
        "GRANT",
        "REVOKE",
        "EXECUTE",
        "EXEC",
        "XP_",          # SQL Server proc prefix — block defensively
        "INTO OUTFILE",  # MySQL file write — block defensively
    ]

    MAX_SQL_LENGTH = 2000   # characters — a legitimate SELECT won't exceed this


    def validate(self, sql: str) -> ValidationResult:
        """
        Runs all safety checks on the generated SQL.

        Returns ValidationResult with:
          - is_valid      : bool
          - reason        : why it passed or failed
          - sanitised_sql : cleaned SQL string if valid, else None
        """
        # ── Step 1 : Basic sanity ─────────────────────────────
        if not sql or not sql.strip():
            return self._fail("Generated SQL is empty.")

        cleaned = sql.strip()

        if len(cleaned) > self.MAX_SQL_LENGTH:
            return self._fail(
                f"Generated SQL exceeds maximum length ({self.MAX_SQL_LENGTH} chars). "
                "This is unexpected — possible model error."
            )

        # ── Step 2 : Strip trailing semicolon for checks ──────
        # We'll add it back cleanly at the end
        normalised = cleaned.rstrip(";").strip()

        # ── Step 3 : Must start with SELECT ───────────────────
        if not re.match(r"^SELECT\b", normalised, re.IGNORECASE):
            return self._fail(
                f"Only SELECT queries are allowed. "
                f"Query starts with: '{normalised[:30]}...'"
            )

        # ── Step 4 : Block dangerous keywords ─────────────────
        upper = normalised.upper()
        for keyword in self.BLOCKED_KEYWORDS:
            # Use word boundary to avoid false positives
            # e.g. "CREATED_AT" should not trigger "CREATE"
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, upper):
                return self._fail(
                    f"Blocked keyword detected: '{keyword}'. "
                    "Only read-only SELECT queries are permitted."
                )

        # ── Step 5 : No stacked statements ────────────────────
        # A legitimate SELECT has at most one semicolon at the end
        # Multiple semicolons = stacked queries = injection risk
        if normalised.count(";") > 0:
            return self._fail(
                "Multiple statements detected (semicolon mid-query). "
                "Only a single SELECT statement is allowed."
            )

        # ── Step 6 : No SQL comment injections ────────────────
        if "--" in normalised:
            return self._fail(
                "SQL line comments (--) are not allowed in generated queries."
            )
        if "/*" in normalised or "*/" in normalised:
            return self._fail(
                "SQL block comments (/* */) are not allowed in generated queries."
            )

        # ── All checks passed ─────────────────────────────────
        sanitised = normalised + ";"

        logger.info(f"SQL validation passed: {sanitised[:80]}...")

        return ValidationResult(
            is_valid      = True,
            reason        = "Query passed all safety checks.",
            sanitised_sql = sanitised,
        )


    # ── Private ───────────────────────────────────────────────

    @staticmethod
    def _fail(reason: str) -> ValidationResult:
        logger.warning(f"SQL validation failed: {reason}")
        return ValidationResult(
            is_valid      = False,
            reason        = reason,
            sanitised_sql = None,
        )