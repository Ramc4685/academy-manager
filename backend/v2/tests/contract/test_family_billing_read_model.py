# backend/v2/tests/contract/test_family_billing_read_model.py
"""mongomock contract tests for ``MongoFamilyBillingReadModel`` (spec §3, §8)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.interfaces.admin.families_views import AdminFamilyBillingView
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _dt(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _read_model(db) -> MongoFamilyBillingReadModel:
    return MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=MongoBillingAuditLogRepository(db),
        clock=lambda: NOW,
    )


async def _seed_family(db, acad: str, *, parent_id: str = "p-1") -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await db["users"].insert_one(
        {
            "user_id": parent_id,
            "academy_id": acad,
            "display_name": "Sahaya Vinodh",
            "email": "s@example.com",
            "phone": "555-0100",
            "roles": ["parent"],
        }
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "s-arjun",
                "parent_id": parent_id,
                "full_name": "Arjun",
                "status": "active",
            },
            {
                "academy_id": acad,
                "student_id": "s-hannah",
                "parent_id": parent_id,
                "full_name": "Hannah",
                "status": "active",
            },
        ]
    )
    await db["sessions"].insert_many(
        [
            {
                "academy_id": acad,
                "session_id": "sess-sat",
                "title": "Sat 9:00 Beginners",
                "days_of_week": ["saturday"],
                "start_time": "09:00",
                "monthly_price_cents": 6000,
            },
            {
                "academy_id": acad,
                "session_id": "sess-wed",
                "title": "Wed 6:15 Intermediate",
                "days_of_week": ["wednesday"],
                "start_time": "18:15",
                "monthly_price_cents": 7000,
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "e-arjun",
                "student_id": "s-arjun",
                "session_id": "sess-sat",
                "status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-hannah",
                "student_id": "s-hannah",
                "session_id": "sess-wed",
                "status": "paused",
            },
        ]
    )
    await db["student_billing_enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "e-arjun",
                "student_id": "s-arjun",
                "parent_id": parent_id,
                "status": "active",
                "autopay_enrollment_status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-hannah",
                "student_id": "s-hannah",
                "parent_id": parent_id,
                "status": "active",
                "autopay_enrollment_status": "paused",
                "override_price_cents": 6500,
            },
        ]
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "e-hannah",
            "resume_on": _dt(date(2026, 10, 1)),
            "created_at": NOW,
        }
    )
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": parent_id,
            "stripe_customer_id": "cus_1",
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
        }
    )
    await db["academy_connected_accounts"].insert_one(
        {
            "academy_id": acad,
            "stripe_account_id": "acct_1",
            "status": "active",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "capabilities": {},
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


async def _seed_invoices(db, acad: str, parent_id: str = "p-1") -> None:
    await db["invoices"].insert_many(
        [
            {
                "academy_id": acad,
                "invoice_id": "inv-sep-arjun",
                "invoice_number": "INV-3",
                "parent_id": parent_id,
                "student_id": "s-arjun",
                "enrollment_id": "e-arjun",
                "period": "2026-09",
                "status": "open",
                "total_cents": 6000,
                "balance_due_cents": 6000,
                "due_date": _dt(date(2026, 9, 8)),
                "delivery_status": "sent",
                "last_sent_at": datetime(2026, 9, 1, 6, 5, tzinfo=UTC),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-sep-hannah",
                "invoice_number": "INV-4",
                "parent_id": parent_id,
                "student_id": "s-hannah",
                "enrollment_id": "e-hannah",
                "period": "2026-09",
                "status": "void",
                "total_cents": 7000,
                "balance_due_cents": 0,
                "due_date": _dt(date(2026, 9, 8)),
                "void_reason": "enrollment paused",
                "voided_at": datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-aug-arjun",
                "invoice_number": "INV-1",
                "parent_id": parent_id,
                "student_id": "s-arjun",
                "enrollment_id": "e-arjun",
                "period": "2026-08",
                "status": "paid",
                "total_cents": 6000,
                "balance_due_cents": 0,
                "due_date": _dt(date(2026, 8, 8)),
                "paid_at": datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
                "delivery_status": "sent",
                "last_sent_at": datetime(2026, 8, 1, 6, 5, tzinfo=UTC),
                "created_at": datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
            },
        ]
    )
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-aug",
            "parent_id": parent_id,
            "amount_cents": 6000,
            "payment_method": "card",
            "stripe_payment_intent_id": "pi_aug",
            "paid_at": datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
            "created_at": NOW,
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-aug",
            "invoice_id": "inv-aug-arjun",
            "amount_cents": 6000,
        }
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": acad,
            "attempt_id": "at-1",
            "invoice_id": "inv-sep-arjun",
            "parent_id": parent_id,
            "amount_cents": 6000,
            "status": "declined",
            "failure_message": "Your card was declined.",
            "created_at": datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
        }
    )
    await db["dunning_states"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-sep-arjun",
            "status": "active",
            "attempt_count": 1,
            "last_notification_at": datetime(2026, 9, 8, 14, 1, tzinfo=UTC),
            "next_attempt_at": datetime(2026, 9, 11, 14, 0, tzinfo=UTC),
        }
    )
    await db["billing_audit_log"].insert_one(
        {
            "academy_id": acad,
            "audit_id": "a-1",
            "action": "autopay_paused",
            "actor_id": "admin-1",
            "parent_id": parent_id,
            "at": datetime(2026, 9, 4, 20, 1, tzinfo=UTC),
            "reason": "parent asked",
        }
    )
    await db["enrollment_events"].insert_one(
        {
            "academy_id": acad,
            "event_id": "ev-1",
            "event_type": "paused",
            "enrollment_id": "e-hannah",
            "student_id": "s-hannah",
            "occurred_at": datetime(2026, 9, 4, 19, 59, tzinfo=UTC),
            "actor_id": "admin-1",
            "reason": "travel",
            "effective_at": datetime(2026, 10, 1, 5, 0, tzinfo=UTC),
        }
    )


@pytest.mark.asyncio
async def test_full_family_view(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_invoices(db, acad)

    view = await _read_model(db).build("p-1")

    assert view is not None
    AdminFamilyBillingView.model_validate(view)
    assert view["parent"] == {
        "parent_id": "p-1",
        "name": "Sahaya Vinodh",
        "email": "s@example.com",
        "phone": "555-0100",
    }
    header = view["header"]
    assert header["balance_cents"] == 6000
    assert header["open_invoice_count"] == 1
    assert header["autopay"]["state"] == "partial"
    assert header["autopay"]["card_last4"] == "4242"
    assert header["autopay"]["next_charge_on"] == "2026-09-08"
    assert header["autopay"]["next_charge_invoice_id"] == "inv-sep-arjun"
    assert header["last_payment"]["amount_cents"] == 6000
    assert header["last_payment"]["invoice_ids"] == ["inv-aug-arjun"]
    assert header["enrollment_counts"] == {"active": 1, "paused": 1, "cancelled": 0}

    students = {s["name"]: s for s in view["students"]}
    hannah = students["Hannah"]["enrollments"][0]
    assert hannah["session_title"] == "Wed 6:15 Intermediate"
    assert hannah["schedule"] == "Wed 18:15"
    assert hannah["monthly_price_cents"] == 7000
    assert hannah["override_price_cents"] == 6500
    assert hannah["resume_on"] == "2026-10-01"
    assert hannah["autopay_status"] == "paused"

    rows = {i["invoice_id"]: i for i in view["invoices"]}
    assert list(rows) == [
        "inv-sep-arjun",
        "inv-sep-hannah",
        "inv-aug-arjun",
    ]  # period desc, then created desc
    assert rows["inv-aug-arjun"]["paid_cents"] == 6000
    assert rows["inv-aug-arjun"]["allocations"][0]["stripe_payment_intent_id"] == "pi_aug"
    assert rows["inv-aug-arjun"]["actions"] == ["refund"]
    assert rows["inv-sep-hannah"]["actions"] == []
    assert rows["inv-sep-arjun"]["chargeable"] is True

    codes = [e["code"] for e in view["timeline"]]
    assert codes[:3] == ["failure_notice_emailed", "charge_failed", "audit:autopay_paused"]
    assert "enrollment:paused" in codes
    assert "payment_received" in codes
    assert view["actions"] == ["autopay_on", "autopay_off", "send_invoice", "record_payment"]
    assert view["warnings"] == []


@pytest.mark.asyncio
async def test_unknown_or_foreign_parent_is_none(db, acad) -> None:
    await _seed_family(db, "other-acad")
    assert await _read_model(db).build("p-1") is None
    assert await _read_model(db).build("nobody") is None


@pytest.mark.asyncio
async def test_parent_with_no_students_or_invoices(db, acad) -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await db["users"].insert_one(
        {
            "user_id": "p-empty",
            "academy_id": acad,
            "display_name": "New Parent",
            "roles": ["parent"],
        }
    )

    view = await _read_model(db).build("p-empty")

    assert view is not None
    assert view["students"] == []
    assert view["invoices"] == []
    assert view["timeline"] == []
    assert view["header"]["autopay"]["state"] == "needs_consent"
    assert view["header"]["registration"]["state"] == "not_invited"
    assert view["actions"] == ["send_invite"]


@pytest.mark.asyncio
async def test_foreign_tenant_invoices_for_same_parent_id_are_invisible(db, acad) -> None:
    await _seed_family(db, acad)
    await db["invoices"].insert_one(
        {
            "academy_id": "other-acad",
            "invoice_id": "inv-foreign",
            "parent_id": "p-1",
            "period": "2026-09",
            "status": "open",
            "total_cents": 99999,
            "balance_due_cents": 99999,
            "due_date": _dt(date(2026, 9, 8)),
        }
    )

    view = await _read_model(db).build("p-1")

    assert view is not None
    assert [i["invoice_id"] for i in view["invoices"]] == []


@pytest.mark.asyncio
async def test_secondary_source_failure_becomes_a_warning(db, acad, monkeypatch) -> None:
    await _seed_family(db, acad)
    await _seed_invoices(db, acad)
    model = _read_model(db)

    async def boom(*_a, **_k):
        raise RuntimeError("attempts down")

    monkeypatch.setattr(model, "_attempts", boom)

    view = await model.build("p-1")

    assert view is not None
    assert view["warnings"] == ["attempts_unavailable"]
    assert "charge_failed" not in [e["code"] for e in view["timeline"]]
