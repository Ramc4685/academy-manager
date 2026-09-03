"""Phase 1 payment-visibility composition tests: filtered list, feed, last-by-family."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-1"
OTHER_ACADEMY = "acad-2"


class _NoopStripe:
    pass


def _admin_use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


def _ledger_payment(
    payment_id: str,
    *,
    parent_id: str,
    amount_cents: int,
    paid_at: datetime,
    status: str = "succeeded",
    academy_id: str = ACADEMY,
    stripe_payment_intent_id: str | None = None,
) -> dict[str, Any]:
    return {
        "payment_id": payment_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "amount_cents": amount_cents,
        "refunded_cents": 0,
        "currency": "usd",
        "status": status,
        "payment_method": "card",
        "stripe_payment_intent_id": stripe_payment_intent_id,
        "paid_at": paid_at,
        "created_at": paid_at,
    }


async def _seed_parents(db: Any) -> None:
    await db["users"].insert_many(
        [
            {"academy_id": ACADEMY, "user_id": "parent-1", "display_name": "Asha Rao"},
            {"academy_id": ACADEMY, "user_id": "parent-2", "display_name": "Ben Ortiz"},
        ]
    )


@pytest.mark.asyncio
async def test_list_payments_filtered_sorts_by_paid_at_and_paginates(mongo_db) -> None:
    await _seed_parents(mongo_db)
    await mongo_db["ledger_payments"].insert_many(
        [
            _ledger_payment(
                "lp-old",
                parent_id="parent-1",
                amount_cents=5000,
                paid_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
            ),
            _ledger_payment(
                "lp-new",
                parent_id="parent-2",
                amount_cents=7500,
                paid_at=datetime(2026, 7, 6, 9, tzinfo=UTC),
            ),
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        result = await admin.list_payments_filtered(limit=1, offset=0)

    assert result["total"] == 2
    assert [row["payment_id"] for row in result["payments"]] == ["lp-new"]
    assert result["payments"][0]["parent_name"] == "Ben Ortiz"
    assert result["payments"][0]["paid_at"] == datetime(2026, 7, 6, 9, tzinfo=UTC)

    with tenant_scope(ACADEMY):
        page_two = await admin.list_payments_filtered(limit=1, offset=1)
    assert [row["payment_id"] for row in page_two["payments"]] == ["lp-old"]


@pytest.mark.asyncio
async def test_list_payments_filtered_applies_filters_and_search(mongo_db) -> None:
    await _seed_parents(mongo_db)
    await mongo_db["ledger_payments"].insert_many(
        [
            _ledger_payment(
                "lp-asha",
                parent_id="parent-1",
                amount_cents=5000,
                paid_at=datetime(2026, 7, 2, tzinfo=UTC),
            ),
            _ledger_payment(
                "lp-ben",
                parent_id="parent-2",
                amount_cents=7500,
                paid_at=datetime(2026, 6, 20, tzinfo=UTC),
            ),
            _ledger_payment(
                "lp-other-acad",
                parent_id="parent-9",
                amount_cents=100,
                paid_at=datetime(2026, 7, 3, tzinfo=UTC),
                academy_id=OTHER_ACADEMY,
            ),
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        by_name = await admin.list_payments_filtered(q="asha")
        by_window = await admin.list_payments_filtered(
            date_from=datetime(2026, 7, 1, tzinfo=UTC),
            date_to=datetime(2026, 7, 31, tzinfo=UTC),
        )
        by_status = await admin.list_payments_filtered(status="succeeded")

    assert [row["payment_id"] for row in by_name["payments"]] == ["lp-asha"]
    assert [row["payment_id"] for row in by_window["payments"]] == ["lp-asha"]
    assert {row["payment_id"] for row in by_status["payments"]} == {"lp-asha", "lp-ben"}


@pytest.mark.asyncio
async def test_payment_feed_returns_money_received_with_names(mongo_db) -> None:
    await _seed_parents(mongo_db)
    await mongo_db["ledger_payments"].insert_many(
        [
            _ledger_payment(
                "lp-1",
                parent_id="parent-1",
                amount_cents=5000,
                paid_at=datetime(2026, 7, 5, tzinfo=UTC),
                stripe_payment_intent_id="pi_shared",
            ),
        ]
    )
    await mongo_db["payments"].insert_many(
        [
            # Duplicate of the ledger payment via shared payment intent — must be deduped.
            {
                "payment_id": "legacy-dup",
                "academy_id": ACADEMY,
                "parent_id": "parent-1",
                "amount_cents": 5000,
                "refunded_cents": 0,
                "currency": "usd",
                "status": "succeeded",
                "stripe_payment_intent_id": "pi_shared",
                "paid_at": datetime(2026, 7, 5, tzinfo=UTC),
                "created_at": datetime(2026, 7, 5, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-only",
                "academy_id": ACADEMY,
                "parent_id": "parent-2",
                "amount_cents": 2500,
                "refunded_cents": 0,
                "currency": "usd",
                "status": "succeeded",
                "paid_at": datetime(2026, 7, 7, tzinfo=UTC),
                "created_at": datetime(2026, 7, 7, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-pending",
                "academy_id": ACADEMY,
                "parent_id": "parent-2",
                "amount_cents": 999,
                "refunded_cents": 0,
                "currency": "usd",
                "status": "pending",
                "created_at": datetime(2026, 7, 7, tzinfo=UTC),
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payment_feed(limit=10)

    assert [row["payment_id"] for row in rows] == ["legacy-only", "lp-1"]
    assert rows[0]["parent_name"] == "Ben Ortiz"
    assert rows[1]["parent_name"] == "Asha Rao"


@pytest.mark.asyncio
async def test_last_payment_by_family_keeps_latest_per_parent(mongo_db) -> None:
    await _seed_parents(mongo_db)
    await mongo_db["ledger_payments"].insert_many(
        [
            _ledger_payment(
                "lp-1a",
                parent_id="parent-1",
                amount_cents=5000,
                paid_at=datetime(2026, 6, 5, tzinfo=UTC),
            ),
            _ledger_payment(
                "lp-1b",
                parent_id="parent-1",
                amount_cents=6000,
                paid_at=datetime(2026, 7, 5, tzinfo=UTC),
            ),
            _ledger_payment(
                "lp-2",
                parent_id="parent-2",
                amount_cents=2500,
                paid_at=datetime(2026, 7, 6, tzinfo=UTC),
            ),
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_last_payment_by_family()

    assert [(row["parent_id"], row["amount_cents"]) for row in rows] == [
        ("parent-2", 2500),
        ("parent-1", 6000),
    ]
    assert rows[0]["last_paid_at"] == datetime(2026, 7, 6, tzinfo=UTC)
    assert rows[1]["parent_name"] == "Asha Rao"


def _invoice(
    invoice_id: str, *, parent_id: str, total_cents: int, created_at: datetime
) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_id,
        "academy_id": ACADEMY,
        "parent_id": parent_id,
        "status": "paid",
        "period": "2026-09",
        "subtotal_cents": total_cents,
        "total_cents": total_cents,
        "balance_due_cents": 0,
        "currency": "usd",
        "created_at": created_at,
    }


@pytest.mark.asyncio
async def test_stripe_settled_invoice_row_carries_paid_at_method_and_stripe_ids(mongo_db) -> None:
    """A Stripe checkout that paid an invoice must show on the invoice row, not vanish."""
    await _seed_parents(mongo_db)
    invoice_created = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    paid_at = datetime(2026, 9, 3, 17, 14, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        _invoice("inv-sep", parent_id="parent-1", total_cents=13000, created_at=invoice_created)
    )
    ledger = _ledger_payment(
        "pay-stripe",
        parent_id="parent-1",
        amount_cents=13000,
        paid_at=paid_at,
        stripe_payment_intent_id="pi_123",
    )
    ledger["payment_method"] = "stripe_checkout"
    await mongo_db["ledger_payments"].insert_one(ledger)
    await mongo_db["payment_allocations"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-stripe", "invoice_id": "inv-sep"}
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()
        filtered = await admin.list_payments_filtered(limit=10)

    assert [r["payment_id"] for r in rows] == ["inv-sep"]
    row = rows[0]
    assert row["paid_at"].replace(tzinfo=UTC) == paid_at
    assert row["payment_method"] == "stripe_checkout"
    assert row["stripe_linked"] is True
    assert row["stripe_payment_intent_id"] == "pi_123"
    assert filtered["payments"][0]["paid_at"] == paid_at


@pytest.mark.asyncio
async def test_manual_settlement_keeps_its_method_on_invoice_row(mongo_db) -> None:
    await _seed_parents(mongo_db)
    paid_at = datetime(2026, 9, 3, 14, 0, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        _invoice(
            "inv-zelle",
            parent_id="parent-2",
            total_cents=6000,
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    ledger = _ledger_payment("pay-zelle", parent_id="parent-2", amount_cents=6000, paid_at=paid_at)
    ledger["payment_method"] = "zelle"
    await mongo_db["ledger_payments"].insert_one(ledger)
    await mongo_db["payment_allocations"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-zelle", "invoice_id": "inv-zelle"}
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()

    assert len(rows) == 1
    assert rows[0]["payment_method"] == "zelle"
    assert rows[0]["stripe_linked"] is False
    assert rows[0]["paid_at"].replace(tzinfo=UTC) == paid_at


@pytest.mark.asyncio
async def test_legacy_projection_sharing_payment_id_with_ledger_appears_once(mongo_db) -> None:
    """An expired checkout mirrored into the legacy collection must not render twice."""
    created = datetime(2026, 9, 1, 15, 51, tzinfo=UTC)
    await mongo_db["ledger_payments"].insert_one(
        {
            "payment_id": "pay-expired",
            "academy_id": ACADEMY,
            "parent_id": "parent-1",
            "amount_cents": 7000,
            "currency": "usd",
            "status": "expired",
            "created_at": created,
        }
    )
    await mongo_db["payments"].insert_one(
        {
            "payment_id": "pay-expired",
            "academy_id": ACADEMY,
            "parent_id": "parent-1",
            "amount_cents": 7000,
            "currency": "usd",
            "status": "expired",
            "stripe_checkout_session_id": "cs_live_expired",
            "created_at": created,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()

    assert [r["payment_id"] for r in rows] == ["pay-expired"]


@pytest.mark.asyncio
async def test_standalone_stripe_ledger_row_is_labelled_stripe(mongo_db) -> None:
    """Registration checkouts have no invoice and often no method; still label them Stripe."""
    paid_at = datetime(2026, 9, 1, 20, 19, tzinfo=UTC)
    ledger = _ledger_payment(
        "pay-reg",
        parent_id="parent-1",
        amount_cents=7000,
        paid_at=paid_at,
        stripe_payment_intent_id="pi_reg",
    )
    ledger["payment_method"] = None
    await mongo_db["ledger_payments"].insert_one(ledger)

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()

    assert rows[0]["payment_method"] == "stripe_checkout"
    assert rows[0]["stripe_linked"] is True


@pytest.mark.asyncio
async def test_pending_attempt_does_not_settle_invoice_row(mongo_db) -> None:
    """A pending/failed attempt referencing an invoice must not mark it Stripe-linked or paid."""
    await mongo_db["invoices"].insert_one(
        {
            **_invoice(
                "inv-open",
                parent_id="parent-1",
                total_cents=7000,
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            "status": "open",
            "balance_due_cents": 7000,
        }
    )
    await mongo_db["ledger_payments"].insert_one(
        {
            "payment_id": "pay-pending",
            "academy_id": ACADEMY,
            "parent_id": "parent-1",
            "amount_cents": 7000,
            "currency": "usd",
            "status": "pending",
            "stripe_payment_intent_id": "pi_pending",
            "created_at": datetime(2026, 9, 2, tzinfo=UTC),
        }
    )
    await mongo_db["payment_allocations"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-pending", "invoice_id": "inv-open"}
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()

    assert [r["payment_id"] for r in rows] == ["inv-open"]
    assert rows[0]["status"] == "pending"
    assert rows[0]["stripe_linked"] is False
    assert rows[0]["payment_method"] == "invoice"
    assert rows[0].get("paid_at") is None


@pytest.mark.asyncio
async def test_balance_checkout_settles_every_allocated_invoice(mongo_db) -> None:
    """One ledger payment with two allocations must settle BOTH invoice rows."""
    await _seed_parents(mongo_db)
    paid_at = datetime(2026, 9, 3, 17, 14, tzinfo=UTC)
    await mongo_db["invoices"].insert_many(
        [
            _invoice(
                "inv-a",
                parent_id="parent-1",
                total_cents=6000,
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            _invoice(
                "inv-b",
                parent_id="parent-1",
                total_cents=7000,
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ]
    )
    ledger = _ledger_payment(
        "pay-balance",
        parent_id="parent-1",
        amount_cents=13000,
        paid_at=paid_at,
        stripe_payment_intent_id="pi_bal",
    )
    ledger["payment_method"] = "stripe_checkout"
    await mongo_db["ledger_payments"].insert_one(ledger)
    await mongo_db["payment_allocations"].insert_many(
        [
            {"academy_id": ACADEMY, "payment_id": "pay-balance", "invoice_id": "inv-a"},
            {"academy_id": ACADEMY, "payment_id": "pay-balance", "invoice_id": "inv-b"},
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent()

    by_id = {r["payment_id"]: r for r in rows}
    assert set(by_id) == {"inv-a", "inv-b"}
    for invoice_id in ("inv-a", "inv-b"):
        row = by_id[invoice_id]
        assert row["payment_method"] == "stripe_checkout"
        assert row["stripe_linked"] is True
        assert row["stripe_payment_intent_id"] == "pi_bal"
        assert row["paid_at"].replace(tzinfo=UTC) == paid_at


@pytest.mark.asyncio
async def test_settled_payments_are_not_crowded_out_by_newer_attempts(mongo_db) -> None:
    """Many newer pending attempts must not push the real settlement out of the fold."""
    paid_at = datetime(2026, 9, 1, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        _invoice(
            "inv-old",
            parent_id="parent-1",
            total_cents=6000,
            created_at=datetime(2026, 9, 3, tzinfo=UTC),
        )
    )
    ledger = _ledger_payment("pay-old", parent_id="parent-1", amount_cents=6000, paid_at=paid_at)
    ledger["payment_method"] = "zelle"
    await mongo_db["ledger_payments"].insert_one(ledger)
    await mongo_db["payment_allocations"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-old", "invoice_id": "inv-old"}
    )
    await mongo_db["ledger_payments"].insert_many(
        [
            {
                "payment_id": f"attempt-{n}",
                "academy_id": ACADEMY,
                "parent_id": "parent-1",
                "amount_cents": 100,
                "currency": "usd",
                "status": "pending",
                "created_at": datetime(2026, 9, 2, 0, n, tzinfo=UTC),
            }
            for n in range(8)
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_payments_recent(fetch_cap=6)

    invoice_row = next(r for r in rows if r["payment_id"] == "inv-old")
    assert invoice_row["payment_method"] == "zelle"
    assert invoice_row["paid_at"].replace(tzinfo=UTC) == paid_at


@pytest.mark.asyncio
async def test_feed_labels_stripe_rows_without_method_as_stripe_checkout(mongo_db) -> None:
    await _seed_parents(mongo_db)
    ledger = _ledger_payment(
        "pay-reg-feed",
        parent_id="parent-1",
        amount_cents=7000,
        paid_at=datetime(2026, 9, 1, tzinfo=UTC),
        stripe_payment_intent_id="pi_reg_feed",
    )
    ledger["payment_method"] = None
    await mongo_db["ledger_payments"].insert_one(ledger)

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        feed = await admin.list_payment_feed(limit=5)

    assert feed[0]["payment_method"] == "stripe_checkout"


def test_apply_settlement_keeps_real_stripe_method_over_older_settlement() -> None:
    from backend.v2.contexts.billing.application.admin_payment_settlement import apply_settlement

    row: dict[str, Any] = {"payment_method": "invoice"}
    apply_settlement(
        row,
        {
            "status": "succeeded",
            "payment_method": "stripe",
            "paid_at": datetime(2026, 9, 3, tzinfo=UTC),
        },
    )
    apply_settlement(
        row,
        {
            "status": "succeeded",
            "payment_method": "zelle",
            "paid_at": datetime(2026, 9, 1, tzinfo=UTC),
        },
    )
    assert row["payment_method"] == "stripe"
    assert row["paid_at"] == datetime(2026, 9, 3, tzinfo=UTC)
