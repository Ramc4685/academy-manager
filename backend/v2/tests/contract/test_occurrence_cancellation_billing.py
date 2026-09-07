"""Cancelling one class date, against real collections (issue #671).

Covers the three claims the feature rests on, end to end through Mongo:

* the override row is written where the monthly generator reads it, so an
  un-invoiced period stops pricing the date;
* an already-invoiced family gets exactly one credit worth the date's share;
* running it twice changes nothing.
"""

from __future__ import annotations

import importlib
import inspect
from datetime import UTC, datetime

import pytest

from backend.v2.composition.occurrence_cancellation import (
    compose_apply_occurrence_cancellation,
)
from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellationCommand,
)
from backend.v2.contexts.billing.domain.credits import CLASS_CANCELLATION_SOURCE_TYPE
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_occurrence_cancellation import (
    MongoOccurrenceCancellationReader,
)
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-671"
TZ = "America/Chicago"
# 2026-09 has five Thursdays: 3, 10, 17, 24; the template stops on the 30th.
CANCELLED_DAY = datetime(2026, 9, 10, 23, 0, tzinfo=UTC)  # 18:00 America/Chicago


async def _seed(db, *, invoiced: bool, price_field: str = "amount_cents") -> None:
    await db["academies"].insert_one({"academy_id": ACADEMY, "timezone": TZ})
    await db["sessions"].insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-1",
            "title": "Beginner badminton",
            price_field: 12000,
            "timezone": TZ,
            "days_of_week": ["Thu"],
            "start_time": "18:00",
            "end_time": "19:00",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {"academy_id": ACADEMY, "student_id": "st-1", "parent_id": "par-1"}
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "student_id": "st-1",
            "status": "active",
            "enrolled_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )
    if invoiced:
        await db["invoices"].insert_one(
            {
                "academy_id": ACADEMY,
                "invoice_id": "inv-1",
                "parent_id": "par-1",
                "student_id": "st-1",
                "enrollment_id": "enr-1",
                "period": "2026-09",
                "status": "open",
                "subtotal_cents": 12000,
                "discount_cents": 0,
                "total_cents": 12000,
                "balance_due_cents": 12000,
                "currency": "usd",
                "due_date": "2026-09-08",
                "created_at": datetime(2026, 8, 28, tzinfo=UTC),
                "updated_at": datetime(2026, 8, 28, tzinfo=UTC),
            }
        )


def _cmd() -> ApplyOccurrenceCancellationCommand:
    return ApplyOccurrenceCancellationCommand(
        occurrence_id="occ-1",
        session_id="sess-1",
        start_at=CANCELLED_DAY,
        reason="gym flooded",
        actor_id="admin-1",
    )


@pytest.mark.asyncio
async def test_override_is_written_and_the_generator_stops_pricing_the_date(db) -> None:
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=False)
        reader = MongoOccurrenceCancellationReader(db)
        before = await reader.occurrences_for_period(session_id="sess-1", period="2026-09")
        assert len(before) == 4
        assert all(row.is_billable for row in before)

        await compose_apply_occurrence_cancellation(db).execute(_cmd())

        override = await db["session_occurrence_overrides"].find_one({"academy_id": ACADEMY})
        assert override is not None
        assert override["status"] == "cancelled"
        assert override["is_billable"] is False
        assert override["source_occurrence_id"] == "occ-1"

        after = await reader.occurrences_for_period(session_id="sess-1", period="2026-09")
        assert len(after) == 4  # the date is still listed...
        cancelled = [row for row in after if not row.is_billable]
        assert [row.start_at for row in cancelled] == [CANCELLED_DAY]  # ...but not priced


@pytest.mark.asyncio
async def test_invoiced_family_is_credited_one_class_share(db) -> None:
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=True)

        result = await compose_apply_occurrence_cancellation(db).execute(_cmd())

        assert result.period == "2026-09"
        credits = await MongoCreditLedgerRepository(db).list_for_parent("par-1")
        assert len(credits) == 1
        credit = credits[0]
        assert credit.type == "CLASS_CANCELLATION_CREDIT"
        assert credit.amount_cents == 3000  # 12000 / 4 Thursdays
        assert credit.remaining_amount_cents == 3000
        assert credit.enrollment_id == "enr-1"
        assert credit.source_id == "occ-1:enr-1"
        assert credit.academy_id == ACADEMY
        assert result.credits == {"enr-1": credit.credit_id}


