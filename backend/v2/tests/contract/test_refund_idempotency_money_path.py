"""Refund idempotency against a real MongoDB (#930).

Both admin refund routes are owner-only money writes:

* ``POST /admin/payments/refund`` -> ``IssueRefund.execute`` (billing context);
* ``POST /admin/billing/invoices/{id}/refund`` -> the ``issue_invoice_refund``
  closure, which claims the invoice projection and then calls ``IssueRefund``.

Before #930 both deduped on the refund's SHAPE (payment/invoice + amount +
reason), so a second, legitimate refund with the same amount and reason inside
the 7-day TTL silently replayed the first result: no Stripe refund, no ledger
effect, a 200 to the owner. ``IssueRefund``'s key also carried no academy, so
two academies refunding the same payment id shared one cache entry (#544).

The contract pinned here, on the production ``MongoIdempotencyStore`` (unique
``idempotency_keys.key`` index, migrations applied) and a fake Stripe that
honours Stripe's idempotency-key semantics:

* same ``Idempotency-Key`` twice: one Stripe refund, the retry replays;
* a NEW key with the same amount and reason: a second real refund, or a loud
  rejection when it does not fit, never a silent replay;
* no key, identical repeat: a 409 "possible duplicate" the owner confirms by
  resending with a key, never a silent replay;
* the same key reused for a DIFFERENT refund: 422, nothing moves;
* the Stripe idempotency key is deterministic per request and academy-scoped;
* academies never share a cache entry, whatever the payment id or key.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefundCommand
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    RefundExceedsAmount,
    RefundIdempotencyKeyReused,
    RefundPossibleDuplicate,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-refund-a"
OTHER = "acad-refund-b"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PAID = 10_000


class _FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def boot_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    yield ACAD
    get_settings.cache_clear()


class _World:
    def __init__(self, db: Any, store: Any = None) -> None:
        self.stripe = FakeStripeGateway()
        self.outbox = _FakeOutbox()
        self.admin = compose_admin(
            db,
            outbox=self.outbox,  # type: ignore[arg-type]
            idempotency_store=store or MongoIdempotencyStore(db),
            stripe=self.stripe,
        )

    def refund_payment(
        self,
        *,
        key: str | None,
        amount: int | None = 3_000,
        reason: str = "admin_initiated",
        payment_id: str = "pay-refund-1",
    ) -> Any:
        return self.admin.issue_refund.execute(
            IssueRefundCommand(
                payment_id=payment_id,
                amount_cents=amount,
                reason=reason,
                idempotency_key=key,
            )
        )

    def refund_invoice(
        self,
        *,
        key: str | None,
        amount: int | None = 3_000,
        reason: str = "class cancelled",
        invoice_id: str = "inv-refund-1",
    ) -> Any:
        return self.admin.issue_invoice_refund(
            invoice_id=invoice_id,
            amount_cents=amount,
            reason=reason,
            actor_id="owner-test-1",
            idempotency_key=key,
        )


async def _seed_payment(
    db: Any, *, academy_id: str = ACAD, payment_id: str = "pay-refund-1", amount: int = PAID
) -> None:
    await db["payments"].insert_one(
        {
            "payment_id": payment_id,
            "academy_id": academy_id,
            "parent_id": "parent-test-1",
            "session_id": "sess-test-1",
            "stripe_payment_intent_id": f"pi_{academy_id}_{payment_id}",
            "amount_cents": amount,
            "currency": "usd",
            "status": "succeeded",
            "refunded_cents": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


async def _seed_card_invoice(
    db: Any,
    *,
    academy_id: str = ACAD,
    invoice_id: str = "inv-refund-1",
    payment_id: str = "pay-refund-1",
) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": invoice_id,
            "academy_id": academy_id,
            "parent_id": "parent-test-1",
            "student_id": "student-test-1",
            "enrollment_id": "enroll-test-1",
            "period": "2026-09",
            "status": "paid",
            "subtotal_cents": PAID,
            "discount_cents": 0,
            "total_cents": PAID,
            "balance_due_cents": 0,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 9, 30, tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await _seed_payment(db, academy_id=academy_id, payment_id=payment_id)
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": f"alloc-{academy_id}-{invoice_id}",
            "academy_id": academy_id,
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "amount_cents": PAID,
            "created_at": NOW,
        }
    )


async def _refunded(db: Any, *, academy_id: str = ACAD, payment_id: str = "pay-refund-1") -> int:
    doc = await db["payments"].find_one({"academy_id": academy_id, "payment_id": payment_id})
    assert doc is not None
    return int(doc["refunded_cents"])


async def _invoice_refunded(
    db: Any, *, academy_id: str = ACAD, invoice_id: str = "inv-refund-1"
) -> int:
    doc = await db["invoices"].find_one({"academy_id": academy_id, "invoice_id": invoice_id})
    assert doc is not None
    return int(doc["refunded_cents"])


# ------------------------------------------------------------ payment refunds


async def test_same_key_retry_replays_one_stripe_refund(real_db, boot_academy) -> None:
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        first = await world.refund_payment(key="k-retry")
        second = await world.refund_payment(key="k-retry")
        refunded = await _refunded(real_db)

    assert second == first
    assert len(world.stripe.refunds) == 1
    assert refunded == 3_000
    assert len(world.outbox.events) == 1


async def test_new_key_same_amount_and_reason_is_a_second_real_refund(
    real_db, boot_academy
) -> None:
    """The #930 bug: this second refund used to be swallowed by the first's cache."""
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        first = await world.refund_payment(key="k-first")
        second = await world.refund_payment(key="k-second")
        refunded = await _refunded(real_db)

    assert second.stripe_refund_id != first.stripe_refund_id
    assert len(world.stripe.refunds) == 2
    assert refunded == 6_000
    assert second.total_refunded_cents == 6_000
    assert len(world.outbox.events) == 2


