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
from backend.db.connection import create_pool  # ← need this

logger   = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/query", tags=["Query"])

# ── Shared instances for demo mode ───────────────────────────
# Initialised once — reused across all demo requests.
# Custom mode creates fresh instances per request using user credentials.

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

    Steps:
      1. Resolve services (demo vs custom)
      2. Get conversation history
      3. Classify question (valid / invalid)
      4. Generate SQL via LLM
      5. Evaluate confidence (warnings)
      6. Validate SQL (safety)
      7. Execute query
      8. Store turn in session history
      9. Return response
    """

    question   = body.question
    session_id = body.session_id

    logger.info(f"Query received | session={session_id} | question='{question}'")

    # ── Step 1 : Resolve services based on mode ───────────────
    if body.mode == AppMode.DEMO:
        gemini, schema_svc = _get_demo_instances()
        executor = QueryExecutor()  # Uses settings.DATABASE_URL
        
    elif body.mode == AppMode.CUSTOM:
        # Fetch credentials from session store
        creds = get_session_credentials(session_id)
        
        if not creds:
            raise HTTPException(
                status_code=401,
                detail="Session credentials not found. Call /session/init first."
            )
        
        database_url, gemini_api_key = creds
        
        try:
            # Create fresh pool for this user's database
            pool = await create_pool(database_url)
        except Exception as e:
            logger.error(f"Failed to connect to user database: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Cannot connect to your database: {str(e)}"
            )
        
        # Create instances with user's credentials
        gemini     = GeminiProvider(api_key=gemini_api_key)
        schema_svc = SchemaService(database_url=database_url)
        executor   = QueryExecutor(database_url=database_url)
    
    else:
        raise HTTPException(status_code=400, detail="Invalid mode")

    classifier = ClassifierService(gemini=gemini)
    nl_to_sql  = NLToSQLService(gemini=gemini, database_url=database_url if body.mode == AppMode.CUSTOM else None)

    # ── Step 2 : Get conversation history ─────────────────────
    history = get_history(session_id)

    # ── Step 3a : Ambiguity check ───────────────────────────
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

    # ── Step 3 : Classify ─────────────────────────────────────
    schema_text    = await schema_svc.get_prompt_text()

    # ── Step 3b : Schema relevance (Layer 1) ────────────────
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
    confidence    = _confidence.evaluate(sql, question)
    warnings      = confidence.warnings   # may be empty

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
            generated_sql = sql,   # show what was generated even if rejected
            error         = validation.reason,
            warnings      = warnings,
            returned_rows = result["row_count"],
            total_rows    = result["total_rows"],
            truncated     = result["truncated"],
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

    # Append LARGE_RESULT warning if rows were truncated
    if result["truncated"]:
        warnings.append(WarningDetail(
            code    = "LARGE_RESULT",
            message = (
                f"Results were capped at {settings.MAX_RESULT_ROWS} rows. "
                "Add a more specific filter to see all matching records."
            ),
        ))

    # ── Step 7b : Generate explanation
    explanation = await nl_to_sql.explain(question, validation.sanitised_sql)

    # ── Step 8 : Store turn ───────────────────────────────────
    add_turn(session_id, question, validation.sanitised_sql)

    # ── Step 9 : Return response ──────────────────────────────
    logger.info(
        f"Query success | session={session_id} | "
        f"rows={result['row_count']} | warnings={len(warnings)}"
    )

    return QueryResponse(
        success       = True,
        question      = question,
        generated_sql = validation.sanitised_sql,
        explanation   = explanation, 
        columns       = result["columns"],
        rows          = result["rows"],
        row_count     = result["row_count"],
        warnings      = warnings,
        session_id    = session_id,
    )