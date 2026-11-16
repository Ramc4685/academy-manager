"""Academy-wide overdue family counts across billing periods (L2 risk review B2).

Runs against a real mongod when ``CONTRACT_TESTS_MONGO_URL`` is set.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.overdue_families import OverdueFamiliesReader

# 9 PM Dec 5 in Chicago is already Dec 6 in UTC: academy-local today is Dec 5.
_NOW = datetime(2026, 12, 6, 3, 0, tzinfo=UTC)


def _invoice(invoice_id: str, parent: str, period: str, due: datetime, **extra) -> dict:
    return {
        "academy_id": "test-academy",
        "invoice_id": invoice_id,
        "parent_id": parent,
        "enrollment_id": f"enr-{invoice_id}",
        "period": period,
        "status": "open",
        "due_date": due,
        "balance_due_cents": 15000,
        **extra,
    }


async def _counts(db, zone: str = "America/Chicago") -> dict[str, int]:
    async def timezone(_academy_id: str) -> str:
        return zone

    return await OverdueFamiliesReader(db, academy_timezone=timezone, clock=lambda: _NOW).counts()


async def _autopay(db, *enrollment_ids: str, academy: str = "test-academy") -> None:
    await db["student_billing_enrollments"].insert_many(
        [
            {"academy_id": academy, "enrollment_id": eid, "autopay_enrollment_status": "active"}
            for eid in enrollment_ids
        ]
    )


def _dunning(invoice_id: str, status: str, attempts: int, **extra) -> dict:
    return {
        "academy_id": "test-academy",
        "invoice_id": invoice_id,
        "status": status,
        "attempt_count": attempts,
        **extra,
    }


@pytest.mark.asyncio
async def test_last_month_owing_counts_when_this_month_is_not_due(db, acad) -> None:
    await db["invoices"].insert_many(
        [
            _invoice("nov", "fam-1", "2026-11", datetime(2026, 11, 5, tzinfo=UTC)),
            _invoice("dec", "fam-1", "2026-12", datetime(2026, 12, 10, tzinfo=UTC)),
        ]
    )

    assert await _counts(db) == {"past_due": 1, "needs_action": 1}


@pytest.mark.asyncio
async def test_a_dropped_student_who_still_owes_counts(db, acad) -> None:
    await db["invoices"].insert_one(
        _invoice(
            "old",
            "fam-2",
            "2026-09",
            datetime(2026, 9, 5, tzinfo=UTC),
            enrollment_id="enr-old",
            status="partially_paid",
        )
    )

    assert await _counts(db) == {"past_due": 1, "needs_action": 1}


@pytest.mark.asyncio
async def test_only_owing_sent_invoices_past_their_local_due_date_count(db, acad) -> None:
    dec5 = datetime(2026, 12, 5, tzinfo=UTC)  # due "today" on the academy clock
    await db["invoices"].insert_many(
        [
            _invoice("today", "fam-today", "2026-12", dec5),
            _invoice(
                "draft", "fam-draft", "2026-11", datetime(2026, 11, 5, tzinfo=UTC), status="draft"
            ),
            _invoice(
                "void", "fam-void", "2026-11", datetime(2026, 11, 5, tzinfo=UTC), status="void"
            ),
            _invoice(
                "paid",
                "fam-paid",
                "2026-11",
                datetime(2026, 11, 5, tzinfo=UTC),
                balance_due_cents=0,
            ),
            _invoice(
                "gone", "fam-gone", "2026-11", datetime(2026, 11, 5, tzinfo=UTC), is_deleted=True
            ),
            {
                **_invoice("other", "fam-other", "2026-11", datetime(2026, 11, 5, tzinfo=UTC)),
                "academy_id": "other-academy",
            },
        ]
    )

    assert await _counts(db) == {"past_due": 0, "needs_action": 0}


@pytest.mark.asyncio
async def test_autopay_cover_and_failed_attempts(db, acad) -> None:
    nov5 = datetime(2026, 11, 5, tzinfo=UTC)
    await db["invoices"].insert_many(
        [
            _invoice("covered", "fam-auto", "2026-11", nov5),
            _invoice("failed", "fam-failed", "2026-11", nov5),
            _invoice("manual", "fam-failed", "2026-10", datetime(2026, 10, 5, tzinfo=UTC)),
            _invoice(
                "legacy",
                "fam-legacy",
                "2026-11",
                nov5,
                enrollment_id=None,
                parent_id=None,
                parent_user_id="fam-legacy",
            ),
        ]
    )
    await _autopay(db, "enr-covered", "enr-failed")
    await db["dunning_states"].insert_one(_dunning("failed", "active", 1))

    # fam-auto is covered; fam-failed's failure outranks its manual invoice.
    assert await _counts(db) == {"past_due": 1, "needs_action": 2}


@pytest.mark.asyncio
async def test_a_parked_charge_that_never_reached_the_card_is_not_covered(db, acad) -> None:
    nov5 = datetime(2026, 11, 5, tzinfo=UTC)
    await db["invoices"].insert_many(
        [
            _invoice("nocard", "fam-nocard", "2026-11", nov5),
            _invoice("noacct", "fam-noacct", "2026-11", nov5),
            _invoice("hold", "fam-hold", "2026-11", nov5),
        ]
    )
    await _autopay(db, "enr-nocard", "enr-noacct", "enr-hold")
    # Parking leaves the ladder active with no attempt counted.
    await db["dunning_states"].insert_many(
        [
            _dunning("nocard", "active", 0, suppression_reason="charge_technical_failure"),
            _dunning("noacct", "active", 0, suppression_reason="connected_account_not_ready"),
            # A parent paying by checkout right now is still covered.
            _dunning("hold", "active", 0, suppression_reason="checkout_session_open"),
        ]
    )

    assert await _counts(db) == {"past_due": 2, "needs_action": 2}


@pytest.mark.asyncio
async def test_a_dunned_ladder_needs_action(db, acad) -> None:
    await db["invoices"].insert_one(
        _invoice("dunned", "fam-dunned", "2026-10", datetime(2026, 10, 5, tzinfo=UTC))
    )
    await _autopay(db, "enr-dunned")
    await db["dunning_states"].insert_one(_dunning("dunned", "dunned", 4))

    assert await _counts(db) == {"past_due": 0, "needs_action": 1}


@pytest.mark.asyncio
async def test_a_failed_charge_counts_on_its_due_date(db, acad) -> None:
    # Payments puts a failed attempt in failed_autopay whatever the due date.
    await db["invoices"].insert_one(
        _invoice("today", "fam-today", "2026-12", datetime(2026, 12, 5, tzinfo=UTC))
    )
    await _autopay(db, "enr-today")
    await db["dunning_states"].insert_one(_dunning("today", "active", 1))

    assert await _counts(db) == {"past_due": 0, "needs_action": 1}


@pytest.mark.asyncio
async def test_another_academys_dunning_and_autopay_rows_do_not_leak_in(db, acad) -> None:
    nov5 = datetime(2026, 11, 5, tzinfo=UTC)
    await db["invoices"].insert_many(
        [
            _invoice("plain", "fam-plain", "2026-11", nov5),
            _invoice("covered", "fam-covered", "2026-11", nov5),
        ]
    )
    await _autopay(db, "enr-covered")
    # Same ids in another tenant: autopay for fam-plain, a failure for fam-covered.
    await _autopay(db, "enr-plain", academy="other-academy")
    await db["dunning_states"].insert_one(
        {**_dunning("covered", "dunned", 4), "academy_id": "other-academy"}
    )

    assert await _counts(db) == {"past_due": 1, "needs_action": 1}


@pytest.mark.asyncio
async def test_a_nonsense_academy_timezone_falls_back_to_utc(db, acad) -> None:
    await db["invoices"].insert_one(
        _invoice("nov", "fam-1", "2026-11", datetime(2026, 11, 5, tzinfo=UTC))
    )

    assert await _counts(db, zone="Mars/Olympus") == {"past_due": 1, "needs_action": 1}
