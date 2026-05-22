"""Middleware that blocks legacy /api/* routes when SaaS mode is active."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SaasLegacyRouteGuard(BaseHTTPMiddleware):
    """Return 410 Gone for any /api/* path that is not /api/v2/*.

    Only active when saas_mode=True. Installed by server.py when
    V2_SAAS_MODE env is set. Runs before routing so no legacy handler executes.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if path.startswith("/api/") and not path.startswith("/api/v2/"):
            return Response(
                content='{"detail":"Legacy routes are not available in SaaS mode."}',
                status_code=410,
                media_type="application/json",
            )
        return await call_next(request)