async def test_new_key_that_does_not_fit_is_rejected_loudly(real_db, boot_academy) -> None:
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_payment(key="k-a", amount=6_000)
        with pytest.raises(RefundExceedsAmount):
            await world.refund_payment(key="k-b", amount=6_000)
        refunded = await _refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert refunded == 6_000


async def test_keyless_identical_repeat_is_a_conflict_not_a_silent_replay(
    real_db, boot_academy
) -> None:
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_payment(key=None)
        with pytest.raises(RefundPossibleDuplicate):
            await world.refund_payment(key=None)
        # The owner confirms by resending with a key: a real second refund.
        confirmed = await world.refund_payment(key="k-confirm")
        refunded = await _refunded(real_db)

    assert confirmed.refunded_cents == 3_000
    assert len(world.stripe.refunds) == 2
    assert refunded == 6_000


async def test_keyed_refund_then_keyless_identical_repeat_needs_confirming(
    real_db, boot_academy
) -> None:
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_payment(key="k-one")
        with pytest.raises(RefundPossibleDuplicate):
            await world.refund_payment(key=None)
        refunded = await _refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert refunded == 3_000


async def test_key_reused_for_a_different_refund_is_rejected(real_db, boot_academy) -> None:
    await _seed_payment(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_payment(key="k-reuse", amount=3_000)
        with pytest.raises(RefundIdempotencyKeyReused):
            await world.refund_payment(key="k-reuse", amount=4_000)
        refunded = await _refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert refunded == 3_000


class _LosesTheFirstResultWrite(MongoIdempotencyStore):
    """The process dies after Stripe refunded but before the result was cached."""

    def __init__(self, db: Any) -> None:
        super().__init__(db)
        self.failed = False

    async def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.failed and "payload" in value:
            self.failed = True
            raise RuntimeError("process died before caching the result")
        await super().put(key, value)


async def test_stripe_idempotency_key_is_deterministic_per_request(real_db, boot_academy) -> None:
    """A retry of the same request reaches Stripe with the same key, so Stripe
    (not our cache) is the backstop when the cache write was lost."""
    await _seed_payment(real_db)
    world = _World(real_db, store=_LosesTheFirstResultWrite(real_db))
    with tenant_scope(ACAD):
        with pytest.raises(RuntimeError):
            await world.refund_payment(key="k-crash")
        retried = await world.refund_payment(key="k-crash")
        other = await world.refund_payment(key="k-other")

    keys = [r["idempotency_key"] for r in world.stripe.refund_requests]
    assert len(keys) == 3
    assert keys[0] and keys[0] == keys[1] != keys[2]
    assert all(ACAD in k for k in keys)
    # Stripe replayed the first refund for the retry: one refund object, not two.
    assert len(world.stripe.refunds) == 2
    assert retried.stripe_refund_id == world.stripe.refunds[0]["refund_id"]
    assert other.stripe_refund_id == world.stripe.refunds[1]["refund_id"]


@pytest.mark.parametrize("key", [None, "k-shared"])
async def test_same_payment_id_and_key_in_two_academies_refund_independently(
    real_db, boot_academy, key: str | None
) -> None:
    """Payment ids are not globally unique (#849); keys must carry the academy (#544)."""
    await _seed_payment(real_db, academy_id=ACAD)
    await _seed_payment(real_db, academy_id=OTHER)
    world = _World(real_db)
    with tenant_scope(ACAD):
        a = await world.refund_payment(key=key)
    with tenant_scope(OTHER):
        b = await world.refund_payment(key=key)

    assert a.stripe_refund_id != b.stripe_refund_id
    assert len(world.stripe.refunds) == 2
    assert {r["payment_intent_id"] for r in world.stripe.refunds} == {
        f"pi_{ACAD}_pay-refund-1",
        f"pi_{OTHER}_pay-refund-1",
    }
    assert await _refunded(real_db, academy_id=ACAD) == 3_000
    assert await _refunded(real_db, academy_id=OTHER) == 3_000


async def test_other_academy_cannot_replay_a_cached_refund(real_db, boot_academy) -> None:
    """B sends A's payment id and key: not found, never A's cached result."""
    await _seed_payment(real_db, academy_id=ACAD)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_payment(key="k-leak")

    with tenant_scope(OTHER), pytest.raises(PaymentNotFound):
        await world.refund_payment(key="k-leak")
    assert len(world.stripe.refunds) == 1


# ------------------------------------------------------------ invoice refunds


async def test_invoice_refund_same_key_retry_replays(real_db, boot_academy) -> None:
    await _seed_card_invoice(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        first = await world.refund_invoice(key="k-inv")
        second = await world.refund_invoice(key="k-inv")
        invoice_refunded = await _invoice_refunded(real_db)
        refunded = await _refunded(real_db)
        audits = await real_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "action": "refund_issued"}
        )

    assert second == first
    assert len(world.stripe.refunds) == 1
    assert invoice_refunded == 3_000 and refunded == 3_000
    assert audits == 1


