"""Tenant context.

Holds the current `academy_id` in a ContextVar so repositories can pick it up
without application code passing it around. The auth middleware (W1A-02) is the
sole producer; everything else is a consumer.

See ADR-0006.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class TenantContextUnset(RuntimeError):
    """Raised when a repository runs without a tenant scope set.

    Hitting this is always a bug — either the request bypassed auth or a
    background task was started without explicit tenant scoping.
    """


_current: ContextVar[str | None] = ContextVar("v2_current_academy_id", default=None)

#: Origins that legitimately serve the request's resolved tenant, derived from
#: stored records + server config (never from the raw Host header). Consumed by
#: the redirect allowlist so a dynamically onboarded academy can check out on
#: its own host. See ``shared/tenancy/origins.py``.
_current_origins: ContextVar[tuple[str, ...]] = ContextVar("v2_current_tenant_origins", default=())


def current_academy_id() -> str:
    value = _current.get()
    if value is None:
        raise TenantContextUnset(
            "No academy_id in context. Either auth middleware did not set one, "
            "or a background task ran outside a `tenant_scope(...)` block."
        )
    return value


def current_tenant_origins() -> tuple[str, ...]:
    """Return the resolved tenant's own origins, or ``()`` when none are set.

    Unlike :func:`current_academy_id` this never raises: background jobs,
    non-SaaS deployments and requests that resolve no tenant legitimately have
    no tenant origins, and callers simply fall back to the static allowlist.
    """
    return _current_origins.get()


def set_tenant_origins(origins: tuple[str, ...]) -> object:
    """Set the current tenant origins. Returns a token usable with reset()."""
    return _current_origins.set(origins)


def reset_tenant_origins(token: object) -> None:
    """Reset the tenant-origins ContextVar using a token from ``set_tenant_origins``."""
    _current_origins.reset(token)  # type: ignore[arg-type]


@contextmanager
def tenant_origins_scope(origins: tuple[str, ...]) -> Iterator[None]:
    """Set tenant origins for the duration of the block (tests, background jobs)."""
    token = _current_origins.set(origins)
    try:
        yield
    finally:
        _current_origins.reset(token)


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
