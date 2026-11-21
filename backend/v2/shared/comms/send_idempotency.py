"""Provider idempotency keys for outbound email (L11 item 6).

A unit of work that may be retried (one outbox handler run, one campaign
delivery) opens a scope named after its own durable id. Every email sent
inside the scope gets the key ``<scope>:<recipient hash>:<n>``, where ``n``
counts the sends to that recipient within the scope, and the Resend adapter
puts it in its ``Idempotency-Key`` header. A retry of the same unit mints the
same keys for the same people, so the provider drops what already went out
(Resend keeps a key for 24 hours). Keying by recipient rather than by overall
send order matters: a retry that resolves its audience in a different order
must never land one family's key on another family and have the provider
report that second family "already sent".

A contextvar rather than a ``send()`` argument so the dozens of adapters
between the outbox and the port need no change. Outside a scope no key is
minted and the request is exactly what it was before.

The recipient part is a short SHA-256 of the lower-cased address, so no
address lands in a header or a log line.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class _Scope:
    name: str
    sent: dict[str, int] = field(default_factory=dict)


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


def next_send_idempotency_key(recipient_email: str) -> str | None:
    """The key for the next send to ``recipient_email`` in the current scope,
    or ``None`` outside one."""
    scope = _SCOPE.get()
    if scope is None:
        return None
    who = hashlib.sha256(recipient_email.strip().lower().encode()).hexdigest()[:16]
    scope.sent[who] = scope.sent.get(who, 0) + 1
    suffix = f":{who}:{scope.sent[who]}"
    return scope.name[: MAX_KEY_LENGTH - len(suffix)] + suffix
