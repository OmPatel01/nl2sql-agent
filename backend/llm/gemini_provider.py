# # Gemini API integration logic

import logging
import re
import asyncio
from typing import Optional

from google import genai
from google.genai import types
from google.genai.types import HttpOptions   # ← NEW: forces stable v1 endpoint

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiProvider:
    """Thin async wrapper around the current Google GenAI SDK (2026)."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.GEMINI_API_KEY
        if not key:
            raise ValueError(
                "Gemini API key is missing. "
                "Set GEMINI_API_KEY in .env (demo) or pass it via credentials (custom)."
            )

        # Force stable v1 API version (prevents v1beta 404s in future)
        self.client = genai.Client(
            api_key=key,
            http_options=HttpOptions(api_version="v1")
        )

        # Updated default to current model (was the retired 1.5-flash)
        self.model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

        # Keep your original generation settings
        self.config = types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_TOKENS,
        )

        logger.info(f"GeminiProvider initialised with model: {self.model_name}")

    async def generate(self, prompt: str) -> str:
        """Sends a prompt to Gemini and returns the raw text response."""
        MAX_RETRIES = settings.GEMINI_MAX_RETRIES
        fallback_model = settings.GEMINI_FALLBACK_MODEL
        BASE_DELAY = settings.GEMINI_RETRY_BASE_DELAY

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

                # 🔁 Retry on overload (503)
                if "503" in error_str and attempt < MAX_RETRIES - 1:
                    wait_time = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Gemini overloaded (attempt {attempt+1}) — retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 🔥 Fallback model if retries exhausted
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
        """Sends a prompt to Gemini and returns cleaned SQL only."""
        MAX_RETRIES = settings.GEMINI_MAX_RETRIES
        fallback_model = settings.GEMINI_FALLBACK_MODEL
        BASE_DELAY = settings.GEMINI_RETRY_BASE_DELAY

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.config,
                )

                raw = response.text.strip()
                sql = self._clean_sql(raw)

                logger.debug(f"Gemini raw output:\n{raw}")
                logger.debug(f"Cleaned SQL:\n{sql}")

                return sql

            except Exception as e:
                error_str = str(e)

                # 🔁 Retry on overload
                if "503" in error_str and attempt < MAX_RETRIES - 1:
                    wait_time = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Gemini overloaded (attempt {attempt+1}) — retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 🔥 Fallback model
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
        """Cleans Gemini's response down to plain SQL (unchanged)."""
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
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        if statements:
            cleaned = statements[0] + ";"

        return cleaned.strip()