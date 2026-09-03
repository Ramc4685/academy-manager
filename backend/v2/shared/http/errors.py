"""Domain error → HTTP error translation."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


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
