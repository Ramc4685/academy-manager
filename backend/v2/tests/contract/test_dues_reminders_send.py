"""Regression tests for the dues-reminder send path.

Previously ``_DuesReminderSender`` in ``compose_admin`` was a hardcoded stub
that unconditionally returned ``blocked: True`` with a "Local/test safety
block" message, regardless of environment or email configuration -- no
reminder email was ever actually sent, in any environment. These exercise the
real ``compose_admin`` wiring (not a route fake) against an in-process Mongo:

- by default (no approved environment configured) sending stays blocked, so
  the stub sender's always-``ok=True`` response can never be reported as a
  real send;
- in an approved environment with delivery enabled, reminders are resolved
  through active parent memberships (not the raw ``list_dues_followup`` email
  join, which can be stale for a parent with invoices in more than one
  academy) and delivered through the configured ``EmailSendPort``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    SendDuesRemindersCommand,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _FakeOutbox:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def admin_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.delenv("EMAIL_DELIVERY_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("V2_RESEND_API_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


@pytest.fixture
def approved_env(monkeypatch):
    """Staging/prod with delivery enabled -- the only combination that should
    ever pick the real ``ResendEmailSendPort``. The outbound network call
    itself is stubbed so the test stays hermetic."""
    import resend

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("V2_RESEND_API_KEY", "test-key")
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "resend-msg-1"})
    get_settings.cache_clear()


def _use_cases(db):
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _seed_membership_and_user(db, parent_id: str, *, email: str, display_name: str) -> None:
    await db["academy_memberships"].insert_one(
        {
            "academy_id": ACAD,
            "user_id": parent_id,
            "roles": ["parent"],
            "status": "active",
        }
    )
    await db["users"].insert_one(
        {
            "academy_id": ACAD,
            "user_id": parent_id,
            "email": email,
            "display_name": display_name,
        }
    )


async def _seed_open_invoice(
    db, parent_id: str, *, invoice_id: str, balance_due_cents: int
) -> None:
    await db["invoices"].insert_one(
        {
            "academy_id": ACAD,
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "status": "open",
            "balance_due_cents": balance_due_cents,
            "is_deleted": False,
            "created_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_send_dues_reminders_blocked_by_default_environment(admin_db) -> None:
    await _seed_membership_and_user(
        admin_db, "parent-1", email="parent1@example.com", display_name="Parent One"
    )
    await _seed_open_invoice(admin_db, "parent-1", invoice_id="inv-1", balance_due_cents=15_000)
    use_cases = _use_cases(admin_db)

    with tenant_scope(ACAD):
        result = await use_cases.send_dues_reminders.execute(
            SendDuesRemindersCommand(parent_ids=None)
        )

    assert result["blocked"] is True
    assert result["sent"] == 0
    assert "email delivery is not enabled" in result["reason"]


@pytest.mark.asyncio
async def test_send_dues_reminders_delivers_via_membership_in_approved_env(
    admin_db, approved_env
) -> None:
    await _seed_membership_and_user(
        admin_db, "parent-1", email="parent1@example.com", display_name="Parent One"
    )
    await _seed_open_invoice(admin_db, "parent-1", invoice_id="inv-1", balance_due_cents=15_000)
    use_cases = _use_cases(admin_db)

    with tenant_scope(ACAD):
        result = await use_cases.send_dues_reminders.execute(
            SendDuesRemindersCommand(parent_ids=None)
        )

    assert result["blocked"] is False
    assert result["reason"] is None
    assert result["sent"] == 1


@pytest.mark.asyncio
async def test_send_dues_reminders_skips_parent_without_active_membership(
    admin_db, approved_env
) -> None:
    # An invoice exists but the parent has no membership row in this academy
    # (e.g. their canonical user doc belongs to a different academy) -- the
    # old email-join lookup would have produced a stale/missing email here.
    await _seed_open_invoice(
        admin_db, "parent-no-membership", invoice_id="inv-2", balance_due_cents=5_000
    )
    use_cases = _use_cases(admin_db)

    with tenant_scope(ACAD):
        result = await use_cases.send_dues_reminders.execute(
            SendDuesRemindersCommand(parent_ids=None)
        )

    assert result["blocked"] is False
    assert result["sent"] == 0
    assert result["reason"] == (
        "1 parent(s) skipped (no active membership, no email on file, or delivery failed)."
    )
