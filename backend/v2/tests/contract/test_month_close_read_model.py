"""mongomock contract tests for ``MongoMonthCloseReadModel`` (spec §9).

Seeds the raw collections the read model batches over and checks that the
shaped view reports the month a human would recognise: every tile, the four
odd checks, tenant isolation, and a degraded run that warns instead of
failing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.finance import (
    MongoTuitionDiscountSummaryQuery,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.month_close_read_model import (
    MongoMonthCloseReadModel,
)
from backend.v2.interfaces.admin.month_close_views import AdminMonthCloseView
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

# 2026-09-20 15:00Z is 10:00 America/Chicago → local date 2026-09-20, period 2026-09.
NOW = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
PERIOD = "2026-09"
DUE = date(2026, 9, 8)


def reader(db: Any, **overrides: Any) -> MongoMonthCloseReadModel:
    kwargs: dict[str, Any] = {
        "academy_timezone": academy_timezone_lookup(db),
        "connected_accounts": MongoConnectedAccountRepository(db),
        "billing_settings": MongoBillingSettingsRepository(db),
        "customers": MongoParentBillingCustomerRepository(db),
        "tuition_discounts": MongoTuitionDiscountSummaryQuery(db),
        "clock": lambda: NOW,
    }
    kwargs.update(overrides)
    return MongoMonthCloseReadModel(db, **kwargs)


async def seed_academy(db: Any, academy_id: str, timezone: str = "America/Chicago") -> None:
    await db["academies"].insert_one({"academy_id": academy_id, "timezone": timezone})


async def seed_invoice(
    db: Any,
    *,
    academy_id: str,
    invoice_id: str,
    parent_id: str | None = "par-1",
    enrollment_id: str | None = "enr-1",
    status: str = "open",
    total_cents: int = 10_000,
    balance_due_cents: int = 10_000,
    delivery_status: str = "sent",
    due_date: date | None = DUE,
    period: str = PERIOD,
    **extra: Any,
) -> None:
    await db["invoices"].insert_one(
        {
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "invoice_number": f"INV-{invoice_id}",
            "parent_id": parent_id,
            "enrollment_id": enrollment_id,
            "period": period,
            "status": status,
            "total_cents": total_cents,
            "balance_due_cents": balance_due_cents,
            "delivery_status": delivery_status,
            # Mongo stores a datetime, never a bare ``date``.
            "due_date": (
                datetime.combine(due_date, datetime.min.time(), tzinfo=UTC)
                if due_date is not None
                else None
            ),
            **extra,
        }
    )


async def seed_enrollment(
    db: Any,
    *,
    academy_id: str,
    enrollment_id: str = "enr-1",
    status: str = "active",
    autopay: str | None = "active",
) -> None:
    await db["enrollments"].insert_one(
        {"academy_id": academy_id, "enrollment_id": enrollment_id, "status": status}
    )
    if autopay is not None:
        await db["student_billing_enrollments"].insert_one(
            {
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "autopay_enrollment_status": autopay,
            }
        )


async def seed_parent(db: Any, parent_id: str = "par-1", name: str = "Parent One") -> None:
    await db["users"].insert_one({"user_id": parent_id, "display_name": name})


async def seed_charging_ready(db: Any, academy_id: str) -> None:
    """Make ``autopay_eligibility`` reachable without a Stripe connected account."""
    await db["billing_settings"].insert_one(
        {"academy_id": academy_id, "allow_platform_charge_fallback": True}
    )


async def seed_card(db: Any, academy_id: str, parent_id: str = "par-1") -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": academy_id,
            "parent_id": parent_id,
            "stripe_customer_id": f"cus_{parent_id}",
            # ``display_payment_method`` reads these two, and they are only
            # written when the primary method's setup is active.
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
        }
    )


@pytest.mark.asyncio
async def test_a_seeded_month_fills_every_tile(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    await seed_card(db, acad)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(
        db, academy_id=acad, invoice_id="inv-paid", status="paid", balance_due_cents=0
    )
    await seed_invoice(db, academy_id=acad, invoice_id="inv-open")
    await seed_invoice(
        db, academy_id=acad, invoice_id="inv-draft", status="draft", delivery_status="not_sent"
    )
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-1",
            "status": "succeeded",
            "paid_at": datetime(2026, 9, 9, tzinfo=UTC),
            "paid_amount_cents": 10_000,
        }
    )

    view = AdminMonthCloseView.model_validate(await reader(db).build(PERIOD))

    assert view.period == PERIOD
    assert view.timezone == "America/Chicago"
    assert view.invoices.generated == 2
    assert view.invoices.autopay_notices == 2
    assert view.invoices.emailed == 0
    # The draft is counted as generated but never as money: it was never sent,
    # so it owes nothing, exactly as the family page says (#736).
    assert view.money.billed_cents == 20_000
    assert view.money.collected_cents == 10_000
    assert view.money.outstanding_cents == 10_000
    assert view.money.collection_rate == 0.5
    assert view.warnings == []


@pytest.mark.asyncio
async def test_the_period_defaults_to_the_academys_local_month(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    view = await reader(db).build()

    assert view["period"] == PERIOD


@pytest.mark.asyncio
async def test_a_voided_invoice_is_counted_with_its_reason_and_kept_out_of_billed(
    db: Any, acad: str
) -> None:
    await seed_academy(db, acad)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-void",
        status="void",
        void_reason="duplicate",
        voided_at=datetime(2026, 9, 11, tzinfo=UTC),
    )

    view = await reader(db).build(PERIOD)

    assert view["invoices"]["voided"] == 1
    assert view["invoices"]["voided_cents"] == 10_000
    assert view["invoices"]["void_reasons"] == [{"reason": "duplicate", "count": 1}]
    assert view["money"]["billed_cents"] == 0


@pytest.mark.asyncio
async def test_the_autopay_run_partitions_succeeded_failed_and_pending(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    await seed_card(db, acad)
    await seed_charging_ready(db, acad)
    for n, status in ((1, "active"), (2, "active"), (3, "active")):
        await seed_enrollment(db, academy_id=acad, enrollment_id=f"enr-{n}", status=status)
    await seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-ok",
        enrollment_id="enr-1",
        status="paid",
        balance_due_cents=0,
    )
    await seed_invoice(db, academy_id=acad, invoice_id="inv-bad", enrollment_id="enr-2")
    await seed_invoice(db, academy_id=acad, invoice_id="inv-todo", enrollment_id="enr-3")
    await db["payment_attempts"].insert_one(
        {"academy_id": acad, "attempt_id": "att-1", "invoice_id": "inv-ok", "status": "succeeded"}
    )
    await db["payment_attempts"].insert_one(
        {"academy_id": acad, "attempt_id": "att-2", "invoice_id": "inv-bad", "status": "failed"}
    )
    await db["dunning_states"].insert_one(
        {"academy_id": acad, "invoice_id": "inv-bad", "status": "active", "attempt_count": 1}
    )

    run = (await reader(db).build(PERIOD))["autopay_run"]

    assert run["charge_on"] == "2026-09-08"
    assert run["has_run"] is True
    assert run["succeeded"] == {"count": 1, "cents": 10_000}
    assert run["failed"] == {"count": 1, "cents": 10_000}
    assert run["pending"] == {"count": 1, "cents": 10_000}
    assert run["scheduled"] == {"count": 3, "cents": 30_000}


def odd(view: dict[str, Any], code: str) -> dict[str, Any]:
    return next(row for row in view["odd"] if row["code"] == code)


@pytest.mark.asyncio
async def test_an_invoice_pointing_at_a_missing_enrollment_is_odd(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    # "Not tied to a class" is a legitimate hand-created invoice, not a defect.
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1", enrollment_id=None)
    # A dangling reference is the defect the check exists for.
    await seed_invoice(db, academy_id=acad, invoice_id="inv-2", enrollment_id="enr-gone")

    row = odd(await reader(db).build(PERIOD), "invoice_without_enrollment")

    assert row["count"] == 1
    assert {item["id"] for item in row["items"]} == {"inv-2"}


@pytest.mark.asyncio
async def test_a_paused_enrollment_still_invoiced_is_odd(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    await seed_enrollment(db, academy_id=acad, status="paused", autopay="paused")
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    row = odd(await reader(db).build(PERIOD), "paused_family_invoiced")

    assert row["count"] == 1
    assert row["items"][0] == {
        "kind": "family",
        "id": "par-1",
        "label": "Parent One",
        "href": "/admin/families/par-1",
    }


@pytest.mark.asyncio
async def test_autopay_active_with_no_card_is_odd(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    view = await reader(db).build(PERIOD)

    assert odd(view, "autopay_no_card")["count"] == 1
    # And the worker would not charge it, so it is not "pending" either.
    assert view["autopay_run"]["pending"]["count"] == 0


@pytest.mark.asyncio
async def test_autopay_on_a_cancelled_enrollment_is_odd(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_parent(db)
    await seed_card(db, acad)
    await seed_enrollment(db, academy_id=acad, status="cancelled")
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    row = odd(await reader(db).build(PERIOD), "autopay_on_dead_enrollment")

    assert row["count"] == 1


@pytest.mark.asyncio
async def test_another_academys_month_is_never_visible(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_academy(db, "other-academy")
    await seed_invoice(db, academy_id="other-academy", invoice_id="inv-theirs")
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "other-academy",
            "payment_id": "pay-theirs",
            "status": "succeeded",
            "paid_at": datetime(2026, 9, 9, tzinfo=UTC),
            "paid_amount_cents": 99_000,
        }
    )

    view = await reader(db).build(PERIOD)

    assert view["invoices"]["generated"] == 0
    assert view["money"]["collected_cents"] == 0


@pytest.mark.asyncio
async def test_an_empty_period_is_zeros_and_a_null_rate(db: Any, acad: str) -> None:
    await seed_academy(db, acad)

    view = AdminMonthCloseView.model_validate(await reader(db).build(PERIOD))

    assert view.invoices.generated == 0
    assert view.money.collection_rate is None
    assert [row.count for row in view.odd] == [0, 0, 0, 0]
    assert view.autopay_run.charge_on is None


@pytest.mark.asyncio
async def test_unavailable_attempts_warn_instead_of_failing(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    model = reader(db)

    async def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("payment_attempts is down")

    model._attempts_by_invoice = boom  # type: ignore[method-assign]

    view = AdminMonthCloseView.model_validate(await model.build(PERIOD))

    assert "attempts_unavailable" in view.warnings
    assert view.invoices.generated == 1


@pytest.mark.asyncio
async def test_an_unknown_card_state_suppresses_the_no_card_check(db: Any, acad: str) -> None:
    """Spec §8: never report an odd count the read model cannot stand behind."""
    await seed_academy(db, acad)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")

    class BrokenCustomers:
        async def list_academy_customers(self) -> list[dict[str, Any]]:
            raise RuntimeError("customers is down")

    view = await reader(db, customers=BrokenCustomers()).build(PERIOD)

    assert odd(view, "autopay_no_card")["count"] == 0
    assert "card_state_unavailable" in view["warnings"]


@pytest.mark.asyncio
async def test_the_tuition_discount_card_reuses_the_finance_query(db: Any, acad: str) -> None:
    await seed_academy(db, acad)
    await seed_enrollment(db, academy_id=acad)
    await seed_invoice(db, academy_id=acad, invoice_id="inv-1")
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-1",
            "line_type": "tuition",
            "amount_cents": 10_000,
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-1",
            "source_type": "tuition_discount",
            "category": "sibling",
            "amount_cents": -1_500,
        }
    )

    discounts = (await reader(db).build(PERIOD))["tuition_discounts"]

    assert discounts == {
        "gross_cents": 10_000,
        "discount_cents": 1_500,
        "net_cents": 8_500,
        "by_category": [{"category": "sibling", "amount_cents": 1_500}],
    }


@pytest.mark.asyncio
async def test_an_unknown_timezone_falls_back_to_utc(db: Any, acad: str) -> None:
    await seed_academy(db, acad, timezone="Mars/Olympus")

    view = await reader(db).build(PERIOD)

    assert view["timezone"] == "UTC"
