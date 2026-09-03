"""Domain error → HTTP error translation."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger(__name__)
# Unhandled-500 lines are emitted under a stable name so they can be searched
# and alerted on independently of this module's location.
unhandled_log = logging.getLogger("backend.v2.http")


class DomainError(Exception):
    """Base class for application/domain errors that map to HTTP responses.

    Subclasses set ``code`` (machine-readable) and ``status_code`` (HTTP).
    The route layer never catches these explicitly — the registered handler
    translates them.
    """

    code: str = "DomainError"
    status_code: int = 400

    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # Domain rejections (409 attendance conflicts, not-enrolled, etc.) are
        # expected traffic, not crashes — but they were invisible in production
        # logs, which made "could not save attendance" reports undiagnosable.
        # One structured WARNING per rejection carries the code + ids.
        log.warning(
            "domain_error %s %s -> %s %s details=%s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.code,
            exc.details,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _log_unhandled_error(request: Request, exc: Exception) -> Response:
        # Runs inside Starlette's ServerErrorMiddleware. Log one structured
        # line (request_id/academy_id arrive via ContextLogFilter) and re-raise:
        # the middleware then keeps its 500 semantics and Sentry's FastAPI
        # integration still captures the exception.
        unhandled_log.error(
            "unhandled_error %s %s",
            request.method,
            request.url.path,
            exc_info=True,
            extra={
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
            },
        )
        raise exc
