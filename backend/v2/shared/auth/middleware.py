"""Auth + tenancy middleware.

SaaS contract (ADR-0007):

1. Resolve the academy tenant from the request via ``TenantResolver``
   (subdomain → custom domain → approved internal header). Tenant is
   NEVER inferred from the user.
2. If the request carries an ``Authorization: Bearer <token>`` header AND
   the tenant resolved, call ``load_auth_claims(token, resolved_academy_id)``
   to verify the token, look up the global user, validate an active
   ``academy_memberships`` row, and load platform roles.
3. Attach the resulting ``AuthClaims`` to ``request.state.auth_claims`` and
   set the tenant ``ContextVar`` to the resolved ``academy_id``.
4. Unauthenticated public routes (e.g. ``/api/v2/healthz``) still flow
   through. Protected routes raise 401 via ``Depends(get_auth_claims)``
   when no claims were attached.

``default_academy_id`` is NEVER used by this middleware. If tenant
resolution fails, no claims are attached; protected routes will 401.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.tenancy.context import _current as _tenant_var

log = logging.getLogger(__name__)


# Type aliases for the injected callables.
LoadAuthClaimsCallable = Callable[..., Awaitable[AuthClaims]]
"""``async (id_token: str, *, resolved_academy_id: str) -> AuthClaims``.

The middleware always passes ``resolved_academy_id`` as a keyword to make
the SaaS contract explicit at the call site.
"""

ResolveTenantCallable = Callable[[Request], Awaitable[Optional[str]]]
"""``async (request: Request) -> academy_id | None``.

Returns the resolved ``academy_id`` or ``None`` when the request cannot be
mapped to a known tenant. Implementations should swallow
``TenantResolutionError`` and return ``None``; the middleware never falls
back to a default tenant.
"""


class TenancyMiddleware(BaseHTTPMiddleware):
    """Resolve tenant, verify token, set request.state.auth_claims + tenant ContextVar."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        load_auth_claims: LoadAuthClaimsCallable | None = None,
        resolve_tenant: ResolveTenantCallable | None = None,
    ) -> None:
        super().__init__(app)
        # Both ports are optional — main.py wires the real callables at
        # startup. When either is None, the middleware is effectively a
        # pass-through and protected routes 401 via their dependency.
        self._load_claims = load_auth_claims
        self._resolve_tenant = resolve_tenant

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # --- 1. Resolve tenant from the request (never from the user) -----
        resolved_academy_id: str | None = None
        if self._resolve_tenant is not None:
            try:
                resolved_academy_id = await self._resolve_tenant(request)
            except Exception as exc:  # defensive: never let resolver kill the app
                log.info("tenant_resolve_failed: %s", exc)
                resolved_academy_id = None

        # --- 2. Verify token + load claims only when tenant is known -----
        token = self._extract_bearer(request)
        claims: AuthClaims | None = None
        if token and resolved_academy_id and self._load_claims is not None:
            try:
                claims = await self._load_claims(
                    token, resolved_academy_id=resolved_academy_id
                )
            except DomainError as exc:
                # Catch the shared base — concrete subclasses (InvalidToken,
                # UserNotFound, UserInactive, MembershipNotFound) live in
                # contexts/identity/, which `shared/` cannot import
                # (ADR-0005 layering). The route's Depends(get_auth_claims)
                # raises 401 if it actually needs auth; unauthenticated
                # routes (healthz) keep working.
                log.info("auth_failed: %s", exc.code)

        # --- 3. Set request.state + tenant ContextVar --------------------
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