async def test_invoice_refund_new_key_same_amount_and_reason_is_recorded(
    real_db, boot_academy
) -> None:
    """The #930 bug on the Billing tab route."""
    await _seed_card_invoice(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        first = await world.refund_invoice(key="k-inv-1")
        second = await world.refund_invoice(key="k-inv-2")
        invoice_refunded = await _invoice_refunded(real_db)
        refunded = await _refunded(real_db)
        audits = await real_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "action": "refund_issued"}
        )

    assert second["stripe_refund_id"] != first["stripe_refund_id"]
    assert len(world.stripe.refunds) == 2
    assert invoice_refunded == 6_000 and refunded == 6_000
    assert audits == 2


async def test_invoice_refund_keyless_repeat_is_a_conflict(real_db, boot_academy) -> None:
    await _seed_card_invoice(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_invoice(key=None)
        with pytest.raises(RefundPossibleDuplicate):
            await world.refund_invoice(key=None)
        invoice_refunded = await _invoice_refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert invoice_refunded == 3_000


async def test_invoice_refund_key_reuse_with_other_amount_is_rejected(
    real_db, boot_academy
) -> None:
    await _seed_card_invoice(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_invoice(key="k-inv-reuse", amount=3_000)
        with pytest.raises(RefundIdempotencyKeyReused):
            await world.refund_invoice(key="k-inv-reuse", amount=2_000)
        invoice_refunded = await _invoice_refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert invoice_refunded == 3_000


async def test_invoice_refund_new_key_that_does_not_fit_is_rejected(real_db, boot_academy) -> None:
    await _seed_card_invoice(real_db)
    world = _World(real_db)
    with tenant_scope(ACAD):
        await world.refund_invoice(key="k-big-1", amount=7_000)
        with pytest.raises(ValueError, match="no refundable"):
            await world.refund_invoice(key="k-big-2", amount=7_000)
        invoice_refunded = await _invoice_refunded(real_db)

    assert len(world.stripe.refunds) == 1
    assert invoice_refunded == 7_000


@pytest.mark.parametrize("key", [None, "k-shared"])
async def test_invoice_refund_same_ids_in_two_academies_refund_independently(
    real_db, boot_academy, key: str | None
) -> None:
    await _seed_card_invoice(real_db, academy_id=ACAD)
    await _seed_card_invoice(real_db, academy_id=OTHER)
    world = _World(real_db)
    with tenant_scope(ACAD):
        a = await world.refund_invoice(key=key)
    with tenant_scope(OTHER):
        b = await world.refund_invoice(key=key)

    assert a["stripe_refund_id"] != b["stripe_refund_id"]
    assert len(world.stripe.refunds) == 2
    assert await _invoice_refunded(real_db, academy_id=ACAD) == 3_000
    assert await _invoice_refunded(real_db, academy_id=OTHER) == 3_000
    assert await _refunded(real_db, academy_id=OTHER) == 3_000