@pytest.mark.asyncio
async def test_running_twice_credits_once_and_leaves_one_override(db) -> None:
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=True)
        use_case = compose_apply_occurrence_cancellation(db)

        first = await use_case.execute(_cmd())
        second = await use_case.execute(_cmd())

        assert await db["account_credit_ledger"].count_documents({"academy_id": ACADEMY}) == 1
        assert (
            await db["session_occurrence_overrides"].count_documents({"academy_id": ACADEMY}) == 1
        )
        assert second.credits == first.credits
        assert "existing=1" in second.billing_result


@pytest.mark.asyncio
async def test_void_period_invoice_is_not_credited(db) -> None:
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=True)
        await db["invoices"].update_one({"invoice_id": "inv-1"}, {"$set": {"status": "void"}})

        result = await compose_apply_occurrence_cancellation(db).execute(_cmd())

        assert await db["account_credit_ledger"].count_documents({"academy_id": ACADEMY}) == 0
        assert result.decisions[0].outcome == "skipped:invoice_void"


@pytest.mark.asyncio
async def test_another_academys_cancel_never_touches_this_one(db) -> None:
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=True)
    with tenant_scope("other-academy"):
        await compose_apply_occurrence_cancellation(db).execute(_cmd())

    assert await db["account_credit_ledger"].count_documents({"academy_id": ACADEMY}) == 0
    assert await db["session_occurrence_overrides"].count_documents({"academy_id": ACADEMY}) == 0


@pytest.mark.asyncio
async def test_a_legacy_priced_session_still_credits_the_families(db) -> None:
    """#671: a session doc carrying only ``monthly_price_cents``.

    The generator prices it through its ``session_amount_cents`` fallback
    chain; a bare ``amount_cents`` read in the cancellation path priced it at
    zero, so every family was skipped as ``zero_amount`` while the month was
    still invoiced in full.
    """
    await run_pending_migrations(db)
    with tenant_scope(ACADEMY):
        await _seed(db, invoiced=True, price_field="monthly_price_cents")

        result = await compose_apply_occurrence_cancellation(db).execute(_cmd())

        pricing = await MongoOccurrenceCancellationReader(db).session_pricing("sess-1")
        assert pricing is not None
        assert pricing.monthly_price_cents == 12000
        credits = await MongoCreditLedgerRepository(db).list_for_parent("par-1")
        assert [credit.amount_cents for credit in credits] == [3000]
        assert result.decisions[0].outcome == "credited"


@pytest.mark.asyncio
async def test_migration_0168_scopes_the_unique_credit_index_to_this_feature(db) -> None:
    """The unique credit index must cover ONLY the class-cancellation key
    space (#671).

    OVERPAYMENT credits already carry a string ``source_type`` with
    ``source_id`` = a payment id or an allocation id, written by a non-atomic
    check-then-insert (``record_manual_payment``), so prod may already hold
    duplicates. A ``{"$type": "string"}`` filter would abort this migration on
    DuplicateKeyError — taking the override index and the validator refresh
    with it — and would turn that pre-existing race into a 500 on a money
    path. mongomock does not evaluate partial filters, so the assertion is on
    the declared index spec, which is what Mongo actually applies.
    """
    migration = importlib.import_module("backend.v2.migrations.0168_occurrence_cancellation")
    assert migration.CLASS_CANCELLATION_SOURCE_TYPE == CLASS_CANCELLATION_SOURCE_TYPE

    await run_pending_migrations(db)
    indexes = await db["account_credit_ledger"].index_information()
    assert "credit_source_unique" in indexes

    source = inspect.getsource(migration.up)
    assert 'partialFilterExpression={"source_type": CLASS_CANCELLATION_SOURCE_TYPE}' in source
    assert "$type" not in source
