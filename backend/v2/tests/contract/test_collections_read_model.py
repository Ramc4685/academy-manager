"""mongomock contract tests for ``MongoCollectionsReadModel``.

Seeds the raw collections the read model batches over and checks that each
family lands in the spec §2 bucket the pure classifier assigns, that tenant
isolation holds, and that bad data never breaks the build (spec §6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.collections_read_model import (
    MongoCollectionsReadModel,
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
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

# 2026-09-10 15:00Z is 10:00 America/Chicago → local date 2026-09-10, period 2026-09.
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
PERIOD = "2026-09"


def _dt(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


async def _seed_academy(db, academy_id: str, timezone: str = "America/Chicago") -> None:
    await db["academies"].insert_one({"academy_id": academy_id, "timezone": timezone})


async def _seed_family(
    db,
    *,
    academy_id: str,
    parent_id: str,
    student_id: str,
    enrollment_id: str,
    name: str = "Kid",
    session_id: str = "sess-1",
    enrollment_status: str = "active",
    autopay_status: str | None = "active",
) -> None:
    await db["users"].insert_one(
        {
            "user_id": parent_id,
            "display_name": f"Parent {parent_id}",
            "email": f"{parent_id}@example.com",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": student_id,
            "parent_id": parent_id,
            "full_name": name,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "student_id": student_id,
            "session_id": session_id,
            "status": enrollment_status,
        }
    )
    if autopay_status is not None:
        await db["student_billing_enrollments"].insert_one(
            {
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "student_id": student_id,
                "parent_id": parent_id,
                "status": "active",
                "autopay_enrollment_status": autopay_status,
            }
        )


async def _seed_session(db, *, academy_id: str, session_id: str = "sess-1") -> None:
    await db["sessions"].insert_one(
        {"academy_id": academy_id, "session_id": session_id, "title": "Monday Juniors"}
    )


async def _seed_invoice(
    db,
    *,
    academy_id: str,
    invoice_id: str,
    parent_id: str,
    student_id: str,
    enrollment_id: str | None,
    status: str = "open",
    period: str = PERIOD,
    total_cents: int = 10_000,
    balance_due_cents: int = 10_000,
    due_date: date = date(2026, 9, 15),
    last_sent_at: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    doc: dict[str, Any] = {
        "academy_id": academy_id,
        "invoice_id": invoice_id,
        "invoice_number": f"INV-{invoice_id}",
        "parent_id": parent_id,
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "period": period,
        "status": status,
        "total_cents": total_cents,
        "balance_due_cents": balance_due_cents,
        "due_date": _dt(due_date),
        "delivery_status": "sent" if last_sent_at else "not_sent",
        "last_sent_at": last_sent_at,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if extra:
        doc.update(extra)
    await db["invoices"].insert_one(doc)


async def _seed_card(db, *, academy_id: str, parent_id: str, last4: str = "4242") -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": academy_id,
            "parent_id": parent_id,
            "stripe_customer_id": f"cus_{parent_id}",
            "payment_method_label": "Visa",
            "payment_method_last4": last4,
        }
    )


async def _seed_connect_ready(db, *, academy_id: str) -> None:
    await db["academy_connected_accounts"].insert_one(
        {
            "academy_id": academy_id,
            "stripe_account_id": f"acct_{academy_id}",
            "status": "active",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "capabilities": {},
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def _read_model(db) -> MongoCollectionsReadModel:
    return MongoCollectionsReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        clock=lambda: NOW,
    )


def _bucket(view: dict[str, Any], key: str) -> dict[str, Any]:
    return next(b for b in view["buckets"] if b["key"] == key)


def _counts(view: dict[str, Any]) -> dict[str, int]:
    return {b["key"]: b["count"] for b in view["buckets"]}


@pytest.mark.asyncio
async def test_one_family_per_bucket(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_session(db, academy_id=acad)
    await _seed_connect_ready(db, academy_id=acad)

    # 1. failed_autopay: card on file, ladder tried once and failed.
    await _seed_family(
        db, academy_id=acad, parent_id="p-fail", student_id="s-fail", enrollment_id="e-fail"
    )
    await _seed_card(db, academy_id=acad, parent_id="p-fail")
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-fail",
        parent_id="p-fail",
        student_id="s-fail",
        enrollment_id="e-fail",
        due_date=date(2026, 9, 5),
    )
    await db["dunning_states"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-fail",
            "status": "active",
            "attempt_count": 1,
            "next_attempt_at": datetime(2026, 9, 12, 14, 0, tzinfo=UTC),
        }
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": acad,
            "attempt_id": "attempt-1",
            "invoice_id": "inv-fail",
            "status": "failed",
            "failure_code": "card_declined",
            "failure_message": "Your card was declined.",
            "created_at": datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
        }
    )

    # 2. past_due: autopay not active, due before today.
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-late",
        student_id="s-late",
        enrollment_id="e-late",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-late",
        parent_id="p-late",
        student_id="s-late",
        enrollment_id="e-late",
        due_date=date(2026, 9, 1),
        last_sent_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    )

    # 3. awaiting: autopay not active, due on/after today.
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-wait",
        student_id="s-wait",
        enrollment_id="e-wait",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-wait",
        parent_id="p-wait",
        student_id="s-wait",
        enrollment_id="e-wait",
        due_date=date(2026, 9, 20),
    )

    # 4. autopay_scheduled: active autopay, card on file, connect ready, no attempts.
    await _seed_family(
        db, academy_id=acad, parent_id="p-auto", student_id="s-auto", enrollment_id="e-auto"
    )
    await _seed_card(db, academy_id=acad, parent_id="p-auto", last4="1111")
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-auto",
        parent_id="p-auto",
        student_id="s-auto",
        enrollment_id="e-auto",
        due_date=date(2026, 9, 15),
    )

    # 5. paused: no invoice this period, one paused enrollment.
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-pause",
        student_id="s-pause",
        enrollment_id="e-pause",
        enrollment_status="paused",
        autopay_status=None,
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {
            "academy_id": acad,
            "deferral_id": "def-1",
            "enrollment_id": "e-pause",
            "student_id": "s-pause",
            "resume_on": "2026-10-01",
            "review_on": None,
            "status": "active",
            "created_at": NOW,
        }
    )

    # 6. paid: invoice fully paid via the ledger.
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-paid",
        student_id="s-paid",
        enrollment_id="e-paid",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-paid",
        parent_id="p-paid",
        student_id="s-paid",
        enrollment_id="e-paid",
        status="paid",
        balance_due_cents=0,
    )
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-1",
            "parent_id": "p-paid",
            "amount_cents": 10_000,
            "payment_method": "cash",
            "paid_at": datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "academy_id": acad,
            "allocation_id": "alloc-1",
            "payment_id": "pay-1",
            "invoice_id": "inv-paid",
            "amount_cents": 10_000,
            "created_at": NOW,
        }
    )

    view = await _read_model(db).build(PERIOD)

    assert [b["key"] for b in view["buckets"]] == [
        "failed_autopay",
        "past_due",
        "awaiting",
        "autopay_scheduled",
        "paused",
        "paid",
    ]
    assert _counts(view) == {key: 1 for key in _counts(view)}

    failed = _bucket(view, "failed_autopay")["families"][0]
    assert failed["parent_id"] == "p-fail"
    assert failed["parent_name"] == "Parent p-fail"
    assert failed["parent_email"] == "p-fail@example.com"
    assert failed["students"] == [
        {"student_id": "s-fail", "name": "Kid", "session_title": "Monday Juniors"}
    ]
    assert failed["failure"] == {
        "reason": "Your card was declined.",
        "attempt_count": 1,
        "max_attempts": 4,
        "next_retry_on": "2026-09-12",
        "disabled": False,
    }
    assert failed["actions"] == ["message", "record_payment"]

    late = _bucket(view, "past_due")["families"][0]
    assert late["parent_id"] == "p-late"
    assert late["balance_cents"] == 10_000
    assert late["last_reminder_at"] == "2026-09-02T12:00:00+00:00"
    assert late["autopay"] is None

    assert _bucket(view, "awaiting")["families"][0]["parent_id"] == "p-wait"

    auto = _bucket(view, "autopay_scheduled")["families"][0]
    assert auto["parent_id"] == "p-auto"
    assert auto["autopay"] == {
        "status": "eligible",
        "card_last4": "1111",
        "charge_on": "2026-09-15",
        "notice_sent_at": None,
    }

    paused = _bucket(view, "paused")["families"][0]
    assert paused["parent_id"] == "p-pause"
    assert paused["pause"] == {
        "enrollment_id": "e-pause",
        "resume_on": "2026-10-01",
        "review_on": None,
        "session_title": "Monday Juniors",
        "student_name": "Kid",
    }
    assert paused["actions"] == ["resume"]

    paid = _bucket(view, "paid")["families"][0]
    assert paid["parent_id"] == "p-paid"
    assert paid["paid"] == {
        "amount_cents": 10_000,
        "method": "cash",
        "paid_at": "2026-09-03T16:00:00+00:00",
    }

    assert view["period"] == PERIOD
    assert view["timezone"] == "America/Chicago"
    assert view["generated_at"] == NOW.isoformat()
    assert view["totals"] == {
        "owed_cents": 30_000,
        "autopay_scheduled_cents": 10_000,
        "autopay_scheduled_count": 1,
        "needs_action_count": 2,
        "collected_cents": 10_000,
    }
    assert "unclassified" not in view


@pytest.mark.asyncio
async def test_two_students_one_autopay_one_past_due_is_a_single_past_due_row(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_connect_ready(db, academy_id=acad)
    await _seed_card(db, academy_id=acad, parent_id="p-1")
    await _seed_family(
        db, academy_id=acad, parent_id="p-1", student_id="s-a", enrollment_id="e-a", name="Ana"
    )
    # Second sibling: reuse the parent's user row already inserted above.
    await db["students"].insert_one(
        {"academy_id": acad, "student_id": "s-b", "parent_id": "p-1", "full_name": "Ben"}
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "e-b",
            "student_id": "s-b",
            "session_id": "sess-1",
            "status": "active",
        }
    )
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "e-b",
            "student_id": "s-b",
            "parent_id": "p-1",
            "status": "active",
            "autopay_enrollment_status": "disabled",
        }
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-a",
        parent_id="p-1",
        student_id="s-a",
        enrollment_id="e-a",
        due_date=date(2026, 9, 15),
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-b",
        parent_id="p-1",
        student_id="s-b",
        enrollment_id="e-b",
        due_date=date(2026, 9, 1),
        balance_due_cents=5_000,
        total_cents=5_000,
    )

    view = await _read_model(db).build(PERIOD)

    assert _counts(view) == {
        "failed_autopay": 0,
        "past_due": 1,
        "awaiting": 0,
        "autopay_scheduled": 0,
        "paused": 0,
        "paid": 0,
    }
    row = _bucket(view, "past_due")["families"][0]
    assert sorted(s["name"] for s in row["students"]) == ["Ana", "Ben"]
    assert len(row["invoices"]) == 2
    assert row["balance_cents"] == 15_000


@pytest.mark.asyncio
async def test_paused_family_with_prior_month_open_invoice_carries_leftover(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-pause",
        student_id="s-pause",
        enrollment_id="e-pause",
        enrollment_status="paused",
        autopay_status=None,
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-aug",
        parent_id="p-pause",
        student_id="s-pause",
        enrollment_id="e-pause",
        period="2026-08",
        due_date=date(2026, 8, 15),
        balance_due_cents=4_500,
    )

    view = await _read_model(db).build(PERIOD)

    assert _counts(view)["paused"] == 1
    row = _bucket(view, "paused")["families"][0]
    assert row["leftover_balance_cents"] == 4_500
    assert row["invoices"] == []
    assert _bucket(view, "paused")["total_cents"] == 4_500
    assert view["totals"]["owed_cents"] == 0


@pytest.mark.asyncio
async def test_voided_invoice_is_excluded_entirely(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-void",
        student_id="s-void",
        enrollment_id="e-void",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-void",
        parent_id="p-void",
        student_id="s-void",
        enrollment_id="e-void",
        status="void",
        balance_due_cents=0,
    )

    view = await _read_model(db).build(PERIOD)

    assert all(b["count"] == 0 for b in view["buckets"])
    assert view["totals"]["collected_cents"] == 0


@pytest.mark.asyncio
async def test_autopay_active_without_card_is_awaiting_no_card_on_file(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_connect_ready(db, academy_id=acad)
    await _seed_family(
        db, academy_id=acad, parent_id="p-nocard", student_id="s-nocard", enrollment_id="e-nocard"
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-nocard",
        parent_id="p-nocard",
        student_id="s-nocard",
        enrollment_id="e-nocard",
        due_date=date(2026, 9, 20),
    )

    view = await _read_model(db).build(PERIOD)

    assert _counts(view)["awaiting"] == 1
    assert _counts(view)["autopay_scheduled"] == 0
    row = _bucket(view, "awaiting")["families"][0]
    assert row["autopay"]["status"] == "no_card_on_file"
    assert row["autopay"]["card_last4"] is None
    assert row["autopay"]["charge_on"] == "2026-09-20"


@pytest.mark.asyncio
async def test_prior_month_open_invoice_is_leftover_not_a_period_bucket(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-old",
        student_id="s-old",
        enrollment_id="e-old",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-aug",
        parent_id="p-old",
        student_id="s-old",
        enrollment_id="e-old",
        period="2026-08",
        due_date=date(2026, 8, 15),
        balance_due_cents=2_000,
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-sep",
        parent_id="p-old",
        student_id="s-old",
        enrollment_id="e-old",
        due_date=date(2026, 9, 20),
    )

    view = await _read_model(db).build(PERIOD)

    assert _counts(view) == {
        "failed_autopay": 0,
        "past_due": 0,
        "awaiting": 1,
        "autopay_scheduled": 0,
        "paused": 0,
        "paid": 0,
    }
    row = _bucket(view, "awaiting")["families"][0]
    assert [inv["invoice_id"] for inv in row["invoices"]] == ["inv-sep"]
    assert row["balance_cents"] == 10_000
    assert row["leftover_balance_cents"] == 2_000


@pytest.mark.asyncio
async def test_other_tenant_rows_never_appear(db, acad) -> None:
    await _seed_academy(db, acad)
    other = "other-academy"
    await _seed_academy(db, other)
    await _seed_family(
        db,
        academy_id=other,
        parent_id="p-other",
        student_id="s-other",
        enrollment_id="e-other",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=other,
        invoice_id="inv-other",
        parent_id="p-other",
        student_id="s-other",
        enrollment_id="e-other",
        due_date=date(2026, 9, 1),
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": other,
            "enrollment_id": "e-other-paused",
            "student_id": "s-other",
            "session_id": "sess-1",
            "status": "paused",
        }
    )
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-mine",
        student_id="s-mine",
        enrollment_id="e-mine",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-mine",
        parent_id="p-mine",
        student_id="s-mine",
        enrollment_id="e-mine",
        due_date=date(2026, 9, 1),
    )

    view = await _read_model(db).build(PERIOD)

    parents = {f["parent_id"] for b in view["buckets"] for f in b["families"]}
    assert parents == {"p-mine"}
    assert view["totals"]["owed_cents"] == 10_000


@pytest.mark.asyncio
async def test_period_none_resolves_to_current_local_month(db, acad) -> None:
    await _seed_academy(db, acad)

    view = await _read_model(db).build()

    assert view["period"] == "2026-09"
    assert view["timezone"] == "America/Chicago"


@pytest.mark.asyncio
async def test_period_none_falls_back_to_utc_when_timezone_unset(db, acad) -> None:
    await _seed_academy(db, acad, timezone="")

    view = await _read_model(db).build()

    assert view["period"] == "2026-09"
    assert view["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_orphan_invoice_lands_in_unclassified_only_when_debug(db, acad) -> None:
    await _seed_academy(db, acad)
    await _seed_family(
        db,
        academy_id=acad,
        parent_id="p-ok",
        student_id="s-ok",
        enrollment_id="e-ok",
        autopay_status="not_offered",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-ok",
        parent_id="p-ok",
        student_id="s-ok",
        enrollment_id="e-ok",
        due_date=date(2026, 9, 1),
    )
    # No parent at all on this invoice: the read model must not crash on it.
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-orphan",
        parent_id=None,
        student_id="s-none",
        enrollment_id=None,
        due_date=date(2026, 9, 1),
        extra={"parent_id": None},
    )

    plain = await _read_model(db).build(PERIOD)
    assert "unclassified" not in plain
    assert _counts(plain)["past_due"] == 1

    debug = await _read_model(db).build(PERIOD, debug=True)
    assert _counts(debug)["past_due"] == 1
    assert debug["unclassified"]
    entry = debug["unclassified"][0]
    assert set(entry) == {"parent_id", "error"}
    assert entry["parent_id"] is None
    assert "inv-orphan" in entry["error"]


@pytest.mark.asyncio
async def test_worker_and_read_model_classify_seeded_invoices_identically(db, acad) -> None:
    """The dunning worker and the ``autopay_scheduled`` bucket must agree.

    Six invoices due today (2026-09-10) for distinct families, every parent
    with a card and the academy's connected account ready. Only the three
    with an ``active`` autopay enrollment may be picked up by the worker's
    ``prepare_due_states`` — and exactly those must be the read model's
    ``autopay_scheduled`` bucket.
    """
    from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
        MongoDunningStateRepository,
    )

    await _seed_academy(db, acad)
    await _seed_session(db, academy_id=acad)
    await _seed_connect_ready(db, academy_id=acad)
    due = date(2026, 9, 10)

    seeds: list[tuple[str, str | None, dict[str, Any]]] = [
        ("a1", "active", {}),
        ("a2", "active", {}),
        ("a3", "active", {}),
        ("paused", "paused", {}),
        ("noenr", None, {"enrollment_id": None}),
        ("settled", "active", {"status": "partially_paid", "balance_due_cents": 0}),
    ]
    for tag, autopay_status, overrides in seeds:
        parent_id, student_id, enrollment_id = f"p-{tag}", f"s-{tag}", f"e-{tag}"
        await _seed_family(
            db,
            academy_id=acad,
            parent_id=parent_id,
            student_id=student_id,
            enrollment_id=enrollment_id,
            autopay_status=autopay_status,
        )
        await _seed_card(db, academy_id=acad, parent_id=parent_id)
        invoice_kwargs: dict[str, Any] = {
            "enrollment_id": enrollment_id,
            "status": "open",
            "balance_due_cents": 10_000,
        }
        invoice_kwargs.update(overrides)
        await _seed_invoice(
            db,
            academy_id=acad,
            invoice_id=f"inv-{tag}",
            parent_id=parent_id,
            student_id=student_id,
            due_date=due,
            **invoice_kwargs,
        )

    worker = MongoDunningStateRepository(db, academy_timezone=academy_timezone_lookup(db))
    created = await worker.prepare_due_states(now=NOW, limit=100)
    worker_ids = {
        doc["invoice_id"]
        async for doc in db["dunning_states"].find({"academy_id": acad}, {"invoice_id": 1})
    }

    view = await _read_model(db).build(PERIOD)
    bucket_ids = {
        inv["invoice_id"]
        for family in _bucket(view, "autopay_scheduled")["families"]
        for inv in family["invoices"]
    }

    expected = {"inv-a1", "inv-a2", "inv-a3"}
    assert created == 3
    assert worker_ids == expected
    assert bucket_ids == expected
    assert worker_ids == bucket_ids
