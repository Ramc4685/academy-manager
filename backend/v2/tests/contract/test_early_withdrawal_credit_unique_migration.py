"""Issue #690: approved withdrawal credits need a DB guard, not just code.

``RecordWithdrawalDecision`` dedupes with a check-then-create, so two
concurrent withdraws for one enrollment can both approve a credit and
double the family's spendable balance. These tests pin the partial unique
index the migration adds, the carve-outs the partial filter buys (other
credit types, and voided withdrawal credits that must be re-creditable),
and the "log and skip rather than crash boot" behaviour when production
already holds duplicates.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from backend.scripts.withdrawal_credit_duplicate_audit import audit
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0174_early_withdrawal_credit_unique_index"
INDEX_NAME = "early_withdrawal_credit_unique"

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _credit(
    credit_id: str,
    *,
    academy_id: str = "acad-1",
    enrollment_id: str | None = "enroll-1",
    type: str = "EARLY_WITHDRAWAL_CREDIT",
    status: str = "APPROVED",
    remaining_amount_cents: int = 2_667,
) -> dict:
    return {
        "academy_id": academy_id,
        "credit_id": credit_id,
        "parent_id": "parent-1",
        "student_id": "student-1",
        "enrollment_id": enrollment_id,
        "type": type,
        "status": status,
        "amount_cents": 2_667,
        "remaining_amount_cents": remaining_amount_cents,
        "currency": "usd",
        "reason": "Early withdrawal",
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.asyncio
async def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_creates_the_partial_unique_index(db, migration) -> None:
    await migration.up(db)

    index = (await db["account_credit_ledger"].index_information())[INDEX_NAME]
    assert index["key"] == [("academy_id", 1), ("enrollment_id", 1), ("type", 1)]
    assert index["unique"] is True
    assert index["partialFilterExpression"] == {
        "type": "EARLY_WITHDRAWAL_CREDIT",
        "status": "APPROVED",
    }


@pytest.mark.asyncio
async def test_rejects_a_second_approved_credit_for_one_enrollment(db, migration) -> None:
    await migration.up(db)
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))

    with pytest.raises(DuplicateKeyError):
        await db["account_credit_ledger"].insert_one(_credit("credit-2"))


@pytest.mark.asyncio
async def test_scopes_the_constraint_to_one_academy(db, migration) -> None:
    await migration.up(db)
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))

    await db["account_credit_ledger"].insert_one(_credit("credit-2", academy_id="acad-2"))

    assert await db["account_credit_ledger"].count_documents({}) == 2


@pytest.mark.asyncio
async def test_leaves_other_credit_types_and_voided_credits_unconstrained(db, migration) -> None:
    await migration.up(db)

    # Manual and overpayment credits legitimately repeat for one enrollment.
    await db["account_credit_ledger"].insert_one(_credit("manual-1", type="MANUAL_CREDIT"))
    await db["account_credit_ledger"].insert_one(_credit("manual-2", type="MANUAL_CREDIT"))
    # A voided withdrawal credit must not block re-crediting the enrollment.
    await db["account_credit_ledger"].insert_one(_credit("void-1", status="VOIDED"))
    await db["account_credit_ledger"].insert_one(_credit("void-2", status="VOIDED"))
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))

    assert await db["account_credit_ledger"].count_documents({}) == 5


@pytest.mark.asyncio
async def test_tolerates_preexisting_duplicates_instead_of_crashing_boot(db, migration) -> None:
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))
    await db["account_credit_ledger"].insert_one(_credit("credit-2"))

    await migration.up(db)

    assert INDEX_NAME not in await db["account_credit_ledger"].index_information()


@pytest.mark.asyncio
async def test_builds_the_index_in_the_background(migration) -> None:
    credits = MagicMock()
    credits.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=credits)

    await migration.up(db)

    kwargs = credits.create_index.await_args.kwargs
    assert kwargs["background"] is True
    assert kwargs["unique"] is True
    assert kwargs["name"] == INDEX_NAME


@pytest.mark.asyncio
async def test_duplicate_audit_reports_the_offending_enrollments(db) -> None:
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))
    await db["account_credit_ledger"].insert_one(_credit("credit-2", remaining_amount_cents=1_000))
    await db["account_credit_ledger"].insert_one(_credit("credit-3", enrollment_id="enroll-2"))
    await db["account_credit_ledger"].insert_one(_credit("manual-1", type="MANUAL_CREDIT"))
    await db["account_credit_ledger"].insert_one(_credit("void-1", status="VOIDED"))

    report = await audit(db)

    assert report["duplicate_group_count"] == 1
    assert report["scanned_approved_withdrawal_credits"] == 3
    assert report["surplus_remaining_cents"] == 1_000
    (group,) = report["duplicate_groups"]
    assert group["academy_id"] == "acad-1"
    assert group["enrollment_id"] == "enroll-1"
    assert [credit["credit_id"] for credit in group["credits"]] == ["credit-1", "credit-2"]


@pytest.mark.asyncio
async def test_duplicate_audit_is_clean_when_every_enrollment_has_one_credit(db) -> None:
    await db["account_credit_ledger"].insert_one(_credit("credit-1"))
    await db["account_credit_ledger"].insert_one(_credit("credit-2", enrollment_id="enroll-2"))
    await db["account_credit_ledger"].insert_one(_credit("credit-3", academy_id="acad-2"))

    report = await audit(db)

    assert report["duplicate_group_count"] == 0
    assert report["duplicate_groups"] == []
