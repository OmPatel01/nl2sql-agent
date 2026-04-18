# backend/api/routes/query.py
# Handles POST /query — main NL query endpoint
import logging
from fastapi import APIRouter, HTTPException
from backend.config import get_settings, AppMode
from backend.models.request import QueryRequest
from backend.models.response import QueryResponse, WarningDetail
from backend.llm.gemini_provider import GeminiProvider
from backend.services.classifier import ClassifierService
from backend.services.nl_to_sql import NLToSQLService
from backend.services.confidence import ConfidenceEvaluator
from backend.services.validator import SQLValidator
from backend.services.query_executor import QueryExecutor
from backend.services.schema_service import SchemaService
from backend.services.session_manager import (
    get_history,
    add_turn,
)
from backend.services.session_manager import get_session_credentials
from backend.db.connection import create_pool

logger   = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/query", tags=["Query"])

# ── Shared instances for demo mode ───────────────────────────
_demo_gemini    = None
_demo_schema    = None
_confidence     = ConfidenceEvaluator()
_validator      = SQLValidator()


def _get_demo_instances():
    """Lazy-initialise demo mode singletons on first request."""
    global _demo_gemini, _demo_schema

    if _demo_gemini is None:
        _demo_gemini = GeminiProvider()
        logger.info("Demo GeminiProvider initialised.")

    if _demo_schema is None:
        _demo_schema = SchemaService()
        logger.info("Demo SchemaService initialised.")

    return _demo_gemini, _demo_schema


# ── Route ─────────────────────────────────────────────────────

@router.post("", response_model=QueryResponse)
async def run_query(body: QueryRequest) -> QueryResponse:
    """
    Main pipeline endpoint.

    Accepts a natural language question and returns:
      - The generated SQL
      - Query results as columns + rows
      - Any warnings about the query
      - Error message if something failed

    NOTE: explanation is NOT generated here — it is generated
    on-demand only when the user clicks "Explain" via POST /explain.
    This avoids unnecessary LLM calls and reduces cost.

    Steps:
      1. Resolve services (demo vs custom)
      2. Get conversation history
      3. Classify question (valid / invalid)
      4. Generate SQL via LLM
      5. Evaluate confidence (warnings)
      6. Validate SQL (safety)
      7. Execute query
      8. Store turn in session history
      9. Return response (no explanation — on-demand only)
    """

    question   = body.question
    session_id = body.session_id
    database_url = None  # set below for custom mode

    logger.info(f"Query received | session={session_id} | question='{question}'")

    # ── Step 1 : Resolve services based on mode ───────────────
    if body.mode == AppMode.DEMO:
        gemini, schema_svc = _get_demo_instances()
        executor = QueryExecutor()

    elif body.mode == AppMode.CUSTOM:
        creds = get_session_credentials(session_id)

        if not creds:
            raise HTTPException(
                status_code=401,
                detail="Session credentials not found. Call /session/init first."
            )

        database_url, gemini_api_key = creds

        try:
            await create_pool(database_url)
        except Exception as e:
            logger.error(f"Failed to connect to user database: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Cannot connect to your database: {str(e)}"
            )

        gemini     = GeminiProvider(api_key=gemini_api_key)
        schema_svc = SchemaService(database_url=database_url)
        executor   = QueryExecutor(database_url=database_url)

    else:
        raise HTTPException(status_code=400, detail="Invalid mode")

    classifier = ClassifierService(gemini=gemini)
    nl_to_sql  = NLToSQLService(
        gemini=gemini,
        database_url=database_url if body.mode == AppMode.CUSTOM else None
    )

    # ── Step 2 : Get conversation history ─────────────────────
    history = get_history(session_id)

    # ── Step 3a : Ambiguity check ─────────────────────────────
    is_ambiguous, level = ClassifierService.is_ambiguous(question)

    if is_ambiguous and level == "high":
        return QueryResponse(
            success    = False,
            question   = question,
            error      = "Your query is too vague. Please provide more details.",
            warnings   = [
                WarningDetail(
                    code="AMBIGUOUS_QUERY",
                    message="Query is too vague. Add more details like filters, metrics, or entities."
                )
            ],
            session_id = session_id,
        )

    # ── Step 3b : Schema relevance (Layer 1) ──────────────────
    schema_text = await schema_svc.get_prompt_text()

    if not ClassifierService.is_schema_relevant(question, schema_text):
        return QueryResponse(
            success    = False,
            question   = question,
            error      = "Query is not related to the database schema.",
            warnings   = [
                WarningDetail(
                    code="OUT_OF_SCOPE",
                    message="This question cannot be answered using the current database."
                )
            ],
            session_id = session_id,
        )

    # ── Step 3c : LLM Classifier ──────────────────────────────
    classification = await classifier.classify(question, schema_text)

    if not classification.is_valid:
        logger.info(f"Query rejected by classifier: {classification.reason}")
        return QueryResponse(
            success       = False,
            question      = question,
            generated_sql = None,
            error         = classification.reason,
            session_id    = session_id,
        )

    # ── Step 4 : Generate SQL ─────────────────────────────────
    try:
        sql = await nl_to_sql.generate(question, history)
    except RuntimeError as e:
        logger.error(f"SQL generation failed: {e}")
        return QueryResponse(
            success       = False,
            question      = question,
            generated_sql = None,
            error         = str(e),
            session_id    = session_id,
        )

    # ── Step 5 : Confidence evaluation ────────────────────────
    confidence = _confidence.evaluate(sql, question)
    warnings   = confidence.warnings

    if is_ambiguous and level == "low":
        warnings.append(WarningDetail(
            code="AMBIGUOUS_QUERY",
            message="Query was ambiguous. Assumed best interpretation."
        ))

    # ── Step 6 : Validate SQL ─────────────────────────────────
    validation = _validator.validate(sql)

    if not validation.is_valid:
        logger.warning(f"SQL failed validation: {validation.reason}")
        return QueryResponse(
            success       = False,
            question      = question,
            generated_sql = sql,
            error         = validation.reason,
            warnings      = warnings,
            session_id    = session_id,
        )

    # ── Step 7 : Execute ──────────────────────────────────────
    try:
        result = await executor.execute(validation.sanitised_sql)
    except RuntimeError as e:
        logger.error(f"Query execution failed: {e}")
        return QueryResponse(
            success       = False,
            question      = question,
            generated_sql = validation.sanitised_sql,
            error         = str(e),
            warnings      = warnings,
            session_id    = session_id,
        )

    if result["truncated"]:
        warnings.append(WarningDetail(
            code    = "LARGE_RESULT",
            message = (
                f"Results were capped at {settings.MAX_RESULT_ROWS} rows. "
                "Add a more specific filter to see all matching records."
            ),
        ))

    # ── Step 8 : Store turn ───────────────────────────────────
    add_turn(session_id, question, validation.sanitised_sql)

    # ── Step 9 : Return response ──────────────────────────────
    # explanation is intentionally omitted here — generated on-demand
    # only when user clicks the Explain button (POST /explain).
    logger.info(
        f"Query success | session={session_id} | "
        f"rows={result['row_count']} | warnings={len(warnings)}"
    )

    return QueryResponse(
        success       = True,
        question      = question,
        generated_sql = validation.sanitised_sql,
        explanation   = None,   # ← never generated eagerly
        columns       = result["columns"],
        rows          = result["rows"],
        row_count     = result["row_count"],
        returned_rows = result["returned_rows"],
        total_rows    = result["total_rows"],
        truncated     = result["truncated"],
        warnings      = warnings,
        session_id    = session_id,
    )