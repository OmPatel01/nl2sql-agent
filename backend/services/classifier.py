# backend/services/classifier.py
# Classifies queries (valid vs irrelevant)
import logging
import re
import difflib
from dataclasses import dataclass
from backend.llm.gemini_provider import GeminiProvider
from backend.prompts.classifier import build_classifier_prompt

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    is_valid  : bool
    reason    : str
    raw       : str   # full Gemini response — useful for debugging


class ClassifierService:
    """
    Decides whether a user's natural language question
    is answerable from the current database schema.

    Sits at the top of the pipeline — invalid queries are
    rejected here before touching the LLM SQL generator,
    saving tokens and latency.
    """

    def __init__(self, gemini: GeminiProvider):
        self.gemini = gemini


    async def classify(
        self,
        question   : str,
        schema_text: str,
    ) -> ClassificationResult:
        """
        Classifies the question as VALID or INVALID.

        Returns a ClassificationResult with:
          - is_valid : bool
          - reason   : short explanation
          - raw      : full model response for logging
        """

        # Fast path — catch obvious non-questions before hitting the LLM
        fast_result = self._fast_reject(question)
        if fast_result:
            logger.info(f"Fast reject: '{question}' — {fast_result}")
            return ClassificationResult(
                is_valid = False,
                reason   = fast_result,
                raw      = "fast_reject",
            )

        prompt   = build_classifier_prompt(question, schema_text)
        raw      = await self.gemini.generate(prompt)
        result   = self._parse_response(raw)

        logger.info(
            f"Classification: {'VALID' if result.is_valid else 'INVALID'} "
            f"| question='{question}' | reason='{result.reason}'"
        )

        return result


    # ── Private ───────────────────────────────────────────────

    @staticmethod
    def _fast_reject(question: str) -> str | None:
        """
        Rule-based pre-filter — catches obvious non-database
        questions without spending a Gemini API call.

        Returns a rejection reason string, or None if no fast reject.
        """
        q = question.strip().lower()

        # Too short to be meaningful
        if len(q) < 5:
            return "Question is too short to be meaningful."

        # Greetings / small talk
        greetings = {"hi", "hello", "hey", "thanks", "thank you", "bye", "ok", "okay"}
        if q in greetings or q.rstrip("!?.") in greetings:
            return "Greetings and small talk are not database queries."

        # Explicit write-intent keywords
        write_keywords = ["insert into", "update ", "delete from", "drop table", "alter table", "truncate"]
        for kw in write_keywords:
            if kw in q:
                return f"Write operations are not permitted (detected: '{kw.strip()}')."

        return None  # No fast reject — send to LLM classifier

    @staticmethod
    def is_ambiguous(question: str) -> tuple[bool, str]:
        """
        Detects ambiguous queries.

        Returns:
            (is_ambiguous, level)
            level: "high" (reject) or "low" (warn)
        """
        q = question.strip().lower()
        words = q.split()

        vague_terms = {"show", "list", "give", "data", "info", "details", "top"}

        # Very vague → reject
        if len(words) <= 2:
            return True, "high"

        # Slightly vague → allow but warn
        if any(w in vague_terms for w in words) and len(words) <= 4:
            return True, "low"

        return False, "none"


    @staticmethod
    def is_schema_relevant(question: str, schema_text: str) -> bool:
        """
        Fast keyword-based schema relevance check (Layer 1).
        """
        q = question.lower()

        # extract table/column names from schema text
        schema_words = set(re.findall(r"\b[a-zA-Z_]+\b", schema_text.lower()))

        def _is_similar(word, schema_words):
            for schema_word in schema_words:
                # partial match
                if word in schema_word:
                    return True

                # fuzzy match for typos
                if difflib.SequenceMatcher(None, word, schema_word).ratio() > 0.75:
                    return True

            return False

        matches = [
            word for word in q.split()
            if _is_similar(word, schema_words)
        ]

        return len(matches) > 0

    @staticmethod
    def _parse_response(raw: str) -> ClassificationResult:
        """
        Parses Gemini's classifier response.

        Expected format:
            CLASSIFICATION: VALID
            REASON: The question asks about borrowing records in the schema.

        Falls back to INVALID if the format is unexpected.
        """
        classification = "INVALID"
        reason         = "Could not parse classifier response."

        for line in raw.splitlines():
            line = line.strip()

            if line.upper().startswith("CLASSIFICATION:"):
                value = line.split(":", 1)[1].strip().upper()
                if value in ("VALID", "INVALID"):
                    classification = value

            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        return ClassificationResult(
            is_valid = classification == "VALID",
            reason   = reason,
            raw      = raw,
        )