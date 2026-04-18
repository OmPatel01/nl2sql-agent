# backend/api/routes/query.py
# Handles POST /query — main NL query endpoint
import logging
import time
from fastapi import APIRouter, BackgroundTasks, HTTPException
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
    get_session_credentials,
)
from backend.services.query_logger import LogEntry, query_logger
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
async def run_query(
    body: QueryRequest,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    """
    Main pipeline endpoint.

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
      (Background) Write structured log entry
    """

    question   = body.question
    session_id = body.session_id
    database_url = None

    t_start = time.perf_counter()
    logger.info(f"Query received | session={session_id} | question='{question}'")

    # ── Initialise log entry (filled in progressively) ────────
    entry = LogEntry(
        session_id = session_id,
        mode       = body.mode.value,
        question   = question,
    )

    def _finish_and_log(response: QueryResponse) -> QueryResponse:
        """Finalise the log entry and schedule background write."""
        entry.latency_total = round(time.perf_counter() - t_start, 3)
        background_tasks.add_task(query_logger.write, entry)
        return response

    # ── Step 1 : Resolve services based on mode ───────────────
    if body.mode == AppMode.DEMO:
        gemini, schema_svc = _get_demo_instances()
        executor = QueryExecutor()

    elif body.mode == AppMode.CUSTOM:
        creds = get_session_credentials(session_id)
        if not creds:
            entry.status      = "failed"
            entry.error       = "Session credentials not found."
            entry.error_stage = "auth"
            _finish_and_log(None)
            raise HTTPException(
                status_code=401,
                detail="Session credentials not found. Call /session/init first."
            )

        database_url, gemini_api_key = creds
        try:
            await create_pool(database_url)
        except Exception as e:
            logger.error(f"Failed to connect to user database: {e}")
            entry.status      = "failed"
            entry.error       = str(e)
            entry.error_stage = "db_connect"
            _finish_and_log(None)
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
        entry.status = "rejected"
        entry.error  = "Query too vague."
        entry.error_stage = "ambiguity_check"
        return _finish_and_log(QueryResponse(
            success    = False,
            question   = question,
            error      = "Your query is too vague. Please provide more details.",
            warnings   = [WarningDetail(
                code    = "AMBIGUOUS_QUERY",
                message = "Query is too vague. Add more details like filters, metrics, or entities."
            )],
            session_id = session_id,
        ))

    # ── Step 3b : Schema relevance check ──────────────────────
    schema_text = await schema_svc.get_prompt_text()

    if not ClassifierService.is_schema_relevant(question, schema_text):
        entry.status      = "rejected"
        entry.error       = "Query not related to schema."
        entry.error_stage = "schema_relevance"
        return _finish_and_log(QueryResponse(
            success    = False,
            question   = question,
            error      = "Query is not related to the database schema.",
            warnings   = [WarningDetail(
                code    = "OUT_OF_SCOPE",
                message = "This question cannot be answered using the current database."
            )],
            session_id = session_id,
        ))

    # ── Step 3c : LLM Classifier ──────────────────────────────
    t_classify = time.perf_counter()
    classification = await classifier.classify(question, schema_text)
    entry.latency_classify = round(time.perf_counter() - t_classify, 3)

    if not classification.is_valid:
        logger.info(f"Query rejected by classifier: {classification.reason}")
        entry.status      = "rejected"
        entry.error       = classification.reason
        entry.error_stage = "classifier"
        return _finish_and_log(QueryResponse(
            success       = False,
            question      = question,
            generated_sql = None,
            error         = classification.reason,
            session_id    = session_id,
        ))

    # ── Step 4 : Generate SQL ─────────────────────────────────
    t_generate = time.perf_counter()
    try:
        sql = await nl_to_sql.generate(question, history)
    except RuntimeError as e:
        logger.error(f"SQL generation failed: {e}")
        entry.status      = "failed"
        entry.error       = str(e)
        entry.error_stage = "sql_generation"
        entry.latency_generate = round(time.perf_counter() - t_generate, 3)
        return _finish_and_log(QueryResponse(
            success       = False,
            question      = question,
            generated_sql = None,
            error         = str(e),
            session_id    = session_id,
        ))

    entry.latency_generate = round(time.perf_counter() - t_generate, 3)
    entry.generated_sql    = sql

    # ── Step 5 : Confidence evaluation ────────────────────────
    confidence = _confidence.evaluate(sql, question)
    warnings   = confidence.warnings

    if is_ambiguous and level == "low":
        warnings.append(WarningDetail(
            code    = "AMBIGUOUS_QUERY",
            message = "Query was ambiguous. Assumed best interpretation."
        ))

    entry.warning_codes = [w.code for w in warnings]

    # ── Step 6 : Validate SQL ─────────────────────────────────
    validation = _validator.validate(sql)

    if not validation.is_valid:
        logger.warning(f"SQL failed validation: {validation.reason}")
        entry.status      = "failed"
        entry.error       = validation.reason
        entry.error_stage = "sql_validation"
        return _finish_and_log(QueryResponse(
            success       = False,
            question      = question,
            generated_sql = sql,
            error         = validation.reason,
            warnings      = warnings,
            session_id    = session_id,
        ))

    # ── Step 7 : Execute ──────────────────────────────────────
    t_execute = time.perf_counter()
    try:
        result = await executor.execute(validation.sanitised_sql)
    except RuntimeError as e:
        logger.error(f"Query execution failed: {e}")
        entry.status      = "failed"
        entry.error       = str(e)
        entry.error_stage = "execution"
        entry.latency_execute = round(time.perf_counter() - t_execute, 3)
        return _finish_and_log(QueryResponse(
            success       = False,
            question      = question,
            generated_sql = validation.sanitised_sql,
            error         = str(e),
            warnings      = warnings,
            session_id    = session_id,
        ))

    entry.latency_execute = round(time.perf_counter() - t_execute, 3)

    if result["truncated"]:
        warnings.append(WarningDetail(
            code    = "LARGE_RESULT",
            message = (
                f"Results were capped at {settings.MAX_RESULT_ROWS} rows. "
                "Add a more specific filter to see all matching records."
            ),
        ))
        entry.warning_codes = [w.code for w in warnings]

    # ── Step 8 : Store turn ───────────────────────────────────
    add_turn(session_id, question, validation.sanitised_sql)

    # ── Finalise log entry ────────────────────────────────────
    entry.status    = "success"
    entry.row_count = result["row_count"]
    entry.truncated = result["truncated"]

    logger.info(
        f"Query success | session={session_id} | "
        f"rows={result['row_count']} | warnings={len(warnings)}"
    )

    # ── Step 9 : Return response ──────────────────────────────
    return _finish_and_log(QueryResponse(
        success       = True,
        question      = question,
        generated_sql = validation.sanitised_sql,
        explanation   = None,
        columns       = result["columns"],
        rows          = result["rows"],
        row_count     = result["row_count"],
        returned_rows = result["returned_rows"],
        total_rows    = result["total_rows"],
        truncated     = result["truncated"],
        warnings      = warnings,
        session_id    = session_id,
    ))