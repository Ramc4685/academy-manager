"""Provider idempotency keys for outbound email (L11 item 6).

A unit of work that may be retried — one outbox handler run, one campaign
delivery — opens a scope named after its own durable id. Every email sent
inside the scope gets the key ``<scope>:<n>``, numbered in send order, which
the Resend adapter puts in its ``Idempotency-Key`` header. A retry of the same
unit replays the same sends in the same order, so it mints the same keys and
the provider drops what already went out (Resend keeps a key for 24 hours).

A contextvar rather than a ``send()`` argument so the dozens of adapters
between the outbox and the port need no change. Outside a scope no key is
minted and the request is exactly what it was before.

shortcut: sends run concurrently inside one scope (``asyncio.gather``) are
numbered in completion order, which a retry may not reproduce; no current
scope sends concurrently. Give each concurrent send its own scope if one does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _Scope:
    name: str
    sent: int = 0


_SCOPE: ContextVar[_Scope | None] = ContextVar("send_idempotency_scope", default=None)

#: Resend refuses longer keys.
MAX_KEY_LENGTH = 256


@contextmanager
def send_idempotency_scope(name: str) -> Iterator[None]:
    token = _SCOPE.set(_Scope(name=name))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def current_send_idempotency_scope() -> str | None:
    scope = _SCOPE.get()
    return scope.name if scope else None


def next_send_idempotency_key() -> str | None:
    """The key for the next send in the current scope, or ``None`` outside one."""
    scope = _SCOPE.get()
    if scope is None:
        return None
    scope.sent += 1
    suffix = f":{scope.sent}"
    return scope.name[: MAX_KEY_LENGTH - len(suffix)] + suffix
