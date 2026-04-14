# Converts natural language to SQL using LLM
import logging
from typing import Optional

from backend.llm.gemini_provider import GeminiProvider
from backend.prompts.nl_to_sql import build_nl_to_sql_prompt
from backend.cache.schema_cache import get_schema_prompt_text

logger = logging.getLogger(__name__)


class NLToSQLService:
    """
    Core service — converts a natural language question
    into a PostgreSQL SELECT query using Gemini.

    Responsibilities:
      - Fetch schema prompt text from cache
      - Inject conversation history for follow-up queries
      - Call Gemini via GeminiProvider
      - Return the cleaned SQL string
    """

    def __init__(
        self,
        gemini      : GeminiProvider,
        database_url: Optional[str] = None,
    ):
        self.gemini       = gemini
        self.database_url = database_url   # None = demo mode (uses settings)


    async def generate(
        self,
        question: str,
        history : list[dict] | None = None,
    ) -> str:
        """
        Generates SQL for the given NL question.

        Args:
            question : user's natural language question
            history  : list of previous turns from SessionManager
                       each dict has keys: 'question', 'sql'

        Returns:
            Cleaned SQL string ready for validation + execution.
        """

        # 1. Get schema prompt text from cache (auto-refreshes if stale)
        schema_text = await get_schema_prompt_text(self.database_url)

        if not schema_text:
            raise RuntimeError(
                "Schema is empty. Cannot generate SQL without schema context."
            )

        # 2. Build the full prompt
        prompt = build_nl_to_sql_prompt(
            question    = question,
            schema_text = schema_text,
            history     = history or [],
        )

        logger.debug(f"NL→SQL prompt built for question: '{question}'")

        # 3. Call Gemini — generate_sql() strips fences and prose automatically
        sql = await self.gemini.generate_sql(prompt)

        if not sql:
            raise RuntimeError(
                "Gemini returned an empty response. "
                "Check your API key, model name, and prompt."
            )

        logger.info(f"Generated SQL for '{question}':\n{sql}")

        return sql