"""Request correlation context (audit C2).

`RequestContextMiddleware` assigns each request an id (inbound `X-Request-ID`,
Fly's `Fly-Request-Id`, or a fresh uuid) and holds it in a ContextVar for the
duration of the request. `ContextLogFilter` copies that id — plus the tenant
from `backend.v2.shared.tenancy` when resolved — onto every log record, which
lights up the dormant `request_id`/`academy_id` fields in `logging.py`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.v2.shared.tenancy.context import TenantContextUnset, current_academy_id

REQUEST_ID_HEADER = "X-Request-ID"
FLY_REQUEST_ID_HEADER = "Fly-Request-Id"

# Inbound ids are client-controlled: only accept short, log/tag-safe values
# (Sentry truncates tags >200 chars; forged junk must not pollute logs).
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_request_id: ContextVar[str | None] = ContextVar("v2_request_id", default=None)


def current_request_id() -> str | None:
    """Return the id of the request being handled, or None outside a request."""
    return _request_id.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generate/propagate a per-request id and echo it on the response.

    Added last in `create_app()` so it runs outermost (Starlette: last added
    runs first) — the id exists before tenancy/rate-limit middleware run and
    is present on their 401/429 responses too.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER) or request.headers.get(
            FLY_REQUEST_ID_HEADER
        )
        request_id = inbound if inbound and _SAFE_REQUEST_ID.fullmatch(inbound) else uuid4().hex
        token = _request_id.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _request_id.reset(token)


class ContextLogFilter(logging.Filter):
    """Stamp request_id/academy_id contextvars onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id.get()
        if request_id is not None:
            record.request_id = request_id
        try:
            record.academy_id = current_academy_id()
        except TenantContextUnset:
            pass
        return True
