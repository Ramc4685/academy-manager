"""Record payment, the Billing tab's one admin money write, against a real MongoDB.

``POST /admin/billing/invoices/{id}/record-payment`` calls the real
``compose_admin`` closure exercised here, with the production
``MongoIdempotencyStore`` and ``MongoBillingLedgerRepository`` on a real
``mongod`` with every migration applied (``real_db``): the unique indexes on
``idempotency_keys.key``, ``ledger_payments`` and ``payment_allocations`` and
the 0132 validators are the ones production has. Two concurrent submits only
interleave the way they do in production on a real server, so none of this
runs on mongomock.

This drives the use-case closure below the route, so it pins the recording
contract only, not who may call it (Record payment is owner-only per People
CRM spec §4; the route's missing owner gate is a strict xfail in
``structural/test_money_route_staff_tiers.py``). The contract pinned here:

* same ``Idempotency-Key`` twice, one after the other: one payment, the second
  call replays the first result;
* same key, concurrently: still one payment and one ledger effect;
* no key, identical payload twice (sequentially or concurrently): one payment,
  the repeat is a 409 "possible duplicate" the admin confirms with a key;
* same key, different payload: 422 and the original payment is untouched;
* a keyed retry after the process died between moving the money and caching
  the result does not record a second payment;
* academy B can never record against, or learn anything about, academy A's
  invoice, whatever the key or payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-money-a"
OTHER = "acad-money-b"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TOTAL = 7_000


class _FakeOutbox:
    async def append(self, event: object) -> None:
        return None


@pytest.fixture
def boot_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """compose_admin resolves its boot academy from settings; pin it to ACAD."""
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    yield ACAD
    get_settings.cache_clear()


def _admin(db: Any, store: Any = None) -> Any:
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=store or MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _seed_invoice(
    db: Any,
    *,
    academy_id: str = ACAD,
    invoice_id: str = "inv-money-1",
    parent_id: str = "parent-test-1",
    total_cents: int = TOTAL,
) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": invoice_id,
            "academy_id": academy_id,
            "parent_id": parent_id,
            "student_id": "student-test-1",
            "enrollment_id": "enroll-test-1",
            "period": "2026-09",
            "status": "open",
            "subtotal_cents": total_cents,
            "discount_cents": 0,
            "total_cents": total_cents,
            "balance_due_cents": total_cents,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 9, 30, tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def _pay(
    admin: Any,
    *,
    key: str | None,
    amount: int = 3_000,
    invoice_id: str = "inv-money-1",
) -> Any:
    return admin.record_manual_payment(
        invoice_id=invoice_id,
        amount_cents=amount,
        payment_method="cash",
        reference_number=None,
        notes="",
        actor_id="admin-test-1",
        idempotency_key=key,
    )


async def _ledger_state(
    db: Any, *, academy_id: str = ACAD, invoice_id: str = "inv-money-1"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    payments = [
        doc async for doc in db["ledger_payments"].find({"academy_id": academy_id}, {"_id": 0})
    ]
    allocations = [
        doc
        async for doc in db["payment_allocations"].find(
            {"academy_id": academy_id, "invoice_id": invoice_id}, {"_id": 0}
        )
    ]
    invoice = await db["invoices"].find_one(
        {"academy_id": academy_id, "invoice_id": invoice_id}, {"_id": 0}
    )
    assert invoice is not None
    return payments, allocations, invoice


# ------------------------------------------------------------------ double submit


async def test_same_key_twice_replays_one_payment(real_db, boot_academy) -> None:
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        first = await _pay(admin, key="k-double")
        second = await _pay(admin, key="k-double")
        payments, allocations, invoice = await _ledger_state(real_db)
        audits = await real_db["billing_audit_log"].count_documents(
            {"action": "manual_payment_recorded", "payment_id": first["payment_id"]}
        )

    assert second == first
    assert len(payments) == 1 and payments[0]["payment_id"] == first["payment_id"]
    assert len(allocations) == 1 and allocations[0]["amount_cents"] == 3_000
    assert invoice["balance_due_cents"] == TOTAL - 3_000
    assert invoice["status"] == "partially_paid"
    assert audits == 1


async def test_concurrent_submits_with_one_key_record_one_payment(real_db, boot_academy) -> None:
    """A double-click fires both requests before either has cached a result."""
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        results = await asyncio.gather(
            *(_pay(admin, key="k-race") for _ in range(4)), return_exceptions=True
        )
        payments, allocations, invoice = await _ledger_state(real_db)

    ok = [r for r in results if isinstance(r, dict)]
    failed = [r for r in results if not isinstance(r, dict)]
    assert ok, results
    assert len(payments) == 1, payments
    assert len(allocations) == 1, allocations
    assert invoice["balance_due_cents"] == TOTAL - 3_000
    assert payments[0]["unapplied_amount_cents"] == 0
    # Every caller that got an answer got THE payment; a caller that lost the
    # race is told the submission is in flight (409), never a second payment.
    assert {r["payment_id"] for r in ok} == {payments[0]["payment_id"]}
    assert all(isinstance(r, ValueError) and "in progress" in str(r) for r in failed), failed


async def test_keyless_identical_repeat_is_a_conflict_not_a_second_payment(
    real_db, boot_academy
) -> None:
    """Documented behaviour: without a key the repeat needs confirming (409)."""
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await _pay(admin, key=None)
        with pytest.raises(ValueError, match="possible duplicate"):
            await _pay(admin, key=None)
        payments, allocations, invoice = await _ledger_state(real_db)

    assert len(payments) == 1 and len(allocations) == 1
    assert invoice["balance_due_cents"] == TOTAL - 3_000


async def test_concurrent_keyless_identical_submits_record_one_payment(
    real_db, boot_academy
) -> None:
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        results = await asyncio.gather(
            *(_pay(admin, key=None) for _ in range(3)), return_exceptions=True
        )
        payments, allocations, invoice = await _ledger_state(real_db)

    ok = [r for r in results if isinstance(r, dict)]
    failed = [r for r in results if not isinstance(r, dict)]
    assert len(payments) == 1 and len(allocations) == 1, (payments, allocations)
    assert invoice["balance_due_cents"] == TOTAL - 3_000
    assert len(ok) == 1, results
    assert all(isinstance(r, ValueError) and "possible duplicate" in str(r) for r in failed)


async def test_distinct_keys_record_two_real_payments(real_db, boot_academy) -> None:
    """Two identical cash payments are legal when the admin confirms each one."""
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        first = await _pay(admin, key="k-one")
        second = await _pay(admin, key="k-two")
        payments, allocations, invoice = await _ledger_state(real_db)

    assert first["payment_id"] != second["payment_id"]
    assert len(payments) == 2 and len(allocations) == 2
    assert invoice["balance_due_cents"] == TOTAL - 6_000


async def test_key_reuse_with_a_different_payload_is_rejected_and_changes_nothing(
    real_db, boot_academy
) -> None:
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        first = await _pay(admin, key="k-reuse", amount=3_000)
        before = await _ledger_state(real_db)
        with pytest.raises(ValueError, match="different payload"):
            await _pay(admin, key="k-reuse", amount=4_000)
        after = await _ledger_state(real_db)

    assert after == before
    assert [p["payment_id"] for p in after[0]] == [first["payment_id"]]
    assert after[0][0]["amount_cents"] == 3_000


class _LosesTheFirstResultWrite(MongoIdempotencyStore):
    """The process dies after the money moved but before the result was cached."""

    def __init__(self, db: Any) -> None:
        super().__init__(db)
        self.failed = False

    async def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.failed and "payload" in value:
            self.failed = True
            raise RuntimeError("process died before caching the result")
        await super().put(key, value)


async def test_keyed_retry_after_a_crash_does_not_record_a_second_payment(
    real_db, boot_academy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.v2.contexts.billing.application import manual_payment_idempotency

    await _seed_invoice(real_db)
    admin = _admin(real_db, store=_LosesTheFirstResultWrite(real_db))
    with tenant_scope(ACAD):
        with pytest.raises(RuntimeError):
            await _pay(admin, key="k-crash")
        # The admin retries once the in-flight window has passed.
        monkeypatch.setattr(manual_payment_idempotency, "IN_FLIGHT_WINDOW", timedelta(0))
        retried = await _pay(admin, key="k-crash")
        payments, allocations, invoice = await _ledger_state(real_db)

    assert len(payments) == 1 and payments[0]["payment_id"] == retried["payment_id"]
    assert len(allocations) == 1
    assert invoice["balance_due_cents"] == TOTAL - 3_000
    assert retried["balance_due_cents"] == TOTAL - 3_000


# ------------------------------------------------------------------ tenancy


@pytest.mark.parametrize("key", [None, "k-shared"])
async def test_other_academy_cannot_record_against_or_replay_this_invoice(
    real_db, boot_academy, key: str | None
) -> None:
    """Idempotency keys are academy-scoped (#544): B never sees A's cached result.

    A records first. B then sends the SAME invoice id, payload and key. An
    unscoped cache answers B with A's payment (keyed) or with a 409 that
    confirms the invoice exists (keyless). B must get "not found", and nothing
    may be written in either academy.
    """
    await _seed_invoice(real_db)
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await _pay(admin, key=key)
        before = await _ledger_state(real_db)

    with tenant_scope(OTHER), pytest.raises(ValueError, match="not found"):
        await _pay(admin, key=key)

    with tenant_scope(ACAD):
        assert await _ledger_state(real_db) == before
    assert await real_db["ledger_payments"].count_documents({"academy_id": OTHER}) == 0
    assert await real_db["payment_allocations"].count_documents({"academy_id": OTHER}) == 0


async def test_same_key_in_two_academies_records_each_academys_own_payment(
    real_db, boot_academy
) -> None:
    """Client keys are not globally unique; two academies may pick the same one."""
    await _seed_invoice(real_db, academy_id=ACAD)
    await _seed_invoice(real_db, academy_id=OTHER, invoice_id="inv-money-b")
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        a = await _pay(admin, key="k-same")
    with tenant_scope(OTHER):
        b = await _pay(admin, key="k-same", invoice_id="inv-money-b")
        other_payments, _, other_invoice = await _ledger_state(
            real_db, academy_id=OTHER, invoice_id="inv-money-b"
        )

    assert a["payment_id"] != b["payment_id"]
    assert [p["payment_id"] for p in other_payments] == [b["payment_id"]]
    assert other_invoice["balance_due_cents"] == TOTAL - 3_000


async def test_audit_entry_is_stamped_with_the_request_academy(real_db, boot_academy) -> None:
    """Boot academy A, request academy B: the trail lands in B, where B's Billing tab reads it."""
    await _seed_invoice(real_db, academy_id=OTHER, invoice_id="inv-money-b")
    admin = _admin(real_db)
    with tenant_scope(OTHER):
        result = await _pay(admin, key="k-audit", invoice_id="inv-money-b")

    audit = await real_db["billing_audit_log"].find_one({"payment_id": result["payment_id"]})
    assert audit is not None
    assert audit["academy_id"] == OTHER
