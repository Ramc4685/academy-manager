"""Tenant context.

Holds the current `academy_id` in a ContextVar so repositories can pick it up
without application code passing it around. The auth middleware (W1A-02) is the
sole producer; everything else is a consumer.

See ADR-0006.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


class TenantContextUnset(RuntimeError):
    """Raised when a repository runs without a tenant scope set.

    Hitting this is always a bug — either the request bypassed auth or a
    background task was started without explicit tenant scoping.
    """


_current: ContextVar[str | None] = ContextVar("v2_current_academy_id", default=None)


def current_academy_id() -> str:
    value = _current.get()
    if value is None:
        raise TenantContextUnset(
            "No academy_id in context. Either auth middleware did not set one, "
            "or a background task ran outside a `tenant_scope(...)` block."
        )
    return value


def set_academy_id(academy_id: str) -> object:
    """Set the current tenant. Returns a token usable with reset()."""
    return _current.set(academy_id)


@contextmanager
def tenant_scope(academy_id: str) -> Iterator[None]:
    """Set tenant context for the duration of the block.

    Use for background tasks or scripts that need to operate as a specific
    tenant. Inside a request, the auth middleware does this for you.
    """
    token = _current.set(academy_id)
    try:
        yield
    finally:
        _current.reset(token)
