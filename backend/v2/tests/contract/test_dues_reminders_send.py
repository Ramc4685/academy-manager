"""Regression test for the dues-reminder send path.

Previously ``_DuesReminderSender`` in ``compose_admin`` was a hardcoded stub
that unconditionally returned ``blocked: True`` with a "Local/test safety
block" message, regardless of environment or email configuration -- no
reminder email was ever actually sent, in any environment. This exercises the
real ``compose_admin`` wiring (not a route fake) against an in-process Mongo
to prove reminders are now delivered through the configured ``EmailSendPort``.
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
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


def _use_cases(db):
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _seed_parent_with_open_invoice(db) -> None:
    await db["users"].insert_one(
        {
            "academy_id": ACAD,
            "user_id": "parent-1",
            "email": "parent1@example.com",
            "display_name": "Parent One",
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": ACAD,
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
            "status": "open",
            "balance_due_cents": 15_000,
            "is_deleted": False,
            "created_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_send_dues_reminders_actually_delivers_email(admin_db) -> None:
    await _seed_parent_with_open_invoice(admin_db)
    use_cases = _use_cases(admin_db)

    with tenant_scope(ACAD):
        result = await use_cases.send_dues_reminders.execute(
            SendDuesRemindersCommand(parent_ids=None)
        )

    assert result["blocked"] is False
    assert result["reason"] is None
    assert result["sent"] == 1


@pytest.mark.asyncio
async def test_send_dues_reminders_skips_parents_without_email(admin_db) -> None:
    await admin_db["invoices"].insert_one(
        {
            "academy_id": ACAD,
            "invoice_id": "inv-2",
            "parent_id": "parent-no-email",
            "status": "open",
            "balance_due_cents": 5_000,
            "is_deleted": False,
            "created_at": NOW,
        }
    )
    use_cases = _use_cases(admin_db)

    with tenant_scope(ACAD):
        result = await use_cases.send_dues_reminders.execute(
            SendDuesRemindersCommand(parent_ids=None)
        )

    assert result["blocked"] is False
    assert result["sent"] == 0
    assert result["reason"] == "1 parent(s) skipped (no email on file or delivery failed)."
