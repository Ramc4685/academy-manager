"""Small in-memory rate limiter for public write endpoints.

State is process-local: buckets live in a plain dict on the middleware
instance. Scaling Fly beyond one machine silently voids the limits (each
machine counts independently) — a shared-store limiter is out of scope
here (see GAPS.md #3).
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Awaitable, Callable
from math import ceil

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

Clock = Callable[[], float]

_PUBLIC_WRITE_PATHS = {
    ("POST", "/api/v2/register/parent"),
    ("POST", "/api/v2/parent/onboarding/start"),
    # Unauthenticated one-time-token consume: token entropy makes brute force
    # infeasible, but unlimited anonymous POSTs would let one client hammer
    # Mongo and the Firebase Admin API (issue #546).
    ("POST", "/api/v2/magic-link/consume"),
}

# Paths with their own (limit, window_seconds), overriding the instance
# defaults. The Stripe webhook ceiling is deliberately high: signature
# verification already rejects garbage, this only caps volumetric abuse,
# and Stripe retries with backoff on 429 so no event is lost.
_PATH_LIMIT_OVERRIDES: dict[tuple[str, str], tuple[int, int]] = {
    ("POST", "/api/v2/parent/webhooks/stripe"): (600, 60),
}

_PROXY_AUTH_HEADER = "x-cm-proxy-auth"

# Authenticated parent endpoints where every accepted request creates a real
# Stripe Checkout/Portal session. Limited per authenticated user (issue #546):
# a scripted parent looping one of these would otherwise burn the platform-wide
# Stripe API budget and break checkout for every academy. Exact-match POSTs;
# the invoice-pay retry path carries an id and is matched structurally in
# `_is_stripe_session_path`.
_STRIPE_SESSION_PATHS = {
    "/api/v2/parent/checkout/start",
    "/api/v2/parent/autopay/start",
    "/api/v2/parent/billing/portal",
    "/api/v2/parent/invoices/pay-balance",
}

_INVOICE_PAY_PREFIX = "/api/v2/parent/invoices/"
_INVOICE_PAY_SUFFIX = "/pay"


def _is_stripe_session_path(method: str, path: str) -> bool:
    if method != "POST":
        return False
    if path in _STRIPE_SESSION_PATHS:
        return True
    # POST /api/v2/parent/invoices/{invoice_id}/pay
    return (
        path.startswith(_INVOICE_PAY_PREFIX)
        and path.endswith(_INVOICE_PAY_SUFFIX)
        and len(path) > len(_INVOICE_PAY_PREFIX) + len(_INVOICE_PAY_SUFFIX)
    )


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local fixed-window limiter for unauthenticated public writes.

    Client keying (behind Fly + the Cloudflare-hosted BFF proxy,
    ``request.client.host`` is the proxy hop, not the end client):

    1. If the request carries ``x-cm-proxy-auth`` matching the configured
       proxy shared secret → trust ``CF-Connecting-IP`` (the end-client IP
       Cloudflare stamped; the BFF proxy forwards it unchanged).
    2. Else → ``Fly-Client-IP`` (stamped by Fly's edge; unforgeable by the
       client, correct for direct-to-Fly hits).
    3. Else → ``request.client.host`` (local dev/tests), else ``"unknown"``.

    A direct client without the secret is keyed by its own Fly-Client-IP no
    matter what headers it forges.
    """

    def __init__(
        self,
        app,
        *,
        limit: int = 20,
        window_seconds: int = 60,
        max_buckets: int = 10_000,
        clock: Clock | None = None,
        proxy_shared_secret: str | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_buckets = max_buckets
        self._clock = clock or time.monotonic
        self._proxy_shared_secret = proxy_shared_secret
        # key -> (window_started_at, count, window_seconds)
        self._buckets: dict[tuple[str, str], tuple[float, int, int]] = {}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        limit_window = self._limit_for(request)
        if limit_window is None:
            return await call_next(request)
        limit, window_seconds = limit_window

        key = (self._client_key(request), request.url.path)
        now = self._clock()
        self._evict_expired(now)
        window_started_at, count, _ = self._buckets.get(key, (now, 0, window_seconds))
        elapsed = now - window_started_at
        if elapsed >= window_seconds:
            window_started_at = now
            count = 0

        count += 1
        self._buckets[key] = (window_started_at, count, window_seconds)
        self._evict_over_capacity()
        if count <= limit:
            return await call_next(request)

        retry_after = max(1, ceil(window_seconds - elapsed))
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Please try again later.",
                    "details": {"retry_after_seconds": retry_after},
                }
            },
            headers={"Retry-After": str(retry_after)},
        )

    def _limit_for(self, request: Request) -> tuple[int, int] | None:
        method_path = (request.method.upper(), request.url.path)
        override = _PATH_LIMIT_OVERRIDES.get(method_path)
        if override is not None:
            return override
        if method_path in _PUBLIC_WRITE_PATHS:
            return (self._limit, self._window_seconds)
        if (
            request.method.upper() == "PATCH"
            and request.url.path.startswith("/api/v2/parent/onboarding/")
            and not request.url.path.endswith("/status")
        ):
            return (self._limit, self._window_seconds)
        return None

    def _client_key(self, request: Request) -> str:
        # Truthy check: an empty-string secret must never validate (an empty
        # x-cm-proxy-auth header would pass compare_digest against it).
        if self._proxy_shared_secret:
            presented = request.headers.get(_PROXY_AUTH_HEADER)
            if presented is not None and hmac.compare_digest(presented, self._proxy_shared_secret):
                cf_connecting_ip = request.headers.get("cf-connecting-ip")
                if cf_connecting_ip:
                    return cf_connecting_ip
        fly_client_ip = request.headers.get("fly-client-ip")
        if fly_client_ip:
            return fly_client_ip
        if request.client is not None:
            return request.client.host
        return "unknown"

    def _evict_expired(self, now: float) -> None:
        expired = [
            key
            for key, (window_started_at, _, window_seconds) in self._buckets.items()
            if now - window_started_at >= window_seconds
        ]
        for key in expired:
            self._buckets.pop(key, None)

    def _evict_over_capacity(self) -> None:
        overflow = len(self._buckets) - self._max_buckets
        if overflow <= 0:
            return
        oldest = sorted(self._buckets.items(), key=lambda item: item[1][0])
        for key, _ in oldest[:overflow]:
            self._buckets.pop(key, None)


class StripeSessionRateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local fixed-window limiter for Stripe-session-creating routes.

    Keyed by the authenticated user (``request.state.auth_claims.user_id``),
    so it must run *after* ``TenancyMiddleware`` has attached claims — wire it
    with ``app.add_middleware`` **before** the tenancy middleware (Starlette
    ordering: last added runs first). Requests without claims are passed
    through untouched: the route's own auth dependency answers 401 before any
    Stripe call is made, so they cannot burn Stripe budget.

    Same process-local caveat as `InMemoryRateLimitMiddleware` (GAPS.md #3):
    scaling beyond one machine multiplies the effective limit per user by the
    machine count, which still caps volumetric abuse.
    """

    def __init__(
        self,
        app,
        *,
        limit: int = 10,
        window_seconds: int = 60,
        max_buckets: int = 10_000,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_buckets = max_buckets
        self._clock = clock or time.monotonic
        # (user_id, path) -> (window_started_at, count)
        self._buckets: dict[tuple[str, str], tuple[float, int]] = {}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _is_stripe_session_path(request.method.upper(), request.url.path):
            return await call_next(request)

        claims = getattr(request.state, "auth_claims", None)
        user_id = getattr(claims, "user_id", None)
        if not user_id:
            return await call_next(request)

        key = (user_id, request.url.path)
        now = self._clock()
        self._evict_expired(now)
        window_started_at, count = self._buckets.get(key, (now, 0))
        elapsed = now - window_started_at
        if elapsed >= self._window_seconds:
            window_started_at = now
            count = 0
            elapsed = 0.0

        count += 1
        self._buckets[key] = (window_started_at, count)
        self._evict_over_capacity()
        if count <= self._limit:
            return await call_next(request)

        retry_after = max(1, ceil(self._window_seconds - elapsed))
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Please try again later.",
                    "details": {"retry_after_seconds": retry_after},
                }
            },
            headers={"Retry-After": str(retry_after)},
        )

    def _evict_expired(self, now: float) -> None:
        expired = [
            key
            for key, (window_started_at, _) in self._buckets.items()
            if now - window_started_at >= self._window_seconds
        ]
        for key in expired:
            self._buckets.pop(key, None)

    def _evict_over_capacity(self) -> None:
        overflow = len(self._buckets) - self._max_buckets
        if overflow <= 0:
            return
        oldest = sorted(self._buckets.items(), key=lambda item: item[1][0])
        for key, _ in oldest[:overflow]:
            self._buckets.pop(key, None)
