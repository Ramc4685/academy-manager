"""Hand-made invoices leave an actor trail and survive a double-submit (#727).

The real ``compose_admin`` closure, so the wiring under test is what the route
calls: "Create invoice" used to mint a fresh ULID per call and derive its
idempotency key from it, so a double-click made two blank drafts, and it wrote
no ``billing_audit`` row at all — unlike "Bill this month" next to it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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


async def _create(admin, *, request_id: str | None = "req-0123456789abcdef") -> dict:
    return await admin.create_student_invoice(
        student_id="student-1",
        parent_id="parent-1",
        period="2026-06",
        due_date=date(2026, 6, 30),
        enrollment_id=None,
        actor_id="admin-7",
        request_id=request_id,
    )


async def test_create_student_invoice_is_idempotent_on_retry(admin_db) -> None:
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        first = await _create(admin)
        second = await _create(admin)

    assert second["invoice_id"] == first["invoice_id"]
    assert await admin_db["invoices"].count_documents({}) == 1


async def test_create_student_invoice_writes_an_audit_entry(admin_db) -> None:
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        created = await _create(admin)
        entries = await admin.list_billing_audit(invoice_id=created["invoice_id"])

    assert [entry["action"] for entry in entries] == ["invoice_hand_created"]
    assert entries[0]["actor_id"] == "admin-7"
    assert entries[0]["parent_id"] == "parent-1"


async def test_create_student_invoice_retry_does_not_duplicate_the_audit_entry(
    admin_db,
) -> None:
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        created = await _create(admin)
        await _create(admin)
        entries = await admin.list_billing_audit(invoice_id=created["invoice_id"])

    assert len(entries) == 1


async def test_create_student_invoice_without_a_request_id_still_creates(admin_db) -> None:
    """Older clients (and the direct use-case callers) send no request id."""
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        first = await _create(admin, request_id=None)
        second = await _create(admin, request_id=None)

    assert second["invoice_id"] != first["invoice_id"]
    assert await admin_db["invoices"].count_documents({}) == 2
