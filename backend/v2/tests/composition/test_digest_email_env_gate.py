"""Environment gate on the coach-digest email sender.

``_build_digest_parts`` wires the sender for BOTH ``SendCoachDailyDigest`` (the
hourly scheduler) and the admin-triggered ``SendCoachDigestTest``. It used to
check only ``email_delivery_enabled`` + ``resend_api_key`` with no environment
check, so a dev/test stack booted from a prod-shaped env file would e-mail real
coaches from a development database. The gate must match
``_build_email_sender``/``compose_admin``: the real Resend adapter is only wired
in staging/prod (AGENTS.md: "Do not send real email from local/test
environments", and ``ResendEmailSendPort``'s own contract).

Nothing here sends anything: every assertion is on which *port object*
composition returns.

Since #556 the composed sender is a ``GatedEmailSendPort`` decorator (the
suppression seam), so these assertions go through ``unwrap_send_port``: an
``isinstance`` check on the wrapper is False for *every* adapter and would
turn this whole file into a tripwire that can never fire again.
"""

from __future__ import annotations

import mongomock_motor
import pytest
from backend.v2.composition.digests import (
    compose_send_coach_daily_digest,
    compose_send_coach_digest_test,
    unwrap_send_port,
)
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.shared.config import get_settings


@pytest.fixture
def db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client["test_db"]


@pytest.fixture
def delivery_credentials(monkeypatch):
    """A prod-shaped email configuration, environment left to each test.

    This is the dangerous inheritance case: the delivery flag and a live Resend
    key are both present on a stack that is not staging/prod.
    """
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("V2_RESEND_API_KEY", "test-key")
    monkeypatch.setenv("V2_SENDER_EMAIL", "noreply@example.test")
    yield
    get_settings.cache_clear()


def _set_env(monkeypatch, env: str) -> None:
    # V2_ENV wins over the APP_ENV fallback whenever it is present (CI sets
    # V2_ENV=test at the job level), so set both.
    monkeypatch.setenv("V2_ENV", env)
    monkeypatch.setenv("APP_ENV", env)
    get_settings.cache_clear()


@pytest.mark.parametrize("env", ["dev", "test"])
def test_coach_daily_digest_uses_stub_outside_staging_and_prod(
    db, delivery_credentials, monkeypatch, env: str
) -> None:
    _set_env(monkeypatch, env)

    use_case = compose_send_coach_daily_digest(db)

    assert isinstance(unwrap_send_port(use_case.sender), StubEmailSendPort), (
        f"the hourly coach digest wired the real Resend adapter in env={env!r}; "
        "a dev stack that inherited EMAIL_DELIVERY_ENABLED + RESEND_API_KEY "
        "would e-mail real coaches"
    )


@pytest.mark.parametrize("env", ["dev", "test"])
def test_coach_digest_test_uses_stub_outside_staging_and_prod(
    db, delivery_credentials, monkeypatch, env: str
) -> None:
    _set_env(monkeypatch, env)

    use_case = compose_send_coach_digest_test(db)

    assert isinstance(unwrap_send_port(use_case.sender), StubEmailSendPort), (
        f"the admin-triggered coach digest test wired the real Resend adapter in env={env!r}"
    )


def test_coach_daily_digest_uses_resend_in_approved_env(
    db, delivery_credentials, monkeypatch
) -> None:
    """The gate must not break real delivery where it is supposed to happen.

    ``staging`` stands in for both approved environments — ``prod`` additionally
    requires the full production settings block (mongo/firebase/stripe), which
    is orthogonal to this gate.
    """
    _set_env(monkeypatch, "staging")

    use_case = compose_send_coach_daily_digest(db)

    assert isinstance(unwrap_send_port(use_case.sender), ResendEmailSendPort)
    # ...and the real adapter is still behind the suppression gate.
    assert isinstance(use_case.sender, GatedEmailSendPort)


def test_coach_daily_digest_uses_stub_without_credentials(db, monkeypatch) -> None:
    _set_env(monkeypatch, "staging")
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "false")
    monkeypatch.delenv("V2_RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        use_case = compose_send_coach_daily_digest(db)
        assert isinstance(unwrap_send_port(use_case.sender), StubEmailSendPort)
    finally:
        get_settings.cache_clear()
