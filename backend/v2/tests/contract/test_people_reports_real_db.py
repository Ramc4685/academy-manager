"""People reports (roadmap L5a) on a real ``mongod`` with every migration applied.

Money owed by age band is seeded through billing's own write paths where one
exists (a real partial payment allocation, a real credit application), with
the 0132 invoice validator in force, and checked against the family index
built from the same data (the parity acceptance test):

* a partially paid invoice counts only its remaining balance;
* an invoice priced net of an applied credit counts the net balance;
* void, waived and paid-then-refunded invoices are excluded;
* due dates 30 / 31 / 60 / 61 days ago and due today land in the right band;
* an invoice stored under the parent's alias lands in the family;
* another academy's invoices (even under the same parent id) never count.

Inquiry conversion counts ``crm_contacts`` by source and pipeline status over
academy-local days, window edges included/excluded, and never another academy.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.composition.families_crm import compose_admin_family_index
from backend.v2.contexts.billing.domain.ledger import LedgerPayment
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.crm.application.people_reports import (
    InquiryConversionReport,
    MoneyOwedByAge,
    MoneyOwedByAgeReport,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

ACAD = "acad-people-a"
OTHER = "acad-people-b"
#: 10:00 in Chicago: the academy's today is 2026-09-23.
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
TODAY = date(2026, 9, 23)
PARENT_A = "u-people-a"
ALIAS_A = "fb-people-a"
PARENT_B = "u-people-b"
PARENT_C = "u-people-c"


def _days_ago(days: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days), datetime.min.time(), tzinfo=UTC)


def _invoice(
    academy_id: str,
    invoice_id: str,
    total: int,
    *,
    parent_id: str,
    due: datetime,
    status: str = "open",
    subtotal: int | None = None,
    balance: int | None = None,
    refunded: int = 0,
) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "student_id": f"stu-{parent_id}",
        "period": "2026-09",
        "status": status,
        "subtotal_cents": subtotal if subtotal is not None else total,
        "discount_cents": 0,
        "total_cents": total,
        "balance_due_cents": balance if balance is not None else total,
        "refunded_cents": refunded,
        "currency": "usd",
        "due_date": due,
        "created_at": datetime(2026, 6, 1, 6, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, 6, 0, tzinfo=UTC),
    }


async def _seed_people(db: Any, academy_id: str, *, with_users: bool = True) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "display_name": "Test Academy", "timezone": "America/Chicago"}
    )
    if with_users:  # users are global (unique firebase_uid): seed them once
        await _seed_users(db, academy_id)
    await db["students"].insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": f"stu-{parent}",
                "parent_id": parent,
                "full_name": f"Testchild {i}",
                "status": "active",
            }
            for i, parent in enumerate((PARENT_A, PARENT_B, PARENT_C))
        ]
    )


async def _seed_users(db: Any, academy_id: str) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": PARENT_A,
                "firebase_uid": ALIAS_A,
                "academy_id": academy_id,
                "display_name": "Testparent Aging",
                "roles": ["parent"],
            },
            {
                "user_id": PARENT_B,
                "academy_id": academy_id,
                "display_name": "Testparent Credit",
                "roles": ["parent"],
            },
            {
                "user_id": PARENT_C,
                "academy_id": academy_id,
                "display_name": "Testparent Settled",
                "roles": ["parent"],
            },
        ]
    )


def _payment(payment_id: str, amount: int) -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id=ACAD,
        parent_id=PARENT_A,
        amount_cents=amount,
        unapplied_amount_cents=amount,
        status="succeeded",
        payment_method="card",
        paid_at=NOW - timedelta(days=3),
        currency="usd",
        created_at=NOW - timedelta(days=3),
        updated_at=NOW - timedelta(days=3),
    )


async def _seed_money(db: Any) -> None:
    await _seed_people(db, ACAD)
    # Family B's credit, applied the way invoice pricing applies it: the
    # invoice is written net of what the credit ledger says it consumed.
    credits = MongoCreditLedgerRepository(db)
    with tenant_scope(ACAD):
        await credits.create(
            CreditLedgerEntry(
                credit_id="credit-people-b",
                academy_id=ACAD,
                parent_id=PARENT_B,
                student_id=f"stu-{PARENT_B}",
                enrollment_id="enr-people-b",
                type="MANUAL_CREDIT",
                status="APPROVED",
                amount_cents=3_000,
                remaining_amount_cents=3_000,
                currency="usd",
                reason="goodwill",
                calculation_snapshot_id="snap-people-b",
                expires_at=datetime(2027, 9, 1, tzinfo=UTC),
                created_at=NOW - timedelta(days=40),
                updated_at=NOW - timedelta(days=40),
            )
        )
        applied = await credits.apply_available_credits(
            parent_id=PARENT_B, invoice_id="inv-b-31", amount_due_cents=8_000
        )
    assert applied == 3_000

    await db["invoices"].insert_many(
        [
            # Family A: 30 days late, partly paid below.
            _invoice(ACAD, "inv-a-30", 6_000, parent_id=PARENT_A, due=_days_ago(30)),
            # Family A, stored under the alias: 61 days late.
            _invoice(ACAD, "inv-a-61", 4_000, parent_id=ALIAS_A, due=_days_ago(61)),
            # Family A: voided, long overdue. Never counted.
            _invoice(
                ACAD, "inv-a-void", 9_000, parent_id=PARENT_A, due=_days_ago(90), status="void"
            ),
            # Family A: not due yet.
            _invoice(ACAD, "inv-a-future", 5_000, parent_id=PARENT_A, due=_days_ago(-12)),
            # Family B: 31 days late, priced net of the 3,000 credit.
            _invoice(
                ACAD,
                "inv-b-31",
                8_000 - applied,
                parent_id=PARENT_B,
                due=_days_ago(31),
                subtotal=8_000,
            ),
            # Family B: exactly 60 days late (still the 31-60 band).
            _invoice(ACAD, "inv-b-60", 2_000, parent_id=PARENT_B, due=_days_ago(60)),
            # Family B: due today is not late.
            _invoice(ACAD, "inv-b-today", 1_000, parent_id=PARENT_B, due=_days_ago(0)),
            # Family B: waived, and paid-then-refunded. Neither counts.
            _invoice(
                ACAD, "inv-b-waived", 7_000, parent_id=PARENT_B, due=_days_ago(70), status="waived"
            ),
            _invoice(
                ACAD,
                "inv-b-refunded",
                3_000,
                parent_id=PARENT_B,
                due=_days_ago(80),
                status="paid",
                balance=0,
                refunded=3_000,
            ),
            # Family C: settled.
            _invoice(
                ACAD,
                "inv-c-paid",
                2_500,
                parent_id=PARENT_C,
                due=_days_ago(45),
                status="paid",
                balance=0,
            ),
            # Another academy, SAME parent id as family A: never counted here.
            _invoice(OTHER, "inv-other-a", 99_999, parent_id=PARENT_A, due=_days_ago(75)),
        ]
    )
    ledger = MongoBillingLedgerRepository(db)
    with tenant_scope(ACAD):
        await ledger.record_payment(_payment("pay-people-a", 2_500), idempotency_key="pay-people-a")
        await ledger.allocate_payment(
            payment_id="pay-people-a",
            invoice_id="inv-a-30",
            amount_cents=2_500,
            idempotency_key="alloc-people-a",
        )
    partial = await db["invoices"].find_one({"academy_id": ACAD, "invoice_id": "inv-a-30"})
    assert partial is not None
    assert (partial["status"], partial["balance_due_cents"]) == ("partially_paid", 3_500)


def _index_model(db: Any) -> MongoFamilyIndexReadModel:
    return MongoFamilyIndexReadModel(
        db,
        parents=MongoUserRepository(db),
        children=MongoStudentRepository(db),
        money=MongoFamilyMoneyReadModel(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )


def _money_report(db: Any) -> MoneyOwedByAgeReport:
    return MoneyOwedByAgeReport(
        index=_index_model(db), money=MongoFamilyMoneyReadModel(db), clock=lambda: NOW
    )


def _bands(report: MoneyOwedByAge) -> dict[str, tuple[int, int]]:
    rows = [report.not_yet_due, *report.bands]
    return {row.key: (row.family_count, row.total_cents) for row in rows}


# ------------------------------------------------------------ money owed by age


async def test_bands_count_only_open_balances_on_the_right_side_of_each_boundary(real_db) -> None:
    await _seed_money(real_db)
    with tenant_scope(ACAD):
        report = await _money_report(real_db).run(ACAD)

    assert report.as_of == TODAY
    assert _bands(report) == {
        # inv-a-future 5,000 + inv-b-today 1,000.
        "not_yet_due": (2, 6_000),
        # inv-a-30: day 30 is the first band; 6,000 less the 2,500 paid.
        "days_1_30": (1, 3_500),
        # inv-b-31 (net of the credit) + inv-b-60 (day 60 is still this band).
        "days_31_60": (1, 5_000 + 2_000),
        # inv-a-61, stored under family A's alias.
        "days_over_60": (1, 4_000),
    }
    assert report.overdue_cents == 3_500 + 7_000 + 4_000
    assert report.overdue_family_count == 2
    assert report.balance_cents == 6_000 + 3_500 + 7_000 + 4_000
    assert report.owing_family_count == 2


async def test_totals_equal_the_family_index_for_the_same_data(real_db) -> None:
    """Parity: the report and the Families view agree to the cent."""
    await _seed_money(real_db)
    with tenant_scope(ACAD):
        report = await _money_report(real_db).run(ACAD)
        index = await _index_model(real_db).build(ACAD)

    money = [f.money for f in index.families if f.money is not None]
    assert len(money) == len(index.families) == 3
    assert report.overdue_cents == sum(m.overdue_cents for m in money)
    assert sum(b.total_cents for b in report.bands) == report.overdue_cents
    assert report.balance_cents == sum(m.balance_cents for m in money)
    assert report.not_yet_due.total_cents + report.overdue_cents == report.balance_cents
    assert report.overdue_family_count == sum(1 for m in money if m.overdue_cents > 0)
    assert report.owing_family_count == sum(1 for m in money if m.balance_cents > 0)


async def test_another_academys_invoices_never_count(real_db) -> None:
    await _seed_money(real_db)
    # The other academy: its own family (same parent id as ACAD's family A).
    await _seed_people(real_db, OTHER, with_users=False)
    with tenant_scope(OTHER):
        other = await _money_report(real_db).run(OTHER)
    with tenant_scope(ACAD):
        mine = await _money_report(real_db).run(ACAD)

    assert _bands(other)["days_over_60"] == (1, 99_999)
    assert other.balance_cents == 99_999
    assert mine.balance_cents == 20_500
    assert 99_999 not in {b.total_cents for b in mine.bands}


async def test_composed_services_serve_the_report(real_db) -> None:
    """The wiring main.py attaches (``admin_family_index.reports``) runs end to end."""
    await _seed_money(real_db)
    services = compose_admin_family_index(real_db)
    with tenant_scope(ACAD):
        report = await services.reports.money_owed_by_age.run(ACAD)
    # Real clock: only the grand total is date-independent.
    assert report.balance_cents == 20_500


# ------------------------------------------------------------ inquiry conversion


def _contact(
    academy_id: str, contact_id: str, source: str, status: str, created_at: datetime
) -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=academy_id,
        name=f"Testinquirer {contact_id}",
        email=f"{contact_id}@example.test",
        source=source,  # type: ignore[arg-type]
        pipeline_status=status,  # type: ignore[arg-type]
        dedupe_key=f"key-{contact_id}" if source == "website" else None,
        created_at=created_at,
        updated_at=created_at,
    )


async def _seed_contacts(db: Any) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": ACAD, "display_name": "Test A", "timezone": "America/Chicago"},
            {"academy_id": OTHER, "display_name": "Test B", "timezone": "America/Chicago"},
        ]
    )
    repo = MongoCrmContactRepository(db)
    # Window 2026-09-01..2026-09-10 in Chicago (CDT, UTC-5):
    # [2026-09-01T05:00Z, 2026-09-11T05:00Z).
    mine = [
        ("c-web-first", "website", "lead", datetime(2026, 9, 1, 5, 0, tzinfo=UTC)),
        ("c-web-trial", "website", "trial", datetime(2026, 9, 5, 12, 0, tzinfo=UTC)),
        ("c-web-last", "website", "enrolled", datetime(2026, 9, 11, 4, 59, tzinfo=UTC)),
        ("c-web-before", "website", "lead", datetime(2026, 9, 1, 4, 59, tzinfo=UTC)),
        ("c-web-after", "website", "enrolled", datetime(2026, 9, 11, 5, 0, tzinfo=UTC)),
        ("c-ref-enrolled", "referral", "enrolled", datetime(2026, 9, 3, 12, 0, tzinfo=UTC)),
        ("c-ref-lead", "referral", "lead", datetime(2026, 9, 4, 12, 0, tzinfo=UTC)),
        ("c-phone-trial", "whatsapp_or_phone", "trial", datetime(2026, 9, 6, 12, 0, tzinfo=UTC)),
    ]
    with tenant_scope(ACAD):
        for contact_id, source, status, at in mine:
            _, created = await repo.add_if_absent(_contact(ACAD, contact_id, source, status, at))
            assert created
    with tenant_scope(OTHER):
        for contact_id, source, status in (
            ("o-web", "website", "enrolled"),
            ("o-ref", "referral", "enrolled"),
        ):
            await repo.add_if_absent(
                _contact(OTHER, contact_id, source, status, datetime(2026, 9, 5, tzinfo=UTC))
            )


def _inquiry_report(db: Any) -> InquiryConversionReport:
    return InquiryConversionReport(
        contacts=MongoCrmContactRepository(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )


async def test_conversion_counts_per_source_over_academy_local_days(real_db) -> None:
    await _seed_contacts(real_db)
    with tenant_scope(ACAD):
        report = await _inquiry_report(real_db).run(
            ACAD, date_from=date(2026, 9, 1), date_to=date(2026, 9, 10)
        )

    assert report.timezone == "America/Chicago"
    rows = {
        r.source: (r.inquiries, r.lead, r.trial, r.enrolled, r.conversion_rate)
        for r in report.sources
    }
    assert rows == {
        "website": (3, 1, 1, 1, 1 / 3),
        "whatsapp_or_phone": (1, 0, 1, 0, 0.0),
        "referral": (2, 1, 0, 1, 0.5),
        "other": (0, 0, 0, 0, None),
    }
    assert [r.source for r in report.sources] == [
        "website",
        "whatsapp_or_phone",
        "referral",
        "other",
    ]
    total = report.total
    assert (total.inquiries, total.lead, total.trial, total.enrolled) == (6, 2, 2, 2)
    assert total.conversion_rate == 2 / 6


async def test_conversion_defaults_to_the_last_90_days_and_is_tenant_scoped(real_db) -> None:
    await _seed_contacts(real_db)
    repo = MongoCrmContactRepository(real_db)
    with tenant_scope(ACAD):
        # 2026-06-26 is the first day of the default window ending 2026-09-23.
        await repo.add_if_absent(
            _contact(ACAD, "c-old", "other", "lead", datetime(2026, 6, 26, 4, 59, tzinfo=UTC))
        )
        await repo.add_if_absent(
            _contact(ACAD, "c-edge", "other", "lead", datetime(2026, 6, 26, 5, 0, tzinfo=UTC))
        )
        report = await _inquiry_report(real_db).run(ACAD)
    with tenant_scope(OTHER):
        other = await _inquiry_report(real_db).run(OTHER)

    assert (report.date_from, report.date_to) == (date(2026, 6, 26), TODAY)
    # All 8 of this academy's September contacts, plus c-edge (c-old is June 25 local).
    assert report.total.inquiries == 8 + 1
    assert next(r for r in report.sources if r.source == "other").inquiries == 1
    assert other.total.inquiries == 2
    assert other.total.enrolled == 2
