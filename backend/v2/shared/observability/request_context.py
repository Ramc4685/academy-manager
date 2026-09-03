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
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.v2.shared.tenancy.context import TenantContextUnset, current_academy_id

REQUEST_ID_HEADER = "X-Request-ID"
FLY_REQUEST_ID_HEADER = "Fly-Request-Id"

# Fly polls this every 30s; one INFO line per poll would drown real traffic.
_QUIET_PATHS = frozenset({"/api/v2/healthz"})

_request_log = logging.getLogger("backend.v2.http.request")

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


class RequestLogMiddleware:
    """Emit one structured line per request: method, route, status, latency.

    Replaces uvicorn's access log (which has neither latency nor the route
    template and bypasses the JSON formatter). Pure ASGI so the status code is
    captured from ``http.response.start`` and an exception escaping the app is
    still logged as a 500 before it propagates. Must be added *before*
    `RequestContextMiddleware` (i.e. sit inside it) so the request id is in
    context when the line is written.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code: int | None = None
        academy_id: str | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, academy_id
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # The tenancy middleware sits inside us, so its tenant_scope is
                # still open here but gone by the time our await returns.
                academy_id = _academy_id_or_none()
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self._log(scope, status_code or 500, started, academy_id)
            raise
        self._log(scope, status_code, started, academy_id)

    @staticmethod
    def _log(scope: Scope, status_code: int | None, started: float, academy_id: str | None) -> None:
        path = scope.get("path", "")
        route = scope.get("route")
        fields = {
            "method": scope.get("method"),
            "path": path,
            "route": getattr(route, "path_format", None) or path,
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if academy_id is not None:
            fields["academy_id"] = academy_id
        level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
        _request_log.log(level, "%s %s -> %s", fields["method"], path, status_code, extra=fields)


def _academy_id_or_none() -> str | None:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return None


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
