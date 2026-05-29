"""Small in-memory rate limiter for public write endpoints."""

from __future__ import annotations

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
}


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local fixed-window limiter for unauthenticated public writes."""

    def __init__(
        self,
        app,
        *,
        limit: int = 20,
        window_seconds: int = 60,
        max_buckets: int = 10_000,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_buckets = max_buckets
        self._clock = clock or time.monotonic
        self._buckets: dict[tuple[str, str], tuple[float, int]] = {}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._is_limited_path(request):
            return await call_next(request)

        key = (self._client_key(request), request.url.path)
        now = self._clock()
        self._evict_expired(now)
        window_started_at, count = self._buckets.get(key, (now, 0))
        elapsed = now - window_started_at
        if elapsed >= self._window_seconds:
            window_started_at = now
            count = 0

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

    @staticmethod
    def _is_limited_path(request: Request) -> bool:
        method_path = (request.method.upper(), request.url.path)
        if method_path in _PUBLIC_WRITE_PATHS:
            return True
        return (
            request.method.upper() == "PATCH"
            and request.url.path.startswith("/api/v2/parent/onboarding/")
            and not request.url.path.endswith("/status")
        )

    @staticmethod
    def _client_key(request: Request) -> str:
        if request.client is not None:
            return request.client.host
        return "unknown"

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._window_seconds
        expired = [
            key
            for key, (window_started_at, _) in self._buckets.items()
            if window_started_at < cutoff
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
