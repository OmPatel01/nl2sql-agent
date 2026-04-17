# Evaluates ambiguity and generates warnings
import logging
import re
from dataclasses import dataclass, field

from backend.models.response import WarningDetail

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceResult:
    is_confident: bool
    warnings    : list[WarningDetail] = field(default_factory=list)


class ConfidenceEvaluator:
    """
    Analyses the generated SQL for patterns that suggest
    low confidence or risky output — without executing it.

    Emits WarningDetail objects that are passed through to
    the API response so the frontend can surface them.

    This is purely rule-based (no extra LLM call) — fast and free.
    """

    # Tables in the demo DB known to grow large
    LARGE_TABLES = {"borrowings"}

    # Columns that commonly cause ambiguity across tables
    AMBIGUOUS_COLUMNS = {"status", "name", "date", "id"}


    def evaluate(self, sql: str, question: str) -> ConfidenceResult:
        """
        Runs all checks against the generated SQL.
        Returns a ConfidenceResult with zero or more warnings.
        is_confident = False only when a warning is serious enough
        to flag the result as potentially wrong.
        """
        warnings: list[WarningDetail] = []
        sql_upper = sql.upper()

        # ── Check 1 : No WHERE clause on a large table ────────
        w = self._check_missing_filter(sql, sql_upper)
        if w:
            warnings.append(w)

        # ── Check 2 : SELECT * used ───────────────────────────
        w = self._check_select_star(sql_upper)
        if w:
            warnings.append(w)

        # ── Check 3 : Ambiguous unqualified column references ─
        w = self._check_ambiguous_columns(sql, sql_upper)
        if w:
            warnings.append(w)

        # ── Check 4 : No LIMIT on potentially large result ────
        w = self._check_missing_limit(sql, sql_upper)
        if w:
            warnings.append(w)

        # ── Check 5 : Question has vague words ────────────────
        w = self._check_vague_question(question)
        if w:
            warnings.append(w)

        # ── Check 6 : Strict ILIKE without wildcards ──────────────
        w = self._check_strict_ilike(sql)
        if w:
            warnings.append(w)

        # Mark low confidence if any warning was raised
        is_confident = len(warnings) == 0

        if warnings:
            logger.warning(
                f"Confidence issues detected for SQL:\n{sql}\n"
                f"Warnings: {[w.code for w in warnings]}"
            )
        else:
            logger.debug("Confidence check passed.")

        return ConfidenceResult(is_confident=is_confident, warnings=warnings)


    # ── Individual checks ─────────────────────────────────────

    def _check_missing_filter(
        self, sql: str, sql_upper: str
    ) -> WarningDetail | None:
        """
        Warn if a large table is queried with no WHERE clause.
        e.g. SELECT ... FROM borrowings  (no WHERE)
        """
        for table in self.LARGE_TABLES:
            in_query = re.search(
                rf"\bFROM\s+{table}\b|\bJOIN\s+{table}\b",
                sql_upper,
            )
            has_where = "WHERE" in sql_upper

            if in_query and not has_where:
                return WarningDetail(
                    code    = "MISSING_FILTER",
                    message = (
                        f"Query scans the entire '{table}' table with no filter. "
                        "Results may be large — consider adding a condition."
                    ),
                )
        return None


    @staticmethod
    def _check_select_star(sql_upper: str) -> WarningDetail | None:
        """Warn if SELECT * was generated despite the prompt rule."""
        if re.search(r"SELECT\s+\*", sql_upper):
            return WarningDetail(
                code    = "SELECT_STAR",
                message = (
                    "Query uses SELECT * which may return unnecessary columns. "
                    "Results might be harder to read."
                ),
            )
        return None


    def _check_ambiguous_columns(
        self, sql: str, sql_upper: str
    ) -> WarningDetail | None:
        """
        Warn if a known ambiguous column name appears in the SQL
        without a table qualifier (e.g. bare 'status' vs 'br.status').
        """
        for col in self.AMBIGUOUS_COLUMNS:
            # Look for the column name NOT preceded by a dot (unqualified)
            unqualified = re.search(
                rf"(?<!\.)\b{col}\b",
                sql,
                re.IGNORECASE,
            )
            if unqualified:
                return WarningDetail(
                    code    = "AMBIGUOUS_COLUMN",
                    message = (
                        f"Column '{col}' appears without a table qualifier. "
                        "This may cause errors if it exists in multiple tables."
                    ),
                )
        return None


    @staticmethod
    def _check_missing_limit(sql: str, sql_upper: str) -> WarningDetail | None:
        """
        Removed generic no-LIMIT warning. It fired on every "show all X" query
        even when the result set was small. The executor enforces MAX_RESULT_ROWS
        as a hard cap; a LARGE_RESULT warning is appended post-execution only
        when rows were actually truncated.
        """
        has_limit     = "LIMIT" in sql_upper
        has_aggregate = bool(
            re.search(r"\b(COUNT|SUM|AVG|MAX|MIN)\s*\(", sql_upper)
        )

        if not has_limit and not has_aggregate:
            return WarningDetail(
                code    = "LARGE_RESULT",
                message = (
                    "Query has no LIMIT clause. "
                    "If the table is large, this may return many rows."
                ),
            )
        return None


    @staticmethod
    def _check_vague_question(question: str) -> WarningDetail | None:
        """
        Warn if the original question contained vague words
        that often lead to ambiguous SQL.
        """
        vague_words = ["something", "anything", "stuff", "things", "some", "any data"]
        q_lower     = question.lower()

        for word in vague_words:
            if word in q_lower:
                return WarningDetail(
                    code    = "LOW_CONFIDENCE",
                    message = (
                        f"Question contains vague language ('{word}'). "
                        "The generated SQL may not match your intent exactly."
                    ),
                )
        return None
    
    @staticmethod
    def _check_strict_ilike(sql: str) -> WarningDetail | None:
        """
        Warn if ILIKE is used without % wildcards — meaning it's an
        exact case-insensitive match, which often misses real results.
        e.g.  ILIKE 'Fiction'  instead of  ILIKE '%Fiction%'
        """
        matches = re.findall(r"ILIKE\s+'([^']*)'", sql, re.IGNORECASE)
        for match in matches:
            if "%" not in match:
                return WarningDetail(
                    code    = "STRICT_MATCH",
                    message = (
                        f"Query uses exact text match (ILIKE '{match}'). "
                        "Consider partial matching (ILIKE '%value%') for broader results."
                    ),
                )
        return None