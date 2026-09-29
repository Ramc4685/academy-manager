"""Pricing page against Mongo (Settings overhaul Phase 3 PR 11b).

The hard rule of this PR: ZERO change to any charged amount. A class-to-plan
link is a label. These tests pin that:

* the checkout quote and the monthly invoice charge a LINKED class its own
  monthly fee, including after the plan's price moves away from it;
* linking never writes to ``sessions`` (the class doc is byte-identical);
* the link rules: exactly one matching plan links, zero or two stay custom,
  a mismatched price is refused, a decided class is never re-linked;
* ``plan_type`` reads as "monthly" for a plan stored before the field;
* every read and write is tenant-scoped.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    GetPricingOverview,
    LinkMatchingClasses,
    SetClassPlanLink,
    SetClassPlanLinkCommand,
)
from backend.v2.contexts.billing.application.use_cases.quote_enrollment import (
    QuoteEnrollment,
    QuoteEnrollmentCommand,
)
from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    UpdateSessionType,
    UpdateSessionTypeCommand,
)
from backend.v2.contexts.billing.domain.errors import PlanPriceMismatch, PricingClassNotFound
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_pricing_read_model import (
    MongoClassPlanLinkRepository,
    MongoPricingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.shared.tenancy.context import _current as _tenant

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return NOW


async def _plan(db, acad: str, plan_id: str, price_cents: int, **extra) -> None:
    doc = {
        "academy_id": acad,
        "session_type_id": plan_id,
        "name": plan_id.title(),
        "price_cents": price_cents,
        "billing_period": "monthly",
        "is_active": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    doc.update(extra)
    await db["session_types"].insert_one(doc)


async def _class(db, acad: str, session_id: str, **fee) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": session_id,
            "title": f"Class {session_id}",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-05-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon", "Fri"],
            "start_time": "18:00",
            "end_time": "19:00",
            "capacity": 8,
            "status": "active",
            **fee,
        }
    )


async def _enroll(db, acad: str, enrollment_id: str, session_id: str, **extra) -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "student_id": f"student-{enrollment_id}",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            **extra,
        }
    )


def _use_cases(db):
    session_types = MongoSessionTypeRepository(db)
    read_model = MongoPricingReadModel(db, clock=_clock)
    links = MongoClassPlanLinkRepository(db)
    audit = RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db))
    return (
        GetPricingOverview(session_types=session_types, read_model=read_model, links=links),
        SetClassPlanLink(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            clock=_clock,
        ),
        LinkMatchingClasses(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            clock=_clock,
        ),
    )


def _link_cmd(acad: str, session_id: str, plan_id: str | None) -> SetClassPlanLinkCommand:
    return SetClassPlanLinkCommand(
        academy_id=acad, session_id=session_id, plan_id=plan_id, actor_id="owner-1"
    )


# ------------------------------------------------------------- charges unchanged


@pytest.mark.asyncio
async def test_linked_class_is_charged_its_own_fee_even_after_the_plan_price_moves(
    db, acad
) -> None:
    await _plan(db, acad, "group", 10_000)
    await _class(db, acad, "sess-1", monthly_price_cents=10_000)
    await db["students"].insert_one(
        {"academy_id": acad, "student_id": "student-e1", "parent_id": "parent-1"}
    )
    await _enroll(db, acad, "e1", "sess-1")
    _, set_link, _ = _use_cases(db)
    session_before = await db["sessions"].find_one({"session_id": "sess-1"}, {"_id": 0})

    await set_link.execute(_link_cmd(acad, "sess-1", "group"))
    # The owner then raises the plan price. Billing must not follow it.
    await UpdateSessionType(session_types=MongoSessionTypeRepository(db)).execute(
        UpdateSessionTypeCommand(session_type_id="group", price_cents=13_000)
    )

    # Linking wrote nothing on the class.
    assert await db["sessions"].find_one({"session_id": "sess-1"}, {"_id": 0}) == session_before

    payments = MongoPaymentRepository(
        db, clock=_clock, ledger_repo=MongoBillingLedgerRepository(db, clock=_clock)
    )
    result = await payments.generate_monthly_payments("2026-06")
    assert result.created == 1
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "enrollment_id": "e1", "period": "2026-06"}
    )
    assert invoice is not None
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["total_cents"] == 10_000

    quote = await QuoteEnrollment(
        sessions=payments, snapshots=payments, occurrences=payments, clock=_clock
    ).execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            calculated_by="parent-1",
        )
    )
    assert quote.monthly_price_cents == 10_000

    # And the page no longer claims the class uses a $130 plan.
    overview, _, _ = _use_cases(db)
    row = (await overview.execute()).classes[0]
    assert row.plan_id is None
    assert row.stale_link is True
    assert row.charged_cents == 10_000


@pytest.mark.asyncio
async def test_custom_and_linked_classes_bill_identically(db, acad) -> None:
    """Same fee, one linked and one custom: the monthly invoice is the same."""
    await _plan(db, acad, "group", 9_000)
    await _class(db, acad, "linked", amount_cents=9_000)
    await _class(db, acad, "custom", amount_cents=9_000)
    for sid in ("linked", "custom"):
        await db["students"].insert_one(
            {"academy_id": acad, "student_id": f"student-{sid}", "parent_id": "parent-1"}
        )
        await _enroll(db, acad, sid, sid)
    _, set_link, _ = _use_cases(db)
    await set_link.execute(_link_cmd(acad, "linked", "group"))
    await set_link.execute(_link_cmd(acad, "custom", None))

    payments = MongoPaymentRepository(
        db, clock=_clock, ledger_repo=MongoBillingLedgerRepository(db, clock=_clock)
    )
    await payments.generate_monthly_payments("2026-06")
    totals = {
        inv["enrollment_id"]: inv["total_cents"]
        async for inv in db["invoices"].find({"academy_id": acad, "period": "2026-06"})
    }
    assert totals == {"linked": 9_000, "custom": 9_000}


# ------------------------------------------------------------------ link rules


@pytest.mark.asyncio
async def test_link_matching_classes_links_only_unambiguous_matches(db, acad) -> None:
    await _plan(db, acad, "group", 12_000)
    await _plan(db, acad, "private", 24_000)
    await _plan(db, acad, "private-twin", 24_000)
    await _class(db, acad, "one-match", amount_cents=12_000)
    await _class(db, acad, "two-matches", amount_cents=24_000)
    await _class(db, acad, "no-match", monthly_price=180)
    overview, _, link_matching = _use_cases(db)

    assert (await overview.execute()).auto_linkable == 1
    result = await link_matching.execute(academy_id=acad, actor_id="owner-1")

    assert result.model_dump() == {
        "linked": 1,
        "no_match": 1,
        "several_matches": 1,
        "already_decided": 0,
    }
    rows = {row.session_id: row for row in (await overview.execute()).classes}
    assert rows["one-match"].plan_id == "group"
    assert rows["two-matches"].plan_id is None
    assert rows["two-matches"].matching_plan_ids == ["private", "private-twin"]
    assert rows["no-match"].plan_id is None
    assert rows["no-match"].charged_cents == 18_000
    plans = {
        row.plan.session_type_id: row.linked_classes for row in (await overview.execute()).plans
    }
    assert plans == {"group": 1, "private": 0, "private-twin": 0}

    # Idempotent: a second run links nothing new.
    again = await link_matching.execute(academy_id=acad, actor_id="owner-1")
    assert again.linked == 0
    assert again.already_decided == 1
    audit = [doc async for doc in db["billing_audit_log"].find({"academy_id": acad})]
    assert [a["action"] for a in audit] == ["class_plan_links_matched"]


@pytest.mark.asyncio
async def test_link_matching_never_overrides_an_owner_custom_choice(db, acad) -> None:
    await _plan(db, acad, "group", 12_000)
    await _class(db, acad, "sess-1", amount_cents=12_000)
    _, set_link, link_matching = _use_cases(db)
    await set_link.execute(_link_cmd(acad, "sess-1", None))

    result = await link_matching.execute(academy_id=acad, actor_id="owner-1")

    assert result.linked == 0
    assert result.already_decided == 1
    overview, _, _ = _use_cases(db)
    assert (await overview.execute()).classes[0].plan_id is None


@pytest.mark.asyncio
async def test_mismatched_price_is_refused_and_nothing_is_stored(db, acad) -> None:
    await _plan(db, acad, "group", 12_000)
    await _class(db, acad, "sess-1", amount_cents=15_000)
    _, set_link, _ = _use_cases(db)

    with pytest.raises(PlanPriceMismatch):
        await set_link.execute(_link_cmd(acad, "sess-1", "group"))

    assert await db["class_plan_links"].count_documents({}) == 0
    assert await db["billing_audit_log"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_owner_link_is_audited_and_writes_no_amount(db, acad) -> None:
    await _plan(db, acad, "group", 12_000)
    await _class(db, acad, "sess-1", amount_cents=12_000)
    _, set_link, _ = _use_cases(db)

    row = await set_link.execute(_link_cmd(acad, "sess-1", "group"))

    assert row.plan_id == "group"
    assert row.charged_cents == 12_000
    link = await db["class_plan_links"].find_one({"session_id": "sess-1"})
    assert link["academy_id"] == acad
    assert link["plan_id"] == "group"
    assert not any("cents" in key for key in link)
    entry = await db["billing_audit_log"].find_one({"action": "class_plan_link_changed"})
    assert entry["actor_id"] == "owner-1"
    assert entry["before"]["plan_id"] is None
    assert entry["after"]["plan_id"] == "group"


# ------------------------------------------------------------- read-time defaults


@pytest.mark.asyncio
async def test_plan_type_defaults_to_monthly_for_a_stored_plan(db, acad) -> None:
    await _plan(db, acad, "legacy", 12_000)  # no plan_type field, as in prod
    overview, _, _ = _use_cases(db)

    plans = (await overview.execute()).plans

    assert [p.plan.plan_type for p in plans] == ["monthly"]
    assert await db["session_types"].find_one({"plan_type": {"$exists": True}}) is None


@pytest.mark.asyncio
async def test_classes_list_students_and_skip_cancelled(db, acad) -> None:
    await _class(db, acad, "running", amount_cents=10_000)
    await _class(db, acad, "gone", amount_cents=10_000, status="cancelled")
    await _enroll(db, acad, "e1", "running")
    await _enroll(db, acad, "e2", "running")
    await _enroll(db, acad, "e3", "running", status="cancelled")
    overview, _, _ = _use_cases(db)

    classes = (await overview.execute()).classes

    assert [(c.session_id, c.students) for c in classes] == [("running", 2)]


@pytest.mark.asyncio
async def test_saved_overrides_are_listed_and_never_applied(db, acad) -> None:
    await _plan(db, acad, "group", 12_000)
    await _class(db, acad, "sess-1", amount_cents=12_000)
    await db["students"].insert_one(
        {"academy_id": acad, "student_id": "student-e1", "full_name": "Ada Lovelace"}
    )
    await _enroll(db, acad, "e1", "sess-1", amount_cents=9_000)
    await _enroll(db, acad, "e2", "sess-1")
    await db["student_billing_enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "bill-1",
                "student_id": "student-e1",
                "parent_id": "parent-1",
                "session_type_id": "group",
                "override_price_cents": 8_000,
                "status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "bill-2",
                "student_id": "student-e2",
                "parent_id": "parent-1",
                "session_type_id": "group",
                "override_price_cents": None,
                "status": "active",
            },
        ]
    )
    overview, _, _ = _use_cases(db)

    rows = (await overview.execute()).saved_overrides

    by_source = {(r.source, r.enrollment_id): r for r in rows}
    assert set(by_source) == {("billing_plan", "bill-1"), ("class_enrollment", "e1")}
    plan_row = by_source[("billing_plan", "bill-1")]
    assert (plan_row.label, plan_row.override_cents, plan_row.charged_cents) == (
        "Group",
        8_000,
        12_000,
    )
    assert plan_row.student_name == "Ada Lovelace"
    class_row = by_source[("class_enrollment", "e1")]
    assert (class_row.label, class_row.override_cents, class_row.charged_cents) == (
        "Class sess-1",
        9_000,
        12_000,
    )


@pytest.mark.asyncio
async def test_no_saved_overrides_is_an_empty_list(db, acad) -> None:
    await _class(db, acad, "sess-1", amount_cents=12_000)
    overview, _, _ = _use_cases(db)
    assert (await overview.execute()).saved_overrides == []


# -------------------------------------------------------------- tenant isolation


@pytest.mark.asyncio
async def test_other_academy_classes_plans_and_links_are_invisible(db, acad) -> None:
    other = "other-academy"
    await _plan(db, acad, "group", 12_000)
    await _plan(db, other, "their-plan", 12_000)
    await _class(db, acad, "mine", amount_cents=12_000)
    await _class(db, other, "theirs", amount_cents=12_000)
    await _enroll(db, other, "their-e", "theirs", amount_cents=1)
    overview, set_link, link_matching = _use_cases(db)

    body = await overview.execute()
    assert [c.session_id for c in body.classes] == ["mine"]
    assert [p.plan.session_type_id for p in body.plans] == ["group"]
    assert body.saved_overrides == []
    # Only one plan matches here: the other academy's same-price plan does
    # not make "mine" ambiguous.
    assert body.classes[0].matching_plan_ids == ["group"]

    with pytest.raises(PricingClassNotFound):
        await set_link.execute(_link_cmd(acad, "theirs", None))
    await link_matching.execute(academy_id=acad, actor_id="owner-1")
    assert await db["class_plan_links"].count_documents({"academy_id": other}) == 0

    token = _tenant.set(other)
    try:
        theirs = await overview.execute()
    finally:
        _tenant.reset(token)
    assert [c.session_id for c in theirs.classes] == ["theirs"]
    assert theirs.classes[0].plan_id is None
