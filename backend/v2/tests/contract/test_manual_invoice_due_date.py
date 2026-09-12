"""Hand-made invoices date themselves from Billing rules (#739).

The real ``compose_admin`` closure, so the wiring that reads
``billing_settings.invoice_due_days`` is what is under test — a hard-coded 7
here gave a family two due dates for one month and made month close report
``charge_on_varies``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _FakeOutbox:
    async def append(self, event: object) -> None:  # pragma: no cover - unused here
        return None


@pytest.fixture
def admin_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
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


async def _seed_due_days(db, days: int) -> None:
    await db["billing_settings"].insert_one({"academy_id": ACAD, "invoice_due_days": days})


async def test_create_student_invoice_defaults_the_due_date_to_the_billing_rule(
    admin_db,
) -> None:
    await _seed_due_days(admin_db, 14)
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        created = await admin.create_student_invoice(
            student_id="student-1",
            parent_id="parent-1",
            period="2026-06",
            due_date=None,
            enrollment_id=None,
        )

    assert created["due_date"] == (date.today() + timedelta(days=14)).isoformat()


async def test_create_student_invoice_keeps_an_explicit_due_date(admin_db) -> None:
    await _seed_due_days(admin_db, 14)
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        created = await admin.create_student_invoice(
            student_id="student-1",
            parent_id="parent-1",
            period="2026-06",
            due_date=date(2026, 6, 30),
            enrollment_id=None,
        )

    assert created["due_date"] == "2026-06-30"


async def test_create_student_invoice_falls_back_to_seven_days_with_no_settings(
    admin_db,
) -> None:
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        created = await admin.create_student_invoice(
            student_id="student-1",
            parent_id="parent-1",
            period="2026-06",
            due_date=None,
            enrollment_id=None,
        )

    assert created["due_date"] == (date.today() + timedelta(days=7)).isoformat()
