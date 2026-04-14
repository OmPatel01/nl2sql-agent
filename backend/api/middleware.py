# Middleware for CORS, logging, error handling
import logging
import time
import uuid

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with method, path, status code,
    and response time. Attaches a unique request ID to
    each request for tracing across log lines.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start      = time.perf_counter()

        # Attach request ID so downstream handlers can log it
        request.state.request_id = request_id

        logger.info(
            f"[{request_id}] → {request.method} {request.url.path}"
        )

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                f"[{request_id}] ✗ Unhandled error after {elapsed:.1f}ms: {e}"
            )
            return JSONResponse(
                status_code = 500,
                content     = {
                    "detail"    : "An unexpected server error occurred.",
                    "request_id": request_id,
                },
            )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            f"[{request_id}] ← {response.status_code} ({elapsed:.1f}ms)"
        )

        # Pass request ID back in response headers for client-side debugging
        response.headers["X-Request-ID"] = request_id
        return response


def setup_cors(app, allowed_origins: list[str]) -> None:
    """
    Attaches CORS middleware to the FastAPI app.
    Called once during app startup in main.py.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = allowed_origins,
        allow_credentials = True,
        allow_methods     = ["GET", "POST", "DELETE"],
        allow_headers     = ["*"],
    )