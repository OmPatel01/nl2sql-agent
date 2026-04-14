# Gemini API integration logic
import logging
import re
from typing import Optional

import google.generativeai as genai

from backend.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


class GeminiProvider:
    """
    Thin async wrapper around the Gemini API.
    Handles client initialisation, calling the model,
    and cleaning the raw response into plain SQL.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        api_key — demo mode uses GEMINI_API_KEY from settings.
                  Custom mode passes the user's key at runtime.
        """
        key = api_key or settings.GEMINI_API_KEY

        if not key:
            raise ValueError(
                "Gemini API key is missing. "
                "Set GEMINI_API_KEY in .env (demo) or pass it via credentials (custom)."
            )

        genai.configure(api_key=key)

        self.model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature      = settings.GEMINI_TEMPERATURE,
                max_output_tokens= settings.GEMINI_MAX_TOKENS,
            ),
        )

        logger.info(f"GeminiProvider initialised with model: {settings.GEMINI_MODEL}")


    async def generate(self, prompt: str) -> str:
        """
        Sends a prompt to Gemini and returns the raw text response.
        Used by the classifier and any non-SQL generation tasks.
        """
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()

        except Exception as e:
            logger.error(f"Gemini generate() failed: {e}")
            raise RuntimeError(f"Gemini API error: {e}") from e


    async def generate_sql(self, prompt: str) -> str:
        """
        Sends a prompt to Gemini and returns cleaned SQL only.
        Strips markdown fences, extra whitespace, and commentary
        that the model sometimes wraps around the SQL.
        """
        try:
            response = await self.model.generate_content_async(prompt)
            raw      = response.text.strip()
            sql      = self._clean_sql(raw)

            logger.debug(f"Gemini raw output:\n{raw}")
            logger.debug(f"Cleaned SQL:\n{sql}")

            return sql

        except Exception as e:
            logger.error(f"Gemini generate_sql() failed: {e}")
            raise RuntimeError(f"Gemini API error: {e}") from e


    # ── Private ───────────────────────────────────────────────

    @staticmethod
    def _clean_sql(raw: str) -> str:
        """
        Cleans Gemini's response down to plain SQL.

        Handles these common model behaviours:
          1. SQL wrapped in ```sql ... ``` fences
          2. SQL wrapped in plain ``` ... ``` fences
          3. Prefixes like "Here is the SQL:" before the query
          4. Trailing commentary after the semicolon
          5. Excess whitespace / newlines
        """
        # 1. Strip markdown code fences (```sql or ```)
        fenced = re.search(r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()

        # 2. Remove common prose prefixes the model adds
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

        # 3. If multiple statements somehow sneak through, keep only the first
        #    (split on ; but preserve the semicolon)
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        if statements:
            cleaned = statements[0] + ";"

        return cleaned.strip()