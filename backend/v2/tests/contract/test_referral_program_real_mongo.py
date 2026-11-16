"""Referral programme on a real ``mongod`` (L9 C2).

The real repositories, the 0238 indexes and ``academy_credit_source_unique``.
Proves: switched off nothing happens anywhere; the hold; exactly-once grants
under concurrent replay (and after a crash between the slot and the credit);
the yearly cap under concurrency; self-referral by parent, email or household
phone; an existing family; an unknown code; a family referred before the
switch-on; a second academy isolated; the parent's stable code and count; and
the migration refusing to build over colliding data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.referrals import (
    GetParentReferral,
    ProcessReferrals,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_referrals import (
    MongoReferralCodeRepository,
    MongoReferralRepository,
    MongoReferralSources,
)
from backend.v2.shared.tenancy import current_academy_id, tenant_scope

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
PROGRAM = {
    "enabled": True,
    "referrer_credit_cents": 2_500,
    "referred_credit_cents": 1_000,
    "hold_days": 7,
    "max_rewards_per_referrer_per_year": 10,
    "credit_expiry_days": None,
    "trigger": "first_paid_invoice",
    "effective_from": T0,
}


class _Rotated(MongoReferralRepository):
    """Hands the pending referrals out starting at a different one, so
    concurrent runs race for the yearly slots across different referrals."""

    def __init__(self, db: Any, shift: int) -> None:
        super().__init__(db)
        self._shift = shift

    async def list_pending(self) -> list[Any]:
        rows = await super().list_pending()
        k = self._shift % len(rows) if rows else 0
        return rows[k:] + rows[:k]


def _process(db: Any, now: datetime, *, shift: int = 0) -> ProcessReferrals:
    return ProcessReferrals(
        settings=MongoBillingSettingsRepository(db),
        referrals=_Rotated(db, shift),
        codes=MongoReferralCodeRepository(db),
        sources=MongoReferralSources(db),
        credits=MongoCreditLedgerRepository(db),
        academy_id=current_academy_id,
        clock=lambda: now,
    )


def _parent_view(db: Any) -> GetParentReferral:
    return GetParentReferral(
        settings=MongoBillingSettingsRepository(db),
        referrals=MongoReferralRepository(db),
        codes=MongoReferralCodeRepository(db),
        clock=lambda: T0,
    )


async def _settings(db: Any, **overrides: Any) -> None:
    await db["billing_settings"].update_one(
        {"academy_id": current_academy_id()},
        {"$set": {"referral_program": {**PROGRAM, **overrides}}},
        upsert=True,
    )


async def _user(db: Any, user_id: str, *, email: str, phone: str | None = None) -> None:
    await db["users"].update_one(
        {"user_id": user_id},
        {"$set": {"email": email, "phone": phone, "display_name": user_id.title()}},
        upsert=True,
    )


async def _referred_family(
    db: Any,
    parent_id: str,
    code: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    contact_at: datetime = T0 + timedelta(days=1),
    invoice_at: datetime = T0 + timedelta(days=2),
    paid_at: datetime | None = T0 + timedelta(days=3),
) -> None:
    """A website inquiry with the code, converted to ``parent_id``, whose
    first invoice was paid at ``paid_at`` (``None`` = still open)."""
    academy = current_academy_id()
    email = email or f"{parent_id}@example.test"
    await _user(db, parent_id, email=email, phone=phone)
    await db["crm_contacts"].insert_one(
        {
            "academy_id": academy,
            "contact_id": f"c-{parent_id}",
            "name": parent_id,
            "email": email,
            "phone_digits": phone,
            "source": "website",
            "pipeline_status": "enrolled",
            "converted_parent_id": parent_id,
            "attribution": {"referral_code": code},
            "created_at": contact_at,
            "updated_at": contact_at,
        }
    )
    invoice_id = f"inv-{parent_id}"
    await db["invoices"].insert_one(
        {
            "academy_id": academy,
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "enrollment_id": f"e-{parent_id}",
            "period": "2026-12",
            "status": "open" if paid_at is None else "paid",
            "subtotal_cents": 10_000,
            "total_cents": 10_000,
            "balance_due_cents": 10_000 if paid_at is None else 0,
            "currency": "usd",
            "created_at": invoice_at,
            "updated_at": paid_at or invoice_at,
        }
    )
    if paid_at is not None:
        await db["payment_allocations"].insert_one(
            {
                "academy_id": academy,
                "allocation_id": f"al-{parent_id}",
                "payment_id": f"pay-{parent_id}",
                "invoice_id": invoice_id,
                "amount_cents": 10_000,
                "created_at": paid_at,
            }
        )


async def _referrer(db: Any, parent_id: str = "u-ref", **user: Any) -> str:
    await _user(db, parent_id, email=user.get("email", "ref@example.test"), phone=user.get("phone"))
    view = await _parent_view(db).execute(parent_id)
    assert view.enabled and view.referral_code
    return view.referral_code


async def _referrals(db: Any) -> list[dict[str, Any]]:
    return [
        doc
        async for doc in db["referrals"].find(
            {"academy_id": current_academy_id()}, sort=[("created_at", 1), ("referral_id", 1)]
        )
    ]


async def _credits(db: Any) -> list[dict[str, Any]]:
    return [
        doc
        async for doc in db["account_credit_ledger"].find(
            {"academy_id": current_academy_id(), "source_type": "REFERRAL"}
        )
    ]


DUE = T0 + timedelta(days=3, hours=1) + timedelta(days=7)


async def test_switched_off_nothing_happens_anywhere(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await _settings(real_db, enabled=False)

    result = await _process(real_db, DUE).execute()
    view = await _parent_view(real_db).execute("u-other")

    assert (result.recorded, result.qualified, result.granted) == (0, 0, 0)
    assert view.enabled is False and view.referral_code is None
    assert await real_db["referrals"].count_documents({}) == 0
    assert await real_db["account_credit_ledger"].count_documents({}) == 0
    # Only the code minted while it was on exists; the off view minted none.
    assert await real_db["referral_codes"].count_documents({}) == 1


async def test_the_credit_waits_for_the_hold_then_both_families_are_credited(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code.lower())  # codes compare upper-case

    early = await _process(real_db, DUE - timedelta(hours=2)).execute()
    [row] = await _referrals(real_db)
    assert (early.recorded, early.qualified, early.granted) == (1, 1, 0)
    assert row["status"] == "pending" and row["referrer_parent_id"] == "u-ref"
    assert row["grant_due_at"].replace(tzinfo=UTC) == T0 + timedelta(days=10)
    assert await _credits(real_db) == []

    late = await _process(real_db, DUE).execute()
    assert late.granted == 1
    [row] = await _referrals(real_db)
    assert row["status"] == "granted"
    credits = {c["source_id"]: c for c in await _credits(real_db)}
    rid = row["referral_id"]
    assert set(credits) == {f"{rid}:referrer", f"{rid}:referred"}
    assert credits[f"{rid}:referrer"]["parent_id"] == "u-ref"
    assert credits[f"{rid}:referrer"]["amount_cents"] == 2_500
    assert credits[f"{rid}:referrer"]["type"] == "REFERRAL_CREDIT"
    assert credits[f"{rid}:referrer"]["expires_at"] is None
    assert credits[f"{rid}:referred"]["parent_id"] == "u-new"
    assert credits[f"{rid}:referred"]["amount_cents"] == 1_000
    assert (await _parent_view(real_db).execute("u-ref")).rewards_earned == 1


async def test_terms_are_frozen_when_the_referral_is_recorded(real_db, acad) -> None:
    await _settings(real_db, credit_expiry_days=90)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, paid_at=None)
    await _process(real_db, T0 + timedelta(days=2)).execute()  # recorded, not paid
    await _settings(real_db, referrer_credit_cents=9_900, hold_days=0)  # later change
    await real_db["invoices"].update_one({"invoice_id": "inv-u-new"}, {"$set": {"status": "paid"}})
    await real_db["payment_allocations"].insert_one(
        {
            "academy_id": acad,
            "allocation_id": "al-late",
            "payment_id": "pay-late",
            "invoice_id": "inv-u-new",
            "amount_cents": 10_000,
            "created_at": T0 + timedelta(days=4),
        }
    )
    await _process(real_db, T0 + timedelta(days=5)).execute()
    assert await _credits(real_db) == []  # still the 7-day hold it was recorded with
    await _process(real_db, T0 + timedelta(days=11, hours=1)).execute()
    referrer = [c for c in await _credits(real_db) if c["source_id"].endswith(":referrer")]
    assert referrer[0]["amount_cents"] == 2_500
    assert referrer[0]["expires_at"].replace(tzinfo=UTC) == T0 + timedelta(days=101, hours=1)


async def test_concurrent_replays_grant_exactly_once(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)

    await asyncio.gather(*(_process(real_db, DUE, shift=n).execute() for n in range(8)))
    await asyncio.gather(*(_process(real_db, DUE).execute() for _ in range(4)))

    rows = await _referrals(real_db)
    assert [r["status"] for r in rows] == ["granted"]
    credits = await _credits(real_db)
    assert sorted(c["source_id"].rsplit(":", 1)[1] for c in credits) == ["referred", "referrer"]


async def test_a_crash_after_the_slot_resumes_without_a_second_credit(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await _process(real_db, DUE - timedelta(days=1)).execute()  # qualified, not due
    [row] = await _referrals(real_db)
    # The slot was claimed and the referrer credit written, then the run died.
    await real_db["referrals"].update_one(
        {"referral_id": row["referral_id"]},
        {"$set": {"reward_key": "u-ref:2026:1", "reward_year": 2026}},
    )
    await real_db["account_credit_ledger"].insert_one(
        {
            "academy_id": acad,
            "credit_id": "cr-before-crash",
            "parent_id": "u-ref",
            "type": "REFERRAL_CREDIT",
            "status": "APPROVED",
            "amount_cents": 2_500,
            "remaining_amount_cents": 2_500,
            "currency": "usd",
            "reason": "x",
            "source_type": "REFERRAL",
            "source_id": f"{row['referral_id']}:referrer",
            "created_at": DUE,
            "updated_at": DUE,
        }
    )
    await asyncio.gather(*(_process(real_db, DUE).execute() for _ in range(3)))
    [row] = await _referrals(real_db)
    assert row["status"] == "granted" and row["referrer_credit_id"] == "cr-before-crash"
    assert len(await _credits(real_db)) == 2


async def test_the_yearly_cap_holds_under_concurrency(real_db, acad) -> None:
    await _settings(real_db, max_rewards_per_referrer_per_year=2)
    code = await _referrer(real_db)
    for n in range(5):
        await _referred_family(real_db, f"u-new{n}", code)
    await _process(real_db, DUE - timedelta(days=1)).execute()  # record + qualify all

    await asyncio.gather(*(_process(real_db, DUE, shift=n).execute() for n in range(5)))

    statuses = sorted((r["status"], r.get("reason")) for r in await _referrals(real_db))
    assert statuses == [("granted", None)] * 2 + [("ineligible", "yearly_cap_reached")] * 3
    referrer_credits = [c for c in await _credits(real_db) if c["parent_id"] == "u-ref"]
    assert len(referrer_credits) == 2
    assert len(await _credits(real_db)) == 4  # capped referrals credit neither family


@pytest.mark.parametrize("how", ["same_parent", "same_email", "same_phone"])
async def test_a_self_referral_never_earns(real_db, acad, how: str) -> None:
    await _settings(real_db)
    code = await _referrer(real_db, email="ref@example.test", phone="(555) 010-0100")
    if how == "same_parent":
        await real_db["crm_contacts"].insert_one(
            {
                "academy_id": acad,
                "contact_id": "c-self",
                "email": "other@example.test",
                "converted_parent_id": "u-ref",
                "attribution": {"referral_code": code},
                "created_at": T0 + timedelta(days=1),
            }
        )
    elif how == "same_email":
        await _referred_family(real_db, "u-new", code, email="REF@example.test")
    else:
        await _referred_family(real_db, "u-new", code, phone="5550100100")

    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["reason"]) == ("ineligible", "self_referral")
    assert await _credits(real_db) == []


async def test_an_existing_family_and_an_unknown_code_never_earn(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    # Invoiced before the inquiry with the code: already a family.
    await _referred_family(
        real_db,
        "u-old",
        code,
        contact_at=T0 + timedelta(days=2),
        invoice_at=T0 + timedelta(days=1),
    )
    await _referred_family(real_db, "u-unknown", "NOSUCHCODE")
    await _process(real_db, DUE).execute()
    reasons = {r["referred_parent_id"]: r["reason"] for r in await _referrals(real_db)}
    assert reasons == {"u-old": "existing_family", "u-unknown": "unknown_code"}
    assert await _credits(real_db) == []


async def test_a_family_referred_before_the_switch_on_does_not_count(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-early", code, contact_at=T0 - timedelta(hours=1))
    await _process(real_db, DUE).execute()
    assert await _referrals(real_db) == []


async def test_a_second_academy_is_isolated(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    with tenant_scope("other-academy"):
        await _settings(real_db)
        await _referred_family(real_db, "u-elsewhere", code)  # A's code at B
        await _process(real_db, DUE).execute()
        rows_b = await _referrals(real_db)
        assert [(r["status"], r["reason"]) for r in rows_b] == [("ineligible", "unknown_code")]
        assert await _credits(real_db) == []
    assert await _process(real_db, DUE).execute() is not None
    assert await _referrals(real_db) == []  # A never sees B's family
    assert await _credits(real_db) == []


async def test_the_parent_code_is_stable_and_unique(real_db, acad) -> None:
    await _settings(real_db)
    views = await asyncio.gather(*(_parent_view(real_db).execute("u-ref") for _ in range(5)))
    assert len({v.referral_code for v in views}) == 1
    other = await _parent_view(real_db).execute("u-two")
    assert other.referral_code != views[0].referral_code
    assert await real_db["referral_codes"].count_documents({}) == 2


async def test_the_migration_names_colliding_data_instead_of_building(real_db) -> None:
    import importlib

    migration = importlib.import_module("backend.v2.migrations.0238_referral_program")
    collection = real_db["referral_codes"]
    await collection.drop_index("referral_code_unique")
    try:
        await collection.insert_many(
            [
                {"academy_id": "a", "parent_id": "p1", "referral_code": "SAME"},
                {"academy_id": "a", "parent_id": "p2", "referral_code": "SAME"},
            ]
        )
        with pytest.raises(RuntimeError, match=r"referral_code_unique.*SAME"):
            await migration.up(real_db)
    finally:
        await collection.delete_many({})
        await migration.up(real_db)
