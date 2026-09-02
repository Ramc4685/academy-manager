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
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.config import get_settings
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.tenancy.context import _current as _tenant_var
from backend.v2.shared.tenancy.context import _current_origins as _tenant_origins_var

log = logging.getLogger(__name__)

BFF_AUTH_HEADER = "x-courtmastr-auth"
BFF_IDENTITY_HEADER = "x-courtmastr-identity"


# Type aliases for the injected callables.
LoadAuthClaimsCallable = Callable[..., Awaitable[AuthClaims]]
"""``async (id_token: str, *, resolved_academy_id: str) -> AuthClaims``.

The middleware always passes ``resolved_academy_id`` as a keyword to make
the SaaS contract explicit at the call site.
"""

ResolveTenantCallable = Callable[[Request], Awaitable[str | None]]
"""``async (request: Request) -> academy_id | None``.

Returns the resolved ``academy_id`` or ``None`` when the request cannot be
mapped to a known tenant. Implementations should swallow
``TenantResolutionError`` and return ``None``; the middleware never falls
back to a default tenant.
"""

CheckTenantServableCallable = Callable[[str], Awaitable[tuple[bool, str | None]]]
"""``async (academy_id: str) -> (servable, reason)``.

Called after tenant resolution and before request handlers for tenant-scoped
routes. This keeps suspended/cancelled tenants from serving business traffic
while allowing platform routes to inspect and repair tenant state.
"""

LoadTenantOriginsCallable = Callable[[str], Awaitable[tuple[str, ...]]]
"""``async (academy_id: str) -> origins``.

Returns the ``scheme://host[:port]`` origins that legitimately serve this
tenant, rebuilt from stored records + server config (see
``shared/tenancy/origins.py``). Never derived from the raw request Host, which
is attacker-controlled and may only select *which* academy. Consumed by the
Stripe redirect allowlist so a dynamically onboarded academy can check out on
its own host.
"""


class TenancyMiddleware(BaseHTTPMiddleware):
    """Resolve tenant, verify token, set request.state.auth_claims + tenant ContextVar."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        load_auth_claims: LoadAuthClaimsCallable | None = None,
        resolve_tenant: ResolveTenantCallable | None = None,
        check_tenant_servable: CheckTenantServableCallable | None = None,
        load_tenant_origins: LoadTenantOriginsCallable | None = None,
    ) -> None:
        super().__init__(app)
        # Both ports are optional — main.py wires the real callables at
        # startup. When either is None, the middleware is effectively a
        # pass-through and protected routes 401 via their dependency.
        self._load_claims = load_auth_claims
        self._resolve_tenant = resolve_tenant
        self._check_tenant_servable = check_tenant_servable
        self._load_tenant_origins = load_tenant_origins
        settings = get_settings()
        self._tenancy_mode = settings.tenancy_mode
        self._primary_academy_id = settings.primary_academy_id

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # --- 1. Resolve tenant from the request (never from the user) -----
        resolved_academy_id: str | None = None
        if self._resolve_tenant is not None:
            try:
                resolved_academy_id = await self._resolve_tenant(request)
            except Exception as exc:  # defensive: never let resolver kill the app
                log.info("tenant_resolve_failed: %s", exc)
                resolved_academy_id = None

        if (
            resolved_academy_id
            and self._tenancy_mode == "single_academy"
            and resolved_academy_id != self._primary_academy_id
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "Platform.TenantForbidden",
                        "message": "Tenant is not allowed in single-academy launch mode.",
                        "details": {"academy_id": resolved_academy_id},
                    }
                },
            )

        if (
            resolved_academy_id
            and self._check_tenant_servable is not None
            and not request.url.path.startswith("/api/v2/platform/")
        ):
            try:
                servable, reason = await self._check_tenant_servable(resolved_academy_id)
            except Exception as exc:
                log.info("tenant_status_check_failed: %s", exc)
                servable, reason = False, "tenant_status_unavailable"
            if not servable:
                return JSONResponse(
                    status_code=423,
                    content={
                        "error": {
                            "code": "Platform.TenantNotServable",
                            "message": "Tenant is not currently servable.",
                            "details": {
                                "academy_id": resolved_academy_id,
                                "reason": reason,
                            },
                        }
                    },
                )

        # --- 2. Verify token + load claims only when tenant is known -----
        token = self._extract_bearer(request)
        claims: AuthClaims | None = None
        auth_error_code: str | None = None
        if token and resolved_academy_id and self._load_claims is not None:
            try:
                claims = await self._load_claims(token, resolved_academy_id=resolved_academy_id)
            except DomainError as exc:
                # Catch the shared base — concrete subclasses (InvalidToken,
                # UserNotFound, UserInactive, MembershipNotFound) live in
                # contexts/identity/, which `shared/` cannot import
                # (ADR-0005 layering). The route's Depends(get_auth_claims)
                # raises 401 if it actually needs auth; unauthenticated
                # routes (healthz) keep working.
                log.info("auth_failed: %s", exc.code)
                auth_error_code = exc.code
        elif token and not resolved_academy_id:
            # A bearer token arrived but no tenant resolved, so the claims
            # loader never ran; without a marker this 401 is
            # indistinguishable from a bad token on the login surface.
            auth_error_code = "Auth.TenantUnresolved"
        # Only the machine-readable code crosses this boundary — never the
        # exception message, which may embed user ids or emails.
        request.state.auth_error_code = auth_error_code

        # Expose the resolved tenant (if any) on request.state so public
        # routes that intentionally run before membership is established
        # — e.g. ``/api/v2/register/parent`` — can pick up the tenant
        # from the request host without re-resolving. Routes that
        # require an authenticated membership keep using
        # ``request.state.auth_claims``.
        request.state.resolved_academy_id = resolved_academy_id

        # Origins that legitimately serve THIS tenant, rebuilt from stored
        # records + server config. The raw Host only selected which academy;
        # it is never allowlisted verbatim (see shared/tenancy/origins.py).
        tenant_origins: tuple[str, ...] = ()
        if resolved_academy_id and self._load_tenant_origins is not None:
            try:
                tenant_origins = await self._load_tenant_origins(resolved_academy_id)
            except Exception as exc:  # defensive: degrade to static allowlist
                log.info("tenant_origins_failed: %s", exc)
                tenant_origins = ()
        request.state.tenant_origins = tenant_origins

        # --- 3. Set request.state + tenant ContextVar --------------------
        tenant_token = None
        if claims is not None:
            request.state.auth_claims = claims
            tenant_token = _tenant_var.set(claims.academy_id)
        origins_token = _tenant_origins_var.set(tenant_origins)

        try:
            return await call_next(request)
        finally:
            if tenant_token is not None:
                _tenant_var.reset(tenant_token)
            _tenant_origins_var.reset(origins_token)

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        for header_name in ("authorization", BFF_AUTH_HEADER, BFF_IDENTITY_HEADER):
            token = TenancyMiddleware._parse_bearer(request.headers.get(header_name))
            if token:
                return token
        return None

    @staticmethod
    def _parse_bearer(header: str | None) -> str | None:
        if not header:
            return None
        parts = header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        token = parts[1].strip()
        return token or None
