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


async def _counts(db) -> dict[str, int]:
    async def chicago(_academy_id: str) -> str:
        return "America/Chicago"

    return await OverdueFamiliesReader(db, academy_timezone=chicago, clock=lambda: _NOW).counts()


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
    await db["enrollments"].insert_one(
        {"academy_id": "test-academy", "enrollment_id": "enr-old", "status": "withdrawn"}
    )
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
    await db["student_billing_enrollments"].insert_many(
        [
            {
                "academy_id": "test-academy",
                "enrollment_id": eid,
                "autopay_enrollment_status": "active",
            }
            for eid in ("enr-covered", "enr-failed")
        ]
    )
    await db["dunning_states"].insert_one(
        {
            "academy_id": "test-academy",
            "invoice_id": "failed",
            "status": "active",
            "attempt_count": 1,
        }
    )

    # fam-auto is covered; fam-failed's failure outranks its manual invoice.
    assert await _counts(db) == {"past_due": 1, "needs_action": 2}
