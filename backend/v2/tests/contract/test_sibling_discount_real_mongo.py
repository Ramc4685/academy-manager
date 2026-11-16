"""Automatic sibling discount on a real ``mongod`` (L9 C1, migration 0237).

The real monthly generator, ledger, settings and decision store with the
production indexes. The family is parent-1: Ava (``stu-a``) and Ben
(``stu-b``), billed for 2026-09 long after they started, so no proration.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    _discount_base_subtotal_cents,
)
from backend.v2.contexts.billing.domain.billing_settings import SiblingDiscount
from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    MongoMonthlyBillingGenerator,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

PERIOD = "2026-09"
NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _clock() -> datetime:
    return NOW


def _repo(db: Any) -> MongoPaymentRepository:
    return MongoPaymentRepository(
        db, clock=_clock, ledger_repo=MongoBillingLedgerRepository(db, clock=_clock)
    )


async def _session(db: Any, acad: str, session_id: str, fee: int) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": session_id,
            "name": session_id,
            "title": session_id,
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon"],
            "start_time": "18:00",
            "end_time": "19:00",
            "monthly_price_cents": fee,
            "capacity": 8,
            "status": "active",
        }
    )


async def _child(db: Any, acad: str, student_id: str, parent_id: str = "parent-1") -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": student_id,
            "parent_id": parent_id,
            "full_name": student_id,
        }
    )


async def _enroll(
    db: Any,
    acad: str,
    enrollment_id: str,
    student_id: str,
    session_id: str,
    *,
    started: datetime = datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
    status: str = "active",
    parent_id: str = "parent-1",
) -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "student_id": student_id,
            "parent_id": parent_id,
            "status": status,
            "billing_type": "standard",
            "billing_start_at": started,
            "created_at": started,
        }
    )


async def _family(db: Any, acad: str) -> None:
    """Ava: one 120.00 class. Ben: one 80.00 class, enrolled first."""
    await _session(db, acad, "sess-hi", 12_000)
    await _session(db, acad, "sess-lo", 8_000)
    await _child(db, acad, "stu-a")
    await _child(db, acad, "stu-b")
    await _enroll(db, acad, "enr-a", "stu-a", "sess-hi")
    await _enroll(
        db, acad, "enr-b", "stu-b", "sess-lo", started=datetime(2025, 6, 1, 15, 0, tzinfo=UTC)
    )


async def _offer(db: Any, **overrides: Any) -> None:
    values = {
        "enabled": True,
        "percent_bps": 1_000,
        "full_price_child": "highest_tuition",
        "applies_to": "all_classes",
        **overrides,
    }
    await MongoBillingSettingsRepository(db).set_family_offers(
        sibling_discount=SiblingDiscount(**values)
    )


async def _invoice(db: Any, acad: str, enrollment_id: str) -> dict[str, Any]:
    doc = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": f"inv-monthly-{enrollment_id}-{PERIOD}"}
    )
    assert doc is not None, enrollment_id
    return doc


async def _discount(db: Any, acad: str, enrollment_id: str) -> int:
    return int((await _invoice(db, acad, enrollment_id))["discount_cents"])


async def _discounts(db: Any, acad: str, *enrollment_ids: str) -> dict[str, int]:
    return {eid: await _discount(db, acad, eid) for eid in enrollment_ids}


async def _lines(db: Any, acad: str, enrollment_id: str) -> list[dict[str, Any]]:
    return [
        doc
        async for doc in db["invoice_lines"].find(
            {"academy_id": acad, "invoice_id": f"inv-monthly-{enrollment_id}-{PERIOD}"},
            {"_id": 0},
            sort=[("line_id", 1)],
        )
    ]


# --- the rule ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("full_price_child", "expected"),
    [
        ("highest_tuition", {"enr-a": 0, "enr-b": 800}),
        ("lowest_tuition", {"enr-a": 1_200, "enr-b": 0}),
        ("first_enrolled", {"enr-a": 1_200, "enr-b": 0}),
    ],
)
async def test_full_price_child_choice(
    real_db, acad, full_price_child: str, expected: dict[str, int]
) -> None:
    await _family(real_db, acad)
    await _offer(real_db, full_price_child=full_price_child)

    result = await _repo(real_db).generate_monthly_payments(PERIOD)

    assert result.created == 2
    assert await _discounts(real_db, acad, "enr-a", "enr-b") == expected


@pytest.mark.parametrize(
    ("applies_to", "expected"),
    [
        ("all_classes", {"enr-a": 0, "enr-b": 800, "enr-b2": 500}),
        ("one_class_per_child", {"enr-a": 0, "enr-b": 800, "enr-b2": 0}),
    ],
)
async def test_applies_to_choice(real_db, acad, applies_to: str, expected: dict[str, int]) -> None:
    # Ava 150.00 stays the highest even against Ben's 80.00 + 50.00.
    await _session(real_db, acad, "sess-top", 15_000)
    await _session(real_db, acad, "sess-lo", 8_000)
    await _session(real_db, acad, "sess-mini", 5_000)
    await _child(real_db, acad, "stu-a")
    await _child(real_db, acad, "stu-b")
    await _enroll(real_db, acad, "enr-a", "stu-a", "sess-top")
    await _enroll(real_db, acad, "enr-b", "stu-b", "sess-lo")
    await _enroll(real_db, acad, "enr-b2", "stu-b", "sess-mini")
    await _offer(real_db, applies_to=applies_to)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _discounts(real_db, acad, "enr-a", "enr-b", "enr-b2") == expected


async def test_an_only_child_gets_no_sibling_discount(real_db, acad) -> None:
    await _session(real_db, acad, "sess-lo", 8_000)
    await _child(real_db, acad, "stu-b")
    await _enroll(real_db, acad, "enr-b", "stu-b", "sess-lo")
    await _offer(real_db)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _discount(real_db, acad, "enr-b") == 0


@pytest.mark.parametrize("status", ["held", "paused"])
async def test_a_held_or_paused_child_does_not_count(real_db, acad, status: str) -> None:
    await _session(real_db, acad, "sess-hi", 12_000)
    await _session(real_db, acad, "sess-lo", 8_000)
    await _child(real_db, acad, "stu-a")
    await _child(real_db, acad, "stu-b")
    await _enroll(real_db, acad, "enr-a", "stu-a", "sess-hi", status=status)
    await _enroll(real_db, acad, "enr-b", "stu-b", "sess-lo")
    await _offer(real_db)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _discount(real_db, acad, "enr-b") == 0
    decision = await real_db["sibling_discount_decisions"].find_one({"enrollment_id": "enr-b"})
    assert decision is not None and decision["discounted"] is False
    assert decision["family_enrollment_ids"] == ["enr-b"]


# --- best of the manual policy and the sibling one ------------------------------


async def _manual(db: Any, *, percent_bps: int) -> None:
    await MongoTuitionDiscountRepository(db, clock=_clock).set_active(
        TuitionDiscount(
            discount_id="disc-manual",
            enrollment_id="enr-b",
            student_id="stu-b",
            category="scholarship",
            kind="percent",
            percent_bps=percent_bps,
            effective_start="2026-01-01",
        ),
        set_by="owner-1",
    )


@pytest.mark.parametrize(
    ("manual_bps", "discount", "source_id"),
    [
        (500, 800, f"sibling-auto-{PERIOD}"),  # sibling 10% beats manual 5%
        (2_000, 1_600, "disc-manual"),  # manual 20% beats sibling 10%
        (1_000, 800, "disc-manual"),  # a tie goes to the manual policy
    ],
)
async def test_the_larger_discount_wins_and_they_never_stack(
    real_db, acad, manual_bps: int, discount: int, source_id: str
) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    await _manual(real_db, percent_bps=manual_bps)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    invoice = await _invoice(real_db, acad, "enr-b")
    assert invoice["discount_cents"] == discount
    assert invoice["total_cents"] == 8_000 - discount
    discount_lines = [
        line for line in await _lines(real_db, acad, "enr-b") if line["line_type"] == "discount"
    ]
    assert [(line["source_id"], line["amount_cents"]) for line in discount_lines] == [
        (source_id, -discount)
    ]


async def test_the_sibling_line_is_the_tuition_discount_line_payroll_nets(real_db, acad) -> None:
    """Payroll (L7) pays on tuition minus ``tuition_discount`` lines; the sibling
    discount must be written as exactly that line type, not a new one."""
    await _family(real_db, acad)
    await _offer(real_db)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    (line,) = [line for line in await _lines(real_db, acad, "enr-b") if line["amount_cents"] < 0]
    assert line["line_type"] == "discount"
    assert line["source_type"] == "tuition_discount"
    assert line["category"] == "sibling"
    assert line["discount_kind"] == "percent"
    assert line["description"] == "Sibling discount"
    assert line["amount_cents"] == -800


async def test_the_ach_base_nets_the_sibling_line(real_db, acad) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    await _repo(real_db).generate_monthly_payments(PERIOD)

    ledger = MongoBillingLedgerRepository(real_db)
    invoice = await ledger.get_invoice(f"inv-monthly-enr-b-{PERIOD}")
    assert invoice is not None
    lines = await ledger.get_lines_for_invoice(invoice.invoice_id)

    assert _discount_base_subtotal_cents(invoice, lines, None) == 7_200


# --- stability ----------------------------------------------------------------


async def test_switched_off_writes_no_decision_rows(real_db, acad) -> None:
    await _family(real_db, acad)

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await real_db["sibling_discount_decisions"].count_documents({}) == 0
    assert await _discounts(real_db, acad, "enr-a", "enr-b") == {"enr-a": 0, "enr-b": 0}


async def test_a_setting_change_leaves_an_existing_invoice_byte_identical(real_db, acad) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    await _repo(real_db).generate_monthly_payments(PERIOD)
    before = {
        eid: (await _invoice(real_db, acad, eid), await _lines(real_db, acad, eid))
        for eid in ("enr-a", "enr-b")
    }

    await _offer(real_db, percent_bps=2_500, full_price_child="lowest_tuition")
    again = await _repo(real_db).generate_monthly_payments(PERIOD)

    assert again.created == 0
    after = {
        eid: (await _invoice(real_db, acad, eid), await _lines(real_db, acad, eid))
        for eid in ("enr-a", "enr-b")
    }
    assert after == before


async def test_switching_on_after_invoicing_never_reprices_the_month(real_db, acad) -> None:
    await _family(real_db, acad)
    await _repo(real_db).generate_monthly_payments(PERIOD)  # offer off
    before = await _invoice(real_db, acad, "enr-b")

    await _offer(real_db)
    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _invoice(real_db, acad, "enr-b") == before
    assert await real_db["sibling_discount_decisions"].count_documents({}) == 0


async def test_the_decision_is_frozen_across_orphan_recovery_after_a_sibling_drops(
    real_db, acad, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    real_write = MongoMonthlyBillingGenerator._dual_write_ledger_invoice

    async def _crash_on_ben(self: Any, **kwargs: Any) -> None:
        if kwargs["enrollment_id"] == "enr-b":
            raise RuntimeError("process died after claiming the key")
        await real_write(self, **kwargs)

    monkeypatch.setattr(MongoMonthlyBillingGenerator, "_dual_write_ledger_invoice", _crash_on_ben)
    with pytest.raises(RuntimeError):
        await _repo(real_db).generate_monthly_payments(PERIOD)
    monkeypatch.setattr(MongoMonthlyBillingGenerator, "_dual_write_ledger_invoice", real_write)
    assert await real_db["invoices"].find_one({"invoice_id": f"inv-monthly-enr-b-{PERIOD}"}) is None

    # Ava leaves and the owner even switches the offer off before the retry.
    await real_db["enrollments"].update_one(
        {"enrollment_id": "enr-a"}, {"$set": {"status": "dropped"}}
    )
    await _offer(real_db, enabled=False)
    result = await _repo(real_db).generate_monthly_payments(PERIOD)

    assert result.repaired_orphan_keys == 1
    assert await _discount(real_db, acad, "enr-b") == 800
    # Ben's decision from the crashed run; Ava (dropped, offer off) never got one.
    decisions = [d["enrollment_id"] async for d in real_db["sibling_discount_decisions"].find({})]
    assert decisions == ["enr-b"]


async def test_the_family_charge_key_is_unchanged_across_a_retry(real_db, acad) -> None:
    """The family autopay key is a digest of the member invoice ids plus the summed
    balance (``charge_invoice_via_autopay``); a re-run after the family or the
    setting changed must not move either."""
    await _family(real_db, acad)
    await _offer(real_db)

    async def _key() -> str:
        members = [await _invoice(real_db, acad, eid) for eid in ("enr-a", "enr-b")]
        rungs = "|".join(sorted(f"{m['invoice_id']}:" for m in members))
        digest = hashlib.sha256(rungs.encode()).hexdigest()[:32]
        return f"autopay-family:{digest}:{sum(m['balance_due_cents'] for m in members)}"

    await _repo(real_db).generate_monthly_payments(PERIOD)
    first = await _key()
    await real_db["enrollments"].update_one(
        {"enrollment_id": "enr-a"}, {"$set": {"status": "dropped"}}
    )
    await _offer(real_db, percent_bps=5_000)
    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _key() == first
    assert first.endswith(":19200")


async def test_a_concurrent_decision_is_reread_not_duplicated(real_db, acad) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    # Another run decided Ben's month first (with a different percent).
    await real_db["sibling_discount_decisions"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-b",
            "period": PERIOD,
            "discounted": True,
            "percent_bps": 1_500,
        }
    )

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _discount(real_db, acad, "enr-b") == 1_200
    assert (
        await real_db["sibling_discount_decisions"].count_documents({"enrollment_id": "enr-b"}) == 1
    )


# --- tenancy ------------------------------------------------------------------


async def test_a_second_academy_is_isolated(real_db, acad) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    with tenant_scope("academy-two"):
        # Same ids, same parent id; the offer stays off here.
        await _family(real_db, "academy-two")
        await _repo(real_db).generate_monthly_payments(PERIOD)
        assert await _discounts(real_db, "academy-two", "enr-a", "enr-b") == {
            "enr-a": 0,
            "enr-b": 0,
        }
    assert await real_db["sibling_discount_decisions"].count_documents({}) == 0

    await _repo(real_db).generate_monthly_payments(PERIOD)

    assert await _discounts(real_db, acad, "enr-a", "enr-b") == {"enr-a": 0, "enr-b": 800}
    assert (
        await real_db["sibling_discount_decisions"].count_documents({"academy_id": "academy-two"})
        == 0
    )
