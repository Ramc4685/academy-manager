"""Auth + tenancy middleware.

Reads the ``Authorization: Bearer <id_token>`` header (if any), calls the
Identity context's `load_auth_claims` use case, attaches `AuthClaims` to
`request.state`, and sets the tenant ContextVar.

Routes that need auth depend on `Depends(get_auth_claims)`, which reads
``request.state.auth_claims`` (set here). Unauthenticated requests still
flow through — only the protected routes raise 401.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive, UserNotFound
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.tenancy.context import _current as _tenant_var

log = logging.getLogger(__name__)


class TenancyMiddleware(BaseHTTPMiddleware):
    """Verify token (if present), set request.state.auth_claims + tenant ContextVar."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        load_auth_claims: Callable[[str], Awaitable[AuthClaims]] | None = None,
    ) -> None:
        super().__init__(app)
        # Optional injection — main.py wires the real use case at startup.
        # When None, the middleware is a pass-through (used by tests that
        # override the auth dependency directly).
        self._load_claims = load_auth_claims

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        token = self._extract_bearer(request)
        claims: AuthClaims | None = None

        if token and self._load_claims is not None:
            try:
                claims = await self._load_claims(token)
            except (InvalidToken, UserNotFound, UserInactive) as exc:
                # We don't 401 here — the route's `Depends(get_auth_claims)`
                # will raise 401 if it actually needs auth. Unauthenticated
                # routes (healthz) keep working.
                log.info("auth_failed: %s", exc.code)

        tenant_token = None
        if claims is not None:
            request.state.auth_claims = claims
            tenant_token = _tenant_var.set(claims.academy_id)

        try:
            return await call_next(request)
        finally:
            if tenant_token is not None:
                _tenant_var.reset(tenant_token)

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        header = request.headers.get("authorization")
        if not header:
            return None
        parts = header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        token = parts[1].strip()
        return token or None
