"""Referral programme on a real ``mongod`` (L9 C2).

The real repositories, the 0238 indexes and ``academy_credit_source_unique``.
Proves: switched off nothing happens anywhere; the hold; exactly-once grants
under concurrent replay (and after a crash between the slot and the credit);
the yearly cap under concurrency; self-referral by parent, email or household
phone; an existing family; an unknown code; a family referred before the
switch-on; a second academy isolated; the parent's stable code and count; and
the migration refusing to build over colliding data; an inquiry-only code
held for review and never auto-granted; the registration code beating an
inquiry's; owner approval granting exactly once.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.referrals import (
    ApproveReferral,
    GetParentReferral,
    ProcessReferrals,
    ReferralNotReviewable,
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
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
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


def _sources(db: Any) -> MongoReferralSources:
    return MongoReferralSources(db, users=MongoUserRepository(db))


def _process(
    db: Any,
    now: datetime,
    *,
    shift: int = 0,
    zone: str = "UTC",
    sources: MongoReferralSources | None = None,
) -> ProcessReferrals:
    async def timezone_for(_academy_id: str) -> str:
        return zone

    return ProcessReferrals(
        settings=MongoBillingSettingsRepository(db),
        referrals=_Rotated(db, shift),
        codes=MongoReferralCodeRepository(db),
        sources=sources or _sources(db),
        credits=MongoCreditLedgerRepository(db),
        academy_id=current_academy_id,
        timezone_for=timezone_for,
        clock=lambda: now,
    )


async def _base_url(academy_id: str) -> str:
    return f"https://{academy_id}.courtmastr.test"


def _parent_view(db: Any) -> GetParentReferral:
    return GetParentReferral(
        settings=MongoBillingSettingsRepository(db),
        referrals=MongoReferralRepository(db),
        codes=MongoReferralCodeRepository(db),
        academy_id=current_academy_id,
        base_url_for=_base_url,
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
    via: str = "application",
    contact_code: str | None = None,
) -> None:
    """A family that arrived with the code on its approved registration
    (``via="application"``, the authenticated source) or only on a converted
    website inquiry (``via="contact"``), whose first invoice was paid at
    ``paid_at`` (``None`` = still open). ``contact_code`` adds an inquiry
    carrying that code as well."""
    academy = current_academy_id()
    email = email or f"{parent_id}@example.test"
    await _user(db, parent_id, email=email, phone=phone)
    if via == "application":
        await db["onboarding_applications"].insert_one(
            {
                "academy_id": academy,
                "application_id": f"app-{parent_id}",
                "parent_user_id": parent_id,
                "parent_email": email,
                "parent_profile": {"email": email, "phone": phone, "referral_code": code},
                "status": "APPROVED",
                "created_at": contact_at,
                "updated_at": contact_at,
            }
        )
    inquiry_code = code if via == "contact" else contact_code
    if inquiry_code is not None:
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
                "attribution": {"referral_code": inquiry_code},
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
        await real_db["onboarding_applications"].insert_one(
            {
                "academy_id": acad,
                "application_id": "app-self",
                "parent_user_id": "u-ref",
                "parent_email": "other@example.test",
                "parent_profile": {"referral_code": code},
                "status": "APPROVED",
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


def _approve(db: Any, now: datetime, *, shift: int = 0) -> ApproveReferral:
    return ApproveReferral(
        settings=MongoBillingSettingsRepository(db),
        referrals=MongoReferralRepository(db),
        process=_process(db, now, shift=shift),
        clock=lambda: now,
    )


async def test_an_inquiry_only_code_waits_for_review_and_never_auto_grants(real_db, acad) -> None:
    """The public inquiry form is unauthenticated: anyone knowing a family's
    email could put their own code on it. It never grants by itself."""
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, via="contact")
    for day in range(3):
        await _process(real_db, DUE + timedelta(days=day)).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["source"], row["qualified_at"]) == ("needs_review", "contact", None)
    assert await _credits(real_db) == []
    assert (await _parent_view(real_db).execute("u-ref")).rewards_earned == 0


async def test_the_registration_code_beats_a_different_inquiry_code(real_db, acad) -> None:
    await _settings(real_db)
    real = await _referrer(real_db, "u-real", email="real@example.test")
    attacker = await _referrer(real_db, "u-attacker", email="attacker@example.test")
    # Same run: both sources present.
    await _referred_family(real_db, "u-new", real, contact_code=attacker)
    # Across runs: the inquiry was recorded first, the registration came later.
    await _referred_family(real_db, "u-late", real, via="contact", contact_code=None)
    await real_db["crm_contacts"].update_one(
        {"contact_id": "c-u-late"}, {"$set": {"attribution.referral_code": attacker}}
    )
    await _process(real_db, T0 + timedelta(days=2)).execute()
    late = await real_db["referrals"].find_one({"referred_parent_id": "u-late"})
    assert (late["status"], late["referrer_parent_id"]) == ("needs_review", "u-attacker")
    await real_db["onboarding_applications"].insert_one(
        {
            "academy_id": acad,
            "application_id": "app-u-late",
            "parent_user_id": "u-late",
            "parent_email": "u-late@example.test",
            "parent_profile": {"referral_code": real},
            "status": "APPROVED",
            "created_at": T0 + timedelta(days=1),
        }
    )

    await _process(real_db, DUE).execute()
    rows = {r["referred_parent_id"]: r for r in await _referrals(real_db)}
    for parent in ("u-new", "u-late"):
        assert (rows[parent]["source"], rows[parent]["status"]) == ("application", "granted")
        assert rows[parent]["referrer_parent_id"] == "u-real"
    owners = sorted(
        c["parent_id"] for c in await _credits(real_db) if c["source_id"].endswith(":referrer")
    )
    assert owners == ["u-real", "u-real"]


async def test_owner_approval_grants_an_inquiry_referral_exactly_once(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, via="contact")
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)

    outcomes = await asyncio.gather(
        *(
            _approve(real_db, DUE, shift=n).execute(row["referral_id"], actor_id="u-owner")
            for n in range(6)
        ),
        *(_process(real_db, DUE, shift=n).execute() for n in range(4)),
        return_exceptions=True,
    )
    approvals = outcomes[:6]
    assert sum(not isinstance(o, BaseException) for o in approvals) == 1
    assert all(
        isinstance(o, ReferralNotReviewable) for o in approvals if isinstance(o, BaseException)
    )
    await _process(real_db, DUE + timedelta(days=1)).execute()

    [row] = await _referrals(real_db)
    assert (row["status"], row["reviewed_by"]) == ("granted", "u-owner")
    credits = await _credits(real_db)
    assert sorted(c["source_id"].rsplit(":", 1)[1] for c in credits) == ["referred", "referrer"]
    with pytest.raises(ReferralNotReviewable):
        await _approve(real_db, DUE).execute(row["referral_id"], actor_id="u-owner")


async def test_approval_is_refused_while_the_programme_is_off(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, via="contact")
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    await _settings(real_db, enabled=False)
    with pytest.raises(ReferralNotReviewable):
        await _approve(real_db, DUE).execute(row["referral_id"], actor_id="u-owner")
    assert (await _referrals(real_db))[0]["status"] == "needs_review"


# Fix round (risk review): the money must have stayed with the academy, the
# credit must land on the id the family is billed under, and the owner must
# see how a family was attributed.


async def _invoice(db: Any, parent_id: str, invoice_id: str, **fields: Any) -> None:
    at = fields.pop("created_at", T0 + timedelta(days=5))
    await db["invoices"].insert_one(
        {
            "academy_id": current_academy_id(),
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "enrollment_id": f"e-{parent_id}",
            "status": "paid",
            "total_cents": 10_000,
            "balance_due_cents": 0,
            "currency": "usd",
            "created_at": at,
            "updated_at": at,
            **fields,
        }
    )


async def test_a_fully_refunded_first_invoice_never_qualifies(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    # A full refund leaves the invoice "paid" with refunded_cents == total.
    await real_db["invoices"].update_one(
        {"invoice_id": "inv-u-new"}, {"$set": {"refunded_cents": 10_000}}
    )
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["qualified_at"]) == ("pending", None)
    assert await _credits(real_db) == []


async def test_a_zero_dollar_paid_invoice_never_qualifies(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await real_db["invoices"].update_one({"invoice_id": "inv-u-new"}, {"$set": {"total_cents": 0}})
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert row["qualified_at"] is None and await _credits(real_db) == []


async def test_a_payment_reversed_in_the_hold_clears_it_and_a_later_payment_requalifies(
    real_db, acad
) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await _process(real_db, DUE - timedelta(days=6)).execute()  # qualifies at once
    [row] = await _referrals(real_db)
    assert row["qualified_invoice_id"] == "inv-u-new"
    # An ACH return (R01) reopens the invoice before the hold ends.
    await real_db["invoices"].update_one(
        {"invoice_id": "inv-u-new"}, {"$set": {"status": "open", "balance_due_cents": 10_000}}
    )
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["qualified_at"], row["qualified_invoice_id"]) == (
        "pending",
        None,
        None,
    )
    assert await _credits(real_db) == []

    paid = T0 + timedelta(days=20)
    await _invoice(real_db, "u-new", "inv-u-new-2", created_at=paid)
    await _process(real_db, paid + timedelta(days=8)).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["qualified_invoice_id"]) == ("granted", "inv-u-new-2")
    assert len(await _credits(real_db)) == 2


@pytest.mark.parametrize(("outcome", "grants"), [(None, False), ("lost", False), ("won", True)])
async def test_a_dispute_on_the_payment_blocks_the_grant(
    real_db, acad, outcome: str | None, grants: bool
) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await _process(real_db, DUE - timedelta(days=6)).execute()
    await real_db["payment_disputes"].insert_one(
        {
            "academy_id": acad,
            "dispute_id": "dp_1",
            "payment_id": "pay-u-new",
            "status": outcome or "needs_response",
            "outcome": outcome,
            "is_open": outcome is None,
            "opened_at": T0 + timedelta(days=4),
            "updated_at": T0 + timedelta(days=4),
        }
    )
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert (row["status"] == "granted") is grants
    assert len(await _credits(real_db)) == (2 if grants else 0)


async def test_an_old_open_invoice_does_not_block_a_later_paid_one(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, paid_at=None)
    await _invoice(real_db, "u-new", "inv-u-new-2")
    await _process(real_db, DUE + timedelta(days=30)).execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["qualified_invoice_id"]) == ("granted", "inv-u-new-2")


async def test_credits_land_on_the_ids_the_families_are_billed_under(real_db, acad) -> None:
    await _settings(real_db)
    await real_db["users"].update_one(
        {"user_id": "u-ref"}, {"$set": {"firebase_uid": "fb-ref"}}, upsert=True
    )
    code = await _referrer(real_db)
    # The referrer's monthly invoices are keyed by enrollment.parent_id = firebase uid.
    await real_db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "e-ref",
            "student_id": "s-ref",
            "session_id": "sess-1",
            "parent_id": "fb-ref",
            "status": "active",
            "created_at": T0,
        }
    )
    await _referred_family(real_db, "u-new", code)
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert row["status"] == "granted"
    owners = {c["source_id"].rsplit(":", 1)[1]: c["parent_id"] for c in await _credits(real_db)}
    assert owners == {"referrer": "fb-ref", "referred": "u-new"}
    ledger = MongoCreditLedgerRepository(real_db)
    applied = await ledger.apply_available_credits(
        parent_id="fb-ref", invoice_id="inv-ref-next", amount_due_cents=10_000
    )
    assert applied == 2_500


async def test_the_reward_year_is_the_academy_local_year(real_db, acad) -> None:
    """Paid 03:00 UTC on 1 January is still 31 December in Chicago."""
    await _settings(real_db)
    code = await _referrer(real_db)
    paid = datetime(2027, 1, 1, 3, 0, tzinfo=UTC)
    await _referred_family(real_db, "u-new", code, invoice_at=paid, paid_at=paid)
    await _process(real_db, paid + timedelta(days=8), zone="America/Chicago").execute()
    [row] = await _referrals(real_db)
    assert (row["status"], row["reward_year"]) == ("granted", 2026)


async def test_the_row_records_the_source_and_competing_codes(real_db, acad) -> None:
    await _settings(real_db)
    real = await _referrer(real_db, "u-real", email="real@example.test")
    other = await _referrer(real_db, "u-other", email="other@example.test")
    await _referred_family(real_db, "u-new", real, contact_code=other)
    await _process(real_db, T0 + timedelta(days=2)).execute()
    [row] = await _referrals(real_db)
    assert (row["source"], row["referral_code"], row["competing_codes"]) == (
        "application",
        real,
        [other],
    )


class _CountingSources(MongoReferralSources):
    def __init__(self, db: Any) -> None:
        super().__init__(db, users=MongoUserRepository(db))
        self.lookups = 0

    async def household(self, parent_id: str) -> Any:
        self.lookups += 1
        return await super().household(parent_id)


async def test_a_settled_family_costs_no_lookups_on_later_runs(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)
    await _process(real_db, DUE).execute()
    assert (await _referrals(real_db))[0]["status"] == "granted"
    counting = _CountingSources(real_db)
    await _process(real_db, DUE + timedelta(days=1), sources=counting).execute()
    assert counting.lookups == 0


async def test_the_share_link_is_on_the_academy_host(real_db, acad) -> None:
    await _settings(real_db)
    view = await _parent_view(real_db).execute("u-ref")
    assert view.share_url == f"https://test-academy.courtmastr.test/?ref={view.referral_code}"


# The risk reviewer's concurrency repros, kept as regression tests.


async def test_approve_racing_the_sweep_grants_once(real_db, acad) -> None:
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code, via="contact")
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert row["status"] == "needs_review"
    await asyncio.gather(
        _approve(real_db, DUE).execute(row["referral_id"], actor_id="owner"),
        *[_process(real_db, DUE, shift=i).execute() for i in range(5)],
    )
    assert len(await _credits(real_db)) == 2


async def test_the_cap_holds_with_six_qualified_families_racing(real_db, acad) -> None:
    await _settings(real_db, max_rewards_per_referrer_per_year=2)
    code = await _referrer(real_db)
    for i in range(6):
        await _referred_family(real_db, f"u-new{i}", code)
    await _process(real_db, DUE - timedelta(days=6)).execute()  # record + qualify
    await asyncio.gather(*[_process(real_db, DUE, shift=i).execute() for i in range(6)])
    rows = await _referrals(real_db)
    assert sum(r["status"] == "granted" for r in rows) == 2
    assert len([c for c in await _credits(real_db) if c["parent_id"] == "u-ref"]) == 2


async def test_a_dispute_stored_under_the_legacy_payment_id_still_blocks(real_db, acad) -> None:
    """``RecordPaymentDispute`` keys the dispute on the legacy ``payments`` row
    when one exists, while the allocation carries the ledger payment id: the
    two only meet through the PaymentIntent."""
    await _settings(real_db)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-new", code)  # allocation payment_id = pay-u-new
    await real_db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-u-new",
            "parent_id": "u-new",
            "stripe_payment_intent_id": "pi_1",
            "amount_cents": 10_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "created_at": T0,
            "updated_at": T0,
        }
    )
    await _process(real_db, DUE - timedelta(days=6)).execute()
    await real_db["payment_disputes"].insert_one(
        {
            "academy_id": acad,
            "dispute_id": "dp_1",
            "payment_id": "legacy-pay-1",
            "stripe_payment_intent_id": "pi_1",
            "status": "needs_response",
            "outcome": None,
            "is_open": True,
            "opened_at": T0 + timedelta(days=4),
            "updated_at": T0 + timedelta(days=4),
        }
    )
    await _process(real_db, DUE).execute()
    [row] = await _referrals(real_db)
    assert row["status"] == "pending" and row["qualified_at"] is None
    assert await _credits(real_db) == []


async def test_a_refund_after_the_slot_is_claimed_still_finishes_the_grant(real_db, acad) -> None:
    """The run died after claiming the slot and writing the referrer credit,
    then the invoice was refunded. Freeing the slot would let a second
    referral take it while the first credit stays spendable."""
    await _settings(real_db, max_rewards_per_referrer_per_year=1)
    code = await _referrer(real_db)
    await _referred_family(real_db, "u-a", code)
    await _process(real_db, DUE - timedelta(days=6)).execute()
    [a] = await _referrals(real_db)
    await real_db["referrals"].update_one(
        {"referral_id": a["referral_id"]},
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
            "source_id": f"{a['referral_id']}:referrer",
            "created_at": DUE,
            "updated_at": DUE,
        }
    )
    await real_db["invoices"].update_one(
        {"invoice_id": "inv-u-a"}, {"$set": {"refunded_cents": 10_000}}
    )
    await _referred_family(real_db, "u-b", code)
    await _process(real_db, DUE).execute()
    rows = {r["referred_parent_id"]: r for r in await _referrals(real_db)}
    assert rows["u-a"]["reward_key"] == "u-ref:2026:1"
    assert rows["u-a"]["status"] == "granted"
    assert rows["u-a"]["referrer_credit_id"] == "cr-before-crash"
    assert (rows["u-b"]["status"], rows["u-b"]["reason"]) == ("ineligible", "yearly_cap_reached")
    assert len([c for c in await _credits(real_db) if c["parent_id"] == "u-ref"]) == 1
