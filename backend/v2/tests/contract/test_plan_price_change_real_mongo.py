"""Change a plan price from a future month, against a REAL mongod (PR 26).

Real ``mongod`` with every migration applied (``real_db``), because the
guarantees here lean on what mongomock does not enforce: the 0212 partial
unique index ("one pending change per plan" under two concurrent applies),
compare-and-set updates, multikey lookups and the 0132 validators on the
billing collections. Skipped (not failed) when no mongod listens.

What is pinned, on a BLNO-shaped academy (Chicago clock, a class fee stored
as ``amount_cents`` and a legacy one as ``monthly_price_cents``, a linked and
a custom class at the same price):

* with no change on record, every charge path (monthly invoice, checkout
  quote, "Bill this month", cancellation credit pricing, move proration)
  charges exactly the stored class fee, i.e. main's behaviour;
* with a change scheduled for month M, month M-1 is unchanged and month M
  uses the new price, on every charge path, before and after the scheduler
  moves the stored fees;
* invoices already generated are byte-for-byte unchanged by apply, flip,
  cancel and a re-run of the monthly job;
* the current month and a month that already has invoices (or a checkout
  charge) are refused;
* a cancel is refused once a month on or after the change is quoted or
  invoiced; the parent quote's "next month" price is the next invoice's;
* a class marked custom leaves the change, a class linked later joins it;
* the cancellation CREDIT amount matches main's for the month's price;
* a custom-price class at the same price is not affected;
* another academy's plan and class with the SAME ids are never touched.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.v2.composition.occurrence_cancellation import compose_apply_occurrence_cancellation
from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellationCommand,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.plan_price_changes import (
    ApplyDuePlanPriceChanges,
    CancelPlanPriceChange,
    ListScheduledClassFees,
    PreviewPlanPriceChange,
    SchedulePlanPriceChange,
    SchedulePlanPriceChangeCommand,
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
from backend.v2.contexts.billing.domain.errors import (
    PriceChangeAlreadyCharged,
    PriceChangeInvalid,
    PriceChangeMonthNotAllowed,
    PriceChangeNotCancellable,
    PriceChangePending,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_enrollment_billing_target import (
    MongoEnrollmentBillingTargetReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    session_amount_cents,
)
from backend.v2.contexts.billing.infrastructure.mongo_move_schedule_reader import (
    MongoMoveScheduleReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_occurrence_cancellation import (
    MongoOccurrenceCancellationReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    MongoAcademyBillingMonth,
    MongoClassFeeResolver,
    MongoInvoicedPeriodReader,
    MongoPlanPriceChangeRepository,
    MongoPriceChangeFlipWriter,
)
from backend.v2.contexts.billing.infrastructure.mongo_pricing_read_model import (
    MongoClassPlanLinkRepository,
    MongoPricingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.interfaces.parent.payment_routes import _quote_response
from backend.v2.shared.tenancy.context import _current as _tenant

#: 2026-09-29, 07:00 in Chicago: the current billing month is September.
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
OLD = 12_000
NEW = 13_000
OTHER = "other-academy"
V2_ROOT = Path(__file__).resolve().parents[2]


def _clock() -> datetime:
    return NOW


# ------------------------------------------------------------------ fixtures


async def _seed_academy(db: Any, acad: str, *, fee_cents: int = OLD) -> None:
    """BLNO-shaped: two linked classes (one legacy fee field) and a custom one."""
    await db["session_types"].insert_one(
        {
            "academy_id": acad,
            "session_type_id": "group",
            "name": "Group class",
            "price_cents": fee_cents,
            "billing_period": "monthly",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    for session_id, fee in (
        ("juniors", {"amount_cents": fee_cents}),
        ("adults", {"monthly_price_cents": fee_cents}),
        ("squad", {"amount_cents": fee_cents}),
    ):
        await db["sessions"].insert_one(
            {
                "academy_id": acad,
                "session_id": session_id,
                "title": session_id.title(),
                "coach_id": "coach-1",
                "location": "Court 1",
                "timezone": "America/Chicago",
                "start_date": "2026-05-01",
                "end_date": "2027-06-30",
                "days_of_week": ["Tue", "Thu"],
                "start_time": "18:00",
                "end_time": "19:00",
                "capacity": 12,
                "status": "active",
                **fee,
            }
        )
    for session_id, plan_id in (("juniors", "group"), ("adults", "group"), ("squad", None)):
        await db["class_plan_links"].insert_one(
            {"academy_id": acad, "session_id": session_id, "plan_id": plan_id, "source": "owner"}
        )
    enrollments = [
        ("e1", "juniors", "active"),
        ("e2", "juniors", "active"),
        ("e3", "adults", "active"),
        ("e4", "squad", "active"),
        ("e5", "juniors", "paused"),
    ]
    for enrollment_id, session_id, status in enrollments:
        student_id = f"student-{enrollment_id}"
        await db["students"].insert_one(
            {"academy_id": acad, "student_id": student_id, "parent_id": "parent-1"}
        )
        await db["enrollments"].insert_one(
            {
                "academy_id": acad,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "student_id": student_id,
                "parent_id": "parent-1",
                "status": status,
                "billing_type": "standard",
                "billing_start_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            }
        )


class _Kit:
    """The use cases wired the way ``composition/pricing.py`` wires them."""

    def __init__(self, db: Any) -> None:
        self.db = db
        audit = RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db), now=_clock)
        self.changes = MongoPlanPriceChangeRepository(db)
        read_model = MongoPricingReadModel(db, clock=_clock)
        links = MongoClassPlanLinkRepository(db)
        session_types = MongoSessionTypeRepository(db)
        current_period = MongoAcademyBillingMonth(db, clock=_clock).current_period
        self.preview = PreviewPlanPriceChange(
            session_types=session_types,
            read_model=read_model,
            links=links,
            changes=self.changes,
            invoiced=MongoInvoicedPeriodReader(db, clock=_clock),
            current_period=current_period,
        )
        self.schedule = SchedulePlanPriceChange(
            preview=self.preview, changes=self.changes, audit=audit, clock=_clock
        )
        self.invoiced = MongoInvoicedPeriodReader(db, clock=_clock)
        self.cancel = CancelPlanPriceChange(
            changes=self.changes,
            current_period=current_period,
            audit=audit,
            charges=self.invoiced,
            clock=_clock,
        )
        self.apply_due = ApplyDuePlanPriceChanges(
            changes=self.changes, flips=MongoPriceChangeFlipWriter(db), audit=audit, clock=_clock
        )
        self.scheduled_fees = ListScheduledClassFees(changes=self.changes, read_model=read_model)
        self.overview = GetPricingOverview(
            session_types=session_types,
            read_model=read_model,
            links=links,
            price_changes=self.changes,
        )
        self.set_link = SetClassPlanLink(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            clock=_clock,
            price_changes=self.changes,
            charges=self.invoiced,
        )
        self.link_matching = LinkMatchingClasses(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            clock=_clock,
            price_changes=self.changes,
            charges=self.invoiced,
        )
        self.payments = MongoPaymentRepository(
            db, clock=_clock, ledger_repo=MongoBillingLedgerRepository(db, clock=_clock)
        )

    def cmd(self, acad: str, period: str, *, price: int = NEW) -> SchedulePlanPriceChangeCommand:
        return SchedulePlanPriceChangeCommand(
            academy_id=acad,
            plan_id="group",
            new_price_cents=price,
            effective_period=period,
            actor_id="owner-1",
        )

    async def generate(self, period: str) -> Any:
        return await self.payments.generate_monthly_payments(period)

    async def invoice_totals(self, acad: str, period: str) -> dict[str, int]:
        return {
            doc["enrollment_id"]: doc["subtotal_cents"]
            async for doc in self.db["invoices"].find({"academy_id": acad, "period": period})
        }

    async def quote(self, session_id: str, start: datetime) -> int:
        return (await self.quote_snapshot(session_id, start)).monthly_price_cents

    async def quote_snapshot(self, session_id: str, start: datetime) -> Any:
        return await QuoteEnrollment(
            sessions=self.payments,
            snapshots=self.payments,
            occurrences=self.payments,
            clock=_clock,
            class_fees=MongoClassFeeResolver(self.db),
        ).execute(
            QuoteEnrollmentCommand(
                session_id=session_id, billing_start_at=start, calculated_by="parent-1"
            )
        )

    def link(self, acad: str, session_id: str, plan_id: str | None) -> SetClassPlanLinkCommand:
        return SetClassPlanLinkCommand(
            academy_id=acad, session_id=session_id, plan_id=plan_id, actor_id="owner-1"
        )

    async def bill_this_month(self, enrollment_id: str, period: str) -> int:
        target = await MongoEnrollmentBillingTargetReader(self.db, clock=_clock).load(
            enrollment_id, period
        )
        assert target is not None
        return target.monthly_price_cents

    async def cancellation_price(self, session_id: str, period: str) -> int:
        pricing = await MongoOccurrenceCancellationReader(self.db).session_pricing(
            session_id, period=period
        )
        assert pricing is not None
        return pricing.monthly_price_cents

    async def move_price(self, session_id: str, period: str) -> int:
        schedule = await MongoMoveScheduleReader(self.db).load(session_id=session_id, period=period)
        assert schedule is not None
        return schedule.monthly_price_cents

    async def every_path(self, session_id: str, enrollment_id: str, period: str) -> list[int]:
        """The fee each charge path reads for ``session_id`` in ``period``."""
        year, month = (int(p) for p in period.split("-"))
        return [
            await self.quote(session_id, datetime(year, month, 1, 12, 0, tzinfo=UTC)),
            await self.bill_this_month(enrollment_id, period),
            await self.cancellation_price(session_id, period),
            await self.move_price(session_id, period),
        ]


#: Every record a charge lives in: the AR ledger, the monthly run's primary
#: ``payments`` record and its idempotency keys, and the calculation snapshots.
_CHARGE_COLLECTIONS = (
    "invoices",
    "invoice_lines",
    "payments",
    "billing_invoice_keys",
    "billing_calculation_snapshots",
)


async def _ledger_snapshot(db: Any) -> list[dict[str, Any]]:
    """Every charge record, in a stable order, as stored."""
    out: list[dict[str, Any]] = []
    for collection in _CHARGE_COLLECTIONS:
        out.extend(
            [
                {"collection": collection, **doc}
                async for doc in db[collection].find({}).sort([("_id", 1)])
            ]
        )
    return out


def _assert_unchanged(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    """Every record in ``before`` is still stored, field for field.

    A re-run of the monthly job may ADD records (it stamps a calculation
    snapshot per resolved charge, as on main); it must never change one.
    """
    now = {(doc["collection"], doc["_id"]): doc for doc in after}
    for doc in before:
        assert now.get((doc["collection"], doc["_id"])) == doc


# ------------------------------------------------ no change: main's behaviour


@pytest.mark.asyncio
async def test_without_a_change_every_charge_path_reads_the_stored_class_fee(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    stored = {
        sid: session_amount_cents(await real_db["sessions"].find_one({"session_id": sid}))
        for sid in ("juniors", "adults", "squad")
    }
    assert stored == {"juniors": OLD, "adults": OLD, "squad": OLD}

    for period in ("2026-09", "2026-10", "2026-11"):
        result = await kit.generate(period)
        assert result.created == 4  # e5 is paused: never invoiced
        assert await kit.invoice_totals(acad, period) == {
            "e1": OLD,
            "e2": OLD,
            "e3": OLD,
            "e4": OLD,
        }
    for period in ("2026-10", "2026-12"):
        assert await kit.every_path("juniors", "e1", period) == [OLD] * 4
        assert await kit.every_path("adults", "e3", period) == [OLD] * 4
    assert await real_db["plan_price_changes"].count_documents({}) == 0


# ------------------------------------------------------- scheduled change


@pytest.mark.asyncio
async def test_preview_lists_linked_classes_billed_students_and_custom_as_not_affected(
    real_db, acad
) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)

    preview = await kit.preview.execute(plan_id="group", new_price_cents=NEW)

    # September is current and has no invoices yet: still not allowed.
    assert preview.earliest_period == "2026-10"
    assert preview.effective_period == "2026-10"
    assert [(c.session_id, c.students) for c in preview.classes] == [
        ("adults", 1),
        ("juniors", 2),  # e5 is paused: the monthly run does not bill it
    ]
    assert [c.session_id for c in preview.not_affected] == ["squad"]
    assert (preview.total_classes, preview.total_students) == (2, 3)
    assert (preview.old_monthly_cents, preview.new_monthly_cents) == (3 * OLD, 3 * NEW)
    # Read only.
    assert await real_db["plan_price_changes"].count_documents({}) == 0
    assert await real_db["billing_audit_log"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_month_before_is_unchanged_and_the_month_uses_the_new_price(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    await kit.generate("2026-09")
    before = await _ledger_snapshot(real_db)

    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    assert change.session_ids == ["adults", "juniors"]
    # Recording the change wrote no invoice, line, fee or plan price.
    assert await _ledger_snapshot(real_db) == before
    assert (await real_db["sessions"].find_one({"session_id": "juniors"}))["amount_cents"] == OLD
    assert (await real_db["session_types"].find_one({"session_type_id": "group"}))[
        "price_cents"
    ] == OLD

    await kit.generate("2026-10")
    await kit.generate("2026-11")
    assert await kit.invoice_totals(acad, "2026-10") == {
        "e1": OLD,
        "e2": OLD,
        "e3": OLD,
        "e4": OLD,
    }
    assert await kit.invoice_totals(acad, "2026-11") == {
        "e1": NEW,
        "e2": NEW,
        "e3": NEW,  # legacy monthly_price_cents class moves too
        "e4": OLD,  # custom price: not affected
    }
    for session_id, enrollment_id in (("juniors", "e1"), ("adults", "e3")):
        assert await kit.every_path(session_id, enrollment_id, "2026-10") == [OLD] * 4
        assert await kit.every_path(session_id, enrollment_id, "2026-12") == [NEW] * 4
    assert await kit.every_path("squad", "e4", "2026-12") == [OLD] * 4
    # A registration that starts mid-October is prorated on October's price.
    assert await kit.quote("juniors", datetime(2026, 10, 15, 12, tzinfo=UTC)) == OLD


@pytest.mark.asyncio
async def test_the_flip_moves_fees_and_plan_together_and_changes_no_charge(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    await kit.generate("2026-09")
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    await kit.generate("2026-10")

    # October: not due yet.
    assert (await kit.apply_due.execute(academy_id=acad, period="2026-10")).applied == 0
    await kit.generate("2026-11")
    before = await _ledger_snapshot(real_db)

    result = await kit.apply_due.execute(academy_id=acad, period="2026-11")

    assert (result.applied, result.classes_moved) == (1, 2)
    fees = {
        doc["session_id"]: session_amount_cents(doc)
        async for doc in real_db["sessions"].find({"academy_id": acad})
    }
    assert fees == {"juniors": NEW, "adults": NEW, "squad": OLD}
    plan = await real_db["session_types"].find_one({"academy_id": acad})
    assert plan["price_cents"] == NEW
    # Links did not go stale: both classes still show the plan.
    rows = {row.session_id: row for row in (await kit.overview.execute()).classes}
    assert (rows["juniors"].plan_id, rows["juniors"].stale_link) == ("group", False)
    assert (rows["adults"].plan_id, rows["adults"].stale_link) == ("group", False)
    assert rows["juniors"].scheduled_cents is None
    # The flip wrote no charge record at all.
    assert await _ledger_snapshot(real_db) == before
    # Same answer per month after the flip; nothing already invoiced moved,
    # even when the monthly job runs again for those months.
    for period in ("2026-09", "2026-10", "2026-11"):
        rerun = await kit.generate(period)
        assert rerun.created == 0
    _assert_unchanged(before, await _ledger_snapshot(real_db))
    assert await kit.every_path("juniors", "e1", "2026-10") == [OLD] * 4
    assert await kit.every_path("juniors", "e1", "2026-12") == [NEW] * 4
    # Re-running the flip is a no-op.
    assert (await kit.apply_due.execute(academy_id=acad, period="2026-12")).applied == 0
    actions = [doc["action"] async for doc in real_db["billing_audit_log"].find({})]
    assert actions == ["plan_price_change_scheduled", "plan_price_change_applied"]


@pytest.mark.asyncio
async def test_pricing_page_and_class_editor_show_the_scheduled_fee(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    overview = await kit.overview.execute()
    rows = {row.session_id: row for row in overview.classes}
    assert (rows["juniors"].scheduled_cents, rows["juniors"].scheduled_from) == (NEW, "2026-11")
    assert rows["squad"].scheduled_cents is None
    plan = overview.plans[0]
    assert (plan.scheduled_cents, plan.scheduled_from) == (NEW, "2026-11")
    fees = await kit.scheduled_fees.execute()
    assert sorted((f.session_id, f.new_cents, f.effective_period) for f in fees) == [
        ("adults", NEW, "2026-11"),
        ("juniors", NEW, "2026-11"),
    ]


# ----------------------------------------------------------- month rules


@pytest.mark.asyncio
async def test_current_and_invoiced_months_are_refused(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)

    for period in ("2026-08", "2026-09"):
        with pytest.raises(PriceChangeMonthNotAllowed):
            await kit.schedule.execute(kit.cmd(acad, period))

    # Next month's invoices already exist (generated early): earliest moves on.
    await kit.generate("2026-10")
    preview = await kit.preview.execute(plan_id="group", new_price_cents=NEW)
    assert preview.earliest_period == "2026-11"
    with pytest.raises(PriceChangeMonthNotAllowed):
        await kit.schedule.execute(kit.cmd(acad, "2026-10"))
    with pytest.raises(PriceChangeInvalid):
        await kit.schedule.execute(kit.cmd(acad, "2026-11", price=OLD))
    assert await real_db["plan_price_changes"].count_documents({}) == 0
    assert await kit.invoice_totals(acad, "2026-10") == {
        "e1": OLD,
        "e2": OLD,
        "e3": OLD,
        "e4": OLD,
    }


@pytest.mark.asyncio
async def test_one_pending_change_per_plan_even_when_two_applies_race(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)

    outcomes = await asyncio.gather(
        kit.schedule.execute(kit.cmd(acad, "2026-11")),
        kit.schedule.execute(kit.cmd(acad, "2026-12", price=14_000)),
        return_exceptions=True,
    )

    assert sum(isinstance(o, PriceChangePending) for o in outcomes) == 1
    assert await real_db["plan_price_changes"].count_documents({"status": "scheduled"}) == 1
    with pytest.raises(PriceChangePending):
        await kit.schedule.execute(kit.cmd(acad, "2027-01"))


# ------------------------------------------------------------------- cancel


@pytest.mark.asyncio
async def test_cancel_before_the_month_restores_the_old_price_and_is_audited(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    await kit.cancel.execute(academy_id=acad, change_id=change.change_id, actor_id="owner-1")

    assert await kit.every_path("juniors", "e1", "2026-12") == [OLD] * 4
    with pytest.raises(PriceChangeNotCancellable):
        await kit.cancel.execute(academy_id=acad, change_id=change.change_id, actor_id="owner-1")
    # The plan is free for a new change. (December is taken: the "Bill this
    # month" read above charged it, so the earliest month is January.)
    await kit.schedule.execute(kit.cmd(acad, "2027-01", price=14_000))
    actions = [doc["action"] async for doc in real_db["billing_audit_log"].find({})]
    assert actions == [
        "plan_price_change_scheduled",
        "plan_price_change_cancelled",
        "plan_price_change_scheduled",
    ]


@pytest.mark.asyncio
async def test_a_change_that_took_effect_cannot_be_cancelled(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-10"))
    await kit.apply_due.execute(academy_id=acad, period="2026-10")

    with pytest.raises(PriceChangeNotCancellable):
        await kit.cancel.execute(academy_id=acad, change_id=change.change_id, actor_id="owner-1")


@pytest.mark.asyncio
async def test_a_hand_edited_class_fee_wins_over_the_scheduled_change(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    # The owner sets the class fee by hand after scheduling.
    await real_db["sessions"].update_one(
        {"academy_id": acad, "session_id": "juniors"}, {"$set": {"amount_cents": 15_000}}
    )

    assert await kit.every_path("juniors", "e1", "2026-12") == [15_000] * 4
    await kit.apply_due.execute(academy_id=acad, period="2026-11")
    juniors = await real_db["sessions"].find_one({"academy_id": acad, "session_id": "juniors"})
    assert juniors["amount_cents"] == 15_000
    assert await kit.every_path("juniors", "e1", "2026-10") == [15_000] * 4
    assert await kit.every_path("adults", "e3", "2026-12") == [NEW] * 4


@pytest.mark.asyncio
async def test_cancel_is_refused_once_a_later_month_is_quoted_or_invoiced(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    # October: a parent registers for Juniors starting in November and is
    # quoted the new price.
    assert await kit.quote("juniors", datetime(2026, 11, 3, 12, tzinfo=UTC)) == NEW

    with pytest.raises(PriceChangeAlreadyCharged):
        await kit.cancel.execute(academy_id=acad, change_id=change.change_id, actor_id="owner-1")

    # Once that quote expires unpaid, nothing holds the new price: cancel works.
    await real_db["billing_calculation_snapshots"].update_many(
        {"academy_id": acad, "status": "OPEN"},
        {"$set": {"expires_at": datetime(2026, 9, 1, tzinfo=UTC)}},
    )
    await kit.cancel.execute(academy_id=acad, change_id=change.change_id, actor_id="owner-1")

    # A monthly run generated early for the month also blocks a cancel.
    second = await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    await kit.generate("2026-11")
    with pytest.raises(PriceChangeAlreadyCharged):
        await kit.cancel.execute(academy_id=acad, change_id=second.change_id, actor_id="owner-1")
    assert (await kit.changes.get(second.change_id)).status == "scheduled"  # type: ignore[union-attr]
    assert await kit.invoice_totals(acad, "2026-11") == {
        "e1": NEW,
        "e2": NEW,
        "e3": NEW,
        "e4": OLD,
    }


@pytest.mark.asyncio
async def test_a_checkout_charge_for_a_future_month_moves_the_earliest_month(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    # A registration for November is quoted and checked out (snapshot consumed).
    snapshot = await kit.quote_snapshot("juniors", datetime(2026, 11, 3, 12, tzinfo=UTC))
    assert await kit.payments.consume(snapshot.snapshot_id) is not None

    preview = await kit.preview.execute(plan_id="group", new_price_cents=NEW)

    assert preview.earliest_period == "2026-12"
    with pytest.raises(PriceChangeMonthNotAllowed):
        await kit.schedule.execute(kit.cmd(acad, "2026-11"))


@pytest.mark.asyncio
async def test_the_quote_tells_the_parent_next_months_price(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    start = datetime(2026, 10, 10, 12, tzinfo=UTC)

    # No change on record: next month's price is this month's (main's copy).
    plain = _quote_response(await kit.quote_snapshot("juniors", start))
    assert (plain.monthly_price_cents, plain.next_billing_amount_cents) == (OLD, OLD)
    assert plain.next_billing_message == "Starting next month, tuition is $120.00/month."

    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    snapshot = await kit.quote_snapshot("juniors", start)
    response = _quote_response(snapshot)

    assert response.monthly_price_cents == OLD  # October is prorated on October's price
    assert response.next_billing_amount_cents == NEW
    assert response.next_billing_message == "Starting next month, tuition is $130.00/month."
    stored = await real_db["billing_calculation_snapshots"].find_one(
        {"snapshot_id": snapshot.snapshot_id}
    )
    assert "next_monthly_price_cents" not in stored  # never stored


# ------------------------------------------------ links and a pending change


@pytest.mark.asyncio
async def test_marking_a_class_custom_takes_it_out_of_the_change(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    await kit.set_link.execute(kit.link(acad, "juniors", None))

    stored = await kit.changes.get(change.change_id)
    assert stored is not None and stored.session_ids == ("adults",)
    assert await kit.every_path("juniors", "e1", "2026-12") == [OLD] * 4
    await kit.generate("2026-11")
    assert await kit.invoice_totals(acad, "2026-11") == {
        "e1": OLD,
        "e2": OLD,
        "e3": NEW,
        "e4": OLD,
    }
    await kit.apply_due.execute(academy_id=acad, period="2026-11")
    juniors = await real_db["sessions"].find_one({"academy_id": acad, "session_id": "juniors"})
    assert juniors["amount_cents"] == OLD
    audit = await real_db["billing_audit_log"].find_one({"action": "class_plan_link_changed"})
    assert audit["after"]["price_changes_left"] == [change.change_id]


@pytest.mark.asyncio
async def test_moving_a_class_off_the_plan_is_refused_once_it_is_charged_at_the_new_price(
    real_db, acad
) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    await kit.quote("juniors", datetime(2026, 11, 3, 12, tzinfo=UTC))

    with pytest.raises(PriceChangeAlreadyCharged):
        await kit.set_link.execute(kit.link(acad, "juniors", None))

    stored = await kit.changes.get(change.change_id)
    assert stored is not None and "juniors" in stored.session_ids
    link = await real_db["class_plan_links"].find_one({"academy_id": acad, "session_id": "juniors"})
    assert link["plan_id"] == "group"


@pytest.mark.asyncio
async def test_a_class_linked_after_scheduling_joins_the_change_and_its_link_stays(
    real_db, acad
) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    change = await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    # Squad (custom at the plan's price) is linked to the plan in October.
    await kit.set_link.execute(kit.link(acad, "squad", "group"))

    stored = await kit.changes.get(change.change_id)
    assert stored is not None and "squad" in stored.session_ids
    assert await kit.every_path("squad", "e4", "2026-10") == [OLD] * 4
    assert await kit.every_path("squad", "e4", "2026-12") == [NEW] * 4
    await kit.apply_due.execute(academy_id=acad, period="2026-11")
    rows = {row.session_id: row for row in (await kit.overview.execute()).classes}
    assert (rows["squad"].plan_id, rows["squad"].stale_link) == ("group", False)
    assert rows["squad"].charged_cents == NEW


@pytest.mark.asyncio
async def test_the_flip_keeps_legacy_fee_fields_in_step(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    kit = _Kit(real_db)
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))

    await kit.apply_due.execute(academy_id=acad, period="2026-11")

    adults = await real_db["sessions"].find_one({"academy_id": acad, "session_id": "adults"})
    assert (adults["amount_cents"], adults["monthly_price_cents"]) == (NEW, NEW)
    juniors = await real_db["sessions"].find_one({"academy_id": acad, "session_id": "juniors"})
    assert "monthly_price_cents" not in juniors


# ------------------------------------------------- cancellation credit amount


async def _credit_for(db: Any, acad: str, start_at: datetime) -> dict[str, int]:
    token = _tenant.set(acad)
    try:
        result = await compose_apply_occurrence_cancellation(db).execute(
            ApplyOccurrenceCancellationCommand(
                occurrence_id=f"occ-{start_at:%Y%m%d}",
                session_id="juniors",
                start_at=start_at,
                reason="Rain",
            )
        )
    finally:
        _tenant.reset(token)
    return {d.enrollment_id: d.amount_cents for d in result.decisions}


@pytest.mark.asyncio
async def test_cancellation_credit_amounts_follow_the_month_price(real_db, acad) -> None:
    """The credit ApplyOccurrenceCancellation issues, not just the price it reads.

    ``acad`` has a change to NEW from November. ``at-old`` / ``at-new`` never
    had a change: classes stored at OLD / NEW, i.e. main's credit for each
    price. October's credit must equal main's at OLD, November's main's at NEW.
    """
    await _seed_academy(real_db, acad)
    await _seed_academy(real_db, "at-old")
    await _seed_academy(real_db, "at-new", fee_cents=NEW)
    kit = _Kit(real_db)
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    october = datetime(2026, 10, 6, 23, 0, tzinfo=UTC)  # Tue 18:00 Chicago (CDT)
    november = datetime(2026, 11, 11, 0, 0, tzinfo=UTC)  # Tue Nov 10 18:00 CST
    oct_old = await _credit_for(real_db, "at-old", october)
    nov_old = await _credit_for(real_db, "at-old", november)
    nov_new = await _credit_for(real_db, "at-new", november)
    assert oct_old["e1"] > 0 and nov_new["e1"] > nov_old["e1"] > 0

    assert await _credit_for(real_db, acad, october) == oct_old
    assert await _credit_for(real_db, acad, november) == nov_new


# -------------------------------------------------------- tenant isolation


@pytest.mark.asyncio
async def test_another_academy_with_the_same_plan_and_class_ids_is_untouched(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_academy(real_db, OTHER)
    kit = _Kit(real_db)
    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    await kit.apply_due.execute(academy_id=acad, period="2026-11")

    token = _tenant.set(OTHER)
    try:
        assert await kit.every_path("juniors", "e1", "2026-12") == [OLD] * 4
        await kit.generate("2026-11")
        assert await kit.invoice_totals(OTHER, "2026-11") == {
            "e1": OLD,
            "e2": OLD,
            "e3": OLD,
            "e4": OLD,
        }
        assert (await kit.apply_due.execute(academy_id=OTHER, period="2026-12")).applied == 0
        assert await kit.scheduled_fees.execute() == []
    finally:
        _tenant.reset(token)
    theirs = await real_db["sessions"].find_one({"academy_id": OTHER, "session_id": "juniors"})
    assert theirs["amount_cents"] == OLD
    their_plan = await real_db["session_types"].find_one({"academy_id": OTHER})
    assert their_plan["price_cents"] == OLD
    assert await real_db["billing_audit_log"].count_documents({"academy_id": OTHER}) == 0


def test_both_checkout_quote_wirings_read_the_fee_for_the_month() -> None:
    """The admin and parent quotes are composed with the period-aware fee read."""
    for module in ("admin.py", "parent.py"):
        source = (V2_ROOT / "composition" / module).read_text(encoding="utf-8")
        assert "class_fees=MongoClassFeeResolver(db)" in source, module
