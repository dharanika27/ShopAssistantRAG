"""Request correlation and error mapping for the API edge (E7-S1).

Two responsibilities, both required by the BRD's "never leak a stack trace"
rule (NFR-3) and the error-handling strategy's "map once, at the edge" principle:

* a request-id middleware that stamps every request/response with a correlation
  id and logs method, path, and status (AC-5) — no secrets, only routing data;
* exception handlers that translate the typed :class:`AppError` hierarchy and
  any unhandled exception into the canonical error envelope (AC-3, AC-4).

This module is the *single* place that knows the HTTP status and user-facing
message for each typed error; services raise typed errors and stay
HTTP-agnostic (error-handling-strategy.md §2).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.core.errors import AppError
from backend.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
_INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Please try again later."


@dataclass(frozen=True)
class ErrorMapping:
    """The public HTTP status, envelope code, and user message for an error."""

    status: int
    code: str
    message: str


_GEMINI_UNAVAILABLE = ErrorMapping(
    status=503,
    code="GEMINI_UNAVAILABLE",
    message="The AI assistant is temporarily unavailable. Please try again in a few moments.",
)

# Maps a typed error's internal ``code`` to its public envelope (api-contracts.md).
_ERROR_MAP: dict[str, ErrorMapping] = {
    "EMBEDDING_UNAVAILABLE": _GEMINI_UNAVAILABLE,
    "GENERATION_UNAVAILABLE": _GEMINI_UNAVAILABLE,
    "PINECONE_UNAVAILABLE": ErrorMapping(
        status=503,
        code="PINECONE_UNAVAILABLE",
        message="Product search is temporarily unavailable. Please try again later.",
    ),
    "MYSQL_UNAVAILABLE": ErrorMapping(
        status=503,
        code="MYSQL_UNAVAILABLE",
        message="We are unable to load product details right now. Please try again later.",
    ),
    "CONFIG_ERROR": ErrorMapping(
        status=500, code=_INTERNAL_ERROR_CODE, message=_INTERNAL_ERROR_MESSAGE
    ),
}


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp each request with a correlation id and log its outcome (AC-5)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "api.request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            },
        )
        return response


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(mapping: ErrorMapping) -> JSONResponse:
    return JSONResponse(
        status_code=mapping.status,
        content={"error": {"code": mapping.code, "message": mapping.message}},
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Map a typed domain error to its envelope; log full detail server-side (AC-4)."""
    mapping = _ERROR_MAP.get(
        exc.code,
        ErrorMapping(status=500, code=_INTERNAL_ERROR_CODE, message=_INTERNAL_ERROR_MESSAGE),
    )
    logger.error(
        "api.app_error",
        extra={
            "request_id": _request_id(request),
            "error_code": exc.code,
            "mapped_code": mapping.code,
            "detail": str(exc),
        },
    )
    return _envelope(mapping)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Map any unhandled exception to a 500 envelope with no trace (AC-3)."""
    logger.error(
        "api.unhandled_error",
        exc_info=exc,
        extra={"request_id": _request_id(request), "error_type": type(exc).__name__},
    )
    return _envelope(
        ErrorMapping(status=500, code=_INTERNAL_ERROR_CODE, message=_INTERNAL_ERROR_MESSAGE)
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the typed and catch-all exception handlers to ``app`` (AC-3, AC-4)."""
    app.add_exception_handler(AppError, handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected_error)
