# backend/llm/gemini_provider.py
# Gemini API integration logic

import logging
import re
import asyncio
from typing import Optional

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from backend.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


def _is_truncated_sql(sql: str) -> bool:
    """
    Detects whether a generated SQL string is incomplete/truncated.

    Gemini sometimes stops mid-generation when token budget is tight.
    Common truncation patterns:
      - Unbalanced parentheses  (CTE opened but never closed)
      - SQL ends mid-clause     (no semicolon, no final SELECT after WITH)
      - Ends inside a function  e.g. "ORDER BY pp.list_price DESC" with no closing )
    """
    s = sql.strip().rstrip(";").strip()

    # 1. Unbalanced parentheses — most reliable signal for CTEs
    if s.count("(") != s.count(")"):
        logger.warning("Truncation detected: unbalanced parentheses in SQL.")
        return True

    # 2. CTE with no outer SELECT after the last closing paren
    #    WITH x AS (...) must be followed by SELECT ...
    if re.match(r"^\s*WITH\b", s, re.IGNORECASE):
        # Find position of last ')' — the outer SELECT must come after it
        last_paren = s.rfind(")")
        tail = s[last_paren + 1:].strip() if last_paren != -1 else ""
        if not re.match(r"^SELECT\b", tail, re.IGNORECASE):
            logger.warning("Truncation detected: CTE has no outer SELECT after closing paren.")
            return True

    # 3. Ends inside an OVER(...) window function (no closing paren for OVER)
    if re.search(r"\bOVER\s*\([^)]*$", s, re.IGNORECASE):
        logger.warning("Truncation detected: unclosed OVER() window function.")
        return True

    return False


class GeminiProvider:
    """Thin async wrapper around the current Google GenAI SDK (2026)."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.GEMINI_API_KEY
        if not key:
            raise ValueError(
                "Gemini API key is missing. "
                "Set GEMINI_API_KEY in .env (demo) or pass it via credentials (custom)."
            )

        self.client = genai.Client(
            api_key=key,
            http_options=HttpOptions(api_version="v1")
        )

        self.model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

        self.config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_TOKENS,
        )

        # Higher token config used when we detect truncation on first attempt
        self._retry_config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=min(settings.GEMINI_MAX_TOKENS * 2, 8192),
        )

        logger.info(f"GeminiProvider initialised with model: {self.model_name}")


    async def generate(self, prompt: str) -> str:
        """Sends a prompt to Gemini and returns the raw text response."""
        MAX_RETRIES    = settings.GEMINI_MAX_RETRIES
        fallback_model = settings.GEMINI_FALLBACK_MODEL
        BASE_DELAY     = settings.GEMINI_RETRY_BASE_DELAY

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.config,
                )
                return response.text.strip()

            except Exception as e:
                error_str = str(e)

                if "503" in error_str and attempt < MAX_RETRIES - 1:
                    wait_time = BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Gemini overloaded (attempt {attempt+1}) — retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                if "503" in error_str:
                    logger.warning("Switching to fallback model due to repeated failures...")
                    try:
                        response = await self.client.aio.models.generate_content(
                            model=fallback_model,
                            contents=prompt,
                            config=self.config,
                        )
                        return response.text.strip()
                    except Exception as fallback_error:
                        logger.error(f"Fallback model also failed: {fallback_error}")
                        raise RuntimeError(f"Gemini API error: {fallback_error}") from fallback_error

                logger.error(f"Gemini generate() failed: {e}")
                raise RuntimeError(f"Gemini API error: {e}") from e


    async def generate_sql(self, prompt: str) -> str:
        """
        Sends a prompt to Gemini and returns cleaned SQL only.

        Includes truncation detection: if the first response looks incomplete
        (e.g. unbalanced parentheses, CTE with no outer SELECT), we retry
        once with a doubled token budget before giving up.
        """
        MAX_RETRIES    = settings.GEMINI_MAX_RETRIES
        fallback_model = settings.GEMINI_FALLBACK_MODEL
        BASE_DELAY     = settings.GEMINI_RETRY_BASE_DELAY

        for attempt in range(MAX_RETRIES):
            try:
                # On a truncation retry (attempt > 0 triggered by truncation),
                # use a larger token budget.
                config = self._retry_config if getattr(self, "_truncation_retry", False) else self.config
                self._truncation_retry = False

                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

                raw = response.text.strip()
                sql = self._clean_sql(raw)

                logger.debug(f"Gemini raw output (attempt {attempt+1}):\n{raw}")
                logger.debug(f"Cleaned SQL:\n{sql}")

                # ── Truncation check ──────────────────────────
                if _is_truncated_sql(sql):
                    if attempt < MAX_RETRIES - 1:
                        logger.warning(
                            f"Truncated SQL detected on attempt {attempt+1} — "
                            f"retrying with larger token budget..."
                        )
                        self._truncation_retry = True  # flag for next loop iteration
                        await asyncio.sleep(0.5)       # brief pause before retry
                        continue
                    else:
                        # All retries exhausted — raise a clear error
                        raise RuntimeError(
                            "Generated SQL appears to be incomplete after multiple attempts. "
                            "Try rephrasing your question with fewer columns or simpler conditions."
                        )

                return sql

            except RuntimeError:
                raise  # re-raise our own errors (truncation, etc.)

            except Exception as e:
                error_str = str(e)

                if "503" in error_str and attempt < MAX_RETRIES - 1:
                    wait_time = BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Gemini overloaded (attempt {attempt+1}) — retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                if "503" in error_str:
                    logger.warning("Switching to fallback model due to repeated failures...")
                    try:
                        response = await self.client.aio.models.generate_content(
                            model=fallback_model,
                            contents=prompt,
                            config=self.config,
                        )
                        raw = response.text.strip()
                        sql = self._clean_sql(raw)
                        return sql
                    except Exception as fallback_error:
                        logger.error(f"Fallback model also failed: {fallback_error}")
                        raise RuntimeError(f"Gemini API error: {fallback_error}") from fallback_error

                logger.error(f"Gemini generate_sql() failed: {e}")
                raise RuntimeError(f"Gemini API error: {e}") from e


    # ── Private ───────────────────────────────────────────────

    @staticmethod
    def _clean_sql(raw: str) -> str:
        """Cleans Gemini's response down to plain SQL."""
        # 1. Strip markdown code fences
        fenced = re.search(
            r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE
        )
        if fenced:
            return fenced.group(1).strip()

        # 2. Remove common prose prefixes
        prose_prefixes = [
            r"^here is the sql[:\s]+",
            r"^here's the sql[:\s]+",
            r"^the sql query[:\s]+",
            r"^sql[:\s]+",
            r"^query[:\s]+",
        ]
        cleaned = raw
        for pattern in prose_prefixes:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        # 3. Keep only the first statement
        # For CTEs, don't split on semicolons inside the CTE body —
        # only split on the terminal semicolon after the outer SELECT.
        # Simple heuristic: find the LAST semicolon and treat everything before it
        # as one statement (CTEs are single logical statements).
        last_semi = cleaned.rfind(";")
        if last_semi != -1:
            cleaned = cleaned[:last_semi + 1].strip()

        return cleaned.strip()