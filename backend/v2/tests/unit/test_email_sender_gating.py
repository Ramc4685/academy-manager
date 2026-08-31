"""``_build_email_sender`` wraps every send path in the suppression gate (#556).

Also pins the regression that wrapping introduces: ``composition/admin.py``
decides whether the local/test "email delivery is not enabled" block applies by
asking ``isinstance(sender, StubEmailSendPort)``. Once the sender is a
``GatedEmailSendPort`` decorator, that check is False in *every* environment
unless the wrapper is unwrapped first — which would let a dev stack believe it
has a real sender.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.v2.composition.digests import _build_email_sender, unwrap_send_port
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort


class _FakeDb:
    """Just enough of a Mongo database for the repository constructors."""

    def __getitem__(self, name: str) -> object:
        return object()


def _settings(**overrides: object) -> SimpleNamespace:
    base = {
        "sender_email": "noreply@example.com",
        "frontend_url": "https://example.com",
        "env": "test",
        "email_delivery_enabled": False,
        "resend_api_key": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_sender_built_with_a_db_is_suppression_gated() -> None:
    sender = _build_email_sender(_settings(), db=_FakeDb())
    assert isinstance(sender, GatedEmailSendPort)
    assert sender.suppressions is not None


def test_sender_built_without_a_db_is_ungated() -> None:
    """The ops digest deliberately stays ungated — it reports that mail is broken."""
    sender = _build_email_sender(_settings())
    assert not isinstance(sender, GatedEmailSendPort)
    assert isinstance(sender, StubEmailSendPort)


def test_gating_does_not_disarm_the_local_test_safety_block() -> None:
    sender = _build_email_sender(_settings(), db=_FakeDb())
    assert isinstance(unwrap_send_port(sender), StubEmailSendPort)
