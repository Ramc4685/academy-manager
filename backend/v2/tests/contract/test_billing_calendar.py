"""L8 billing calendar against a real mongod: autopay on the 1st, due on the 5th
from 2027-01-01, December on today's schedule.

Money paths, so ``real_db`` throughout (mongomock evaluates neither partial
indexes nor plans).
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime

import pytest

from backend.v2.composition.overdue_families import OverdueFamiliesReader
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.tests.contract.test_mongo_payment_repo import _seed_monthly_enrollment

_M0230 = importlib.import_module("backend.v2.migrations.0230_autopay_charge_date_index")
_M0231 = importlib.import_module("backend.v2.migrations.0231_blno_billing_calendar")

JAN_CHANGE = {
    "effective_from": date(2027, 1, 1),
    "invoice_due_days": 4,
    "autopay_charge_offset_days": 0,
    "reminder_days": (0, 3, 7),
}


def _day(value: object) -> date | None:
    return value.date() if isinstance(value, datetime) else None  # type: ignore[return-value]


# --- settings: dated change round trip ------------------------------------------


@pytest.mark.asyncio
async def test_schedule_change_round_trips_and_promotes_on_its_day(real_db, acad) -> None:
    repo = MongoBillingSettingsRepository(real_db)
    await repo.upsert(BillingSettings(academy_id=acad, schedule_change=JAN_CHANGE))

    stored = await real_db["billing_settings"].find_one({"academy_id": acad})
    assert stored["schedule_change"]["effective_from"] == datetime(2027, 1, 1)
    assert stored["invoice_due_days"] == 7

    dec31 = await repo.get(on=date(2026, 12, 31))
    assert (dec31.invoice_due_days, dec31.reminder_days) == (7, (15, 20))
    assert dec31.schedule_change is not None

    jan1 = await repo.get(on=date(2027, 1, 1))
    assert (jan1.invoice_due_days, jan1.autopay_charge_offset_days) == (4, 0)
    assert jan1.reminder_days == (0, 3, 7)

    await repo.upsert(jan1)  # the next settings write persists the promoted values
    stored = await real_db["billing_settings"].find_one({"academy_id": acad})
    assert (stored["invoice_due_days"], stored["schedule_change"]) == (4, None)
    assert (await repo.get(on=date(2026, 12, 1))).invoice_due_days == 4


# --- migrations -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_0231_schedules_blno_only_and_is_idempotent(real_db) -> None:
    await real_db["academies"].insert_many(
        [
            {"academy_id": "acad_blno_badminton", "display_name": "BLNO"},
            {"academy_id": "acad_other", "display_name": "Other"},
        ]
    )
    await real_db["billing_settings"].insert_many(
        [
            {"academy_id": "acad_blno_badminton", "invoice_due_days": 7, "billing_day": 1},
            {"academy_id": "acad_other", "invoice_due_days": 10},
        ]
    )

    await _M0231.up(real_db)
    await _M0231.up(real_db)

    blno = await real_db["billing_settings"].find_one({"academy_id": "acad_blno_badminton"})
    assert blno["invoice_due_days"] == 7  # base untouched: December runs as today
    assert blno["schedule_change"] == {
        "effective_from": datetime(2027, 1, 1),
        "invoice_due_days": 4,
        "autopay_charge_offset_days": 0,
        "reminder_days": [0, 3, 7],
    }
    other = await real_db["billing_settings"].find_one({"academy_id": "acad_other"})
    assert "schedule_change" not in other
    assert await real_db["billing_settings"].count_documents({}) == 2


@pytest.mark.asyncio
async def test_0231_creates_blno_settings_when_missing_and_skips_an_empty_db(real_db) -> None:
    await _M0231.up(real_db)
    assert await real_db["billing_settings"].count_documents({}) == 0

    await real_db["academies"].insert_one(
        {"academy_id": "acad_blno_badminton", "display_name": "BLNO"}
    )
    await _M0231.up(real_db)
    doc = await real_db["billing_settings"].find_one({"academy_id": "acad_blno_badminton"})
    assert doc["schedule_change"]["invoice_due_days"] == 4


@pytest.mark.asyncio
async def test_stamped_ladder_query_uses_the_0230_index(real_db, acad) -> None:
    await _M0230.up(real_db)  # re-run is a no-op
    cutoff = datetime(2027, 1, 1, 23, 59)
    plan = await (
        real_db["invoices"]
        .find(
            {
                "academy_id": acad,
                "status": {"$in": ["open", "partially_paid"]},
                "balance_due_cents": {"$gt": 0},
                "enrollment_id": {"$exists": True, "$ne": None},
                "autopay_charge_date": {"$gt": datetime(1970, 1, 1), "$lte": cutoff},
            }
        )
        .sort([("autopay_charge_date", 1), ("invoice_id", 1)])
        .explain()
    )
    assert "academy_invoice_status_autopay_charge_date" in str(plan["queryPlanner"]["winningPlan"])


# --- generation -----------------------------------------------------------------


async def _generate(real_db, acad: str, *, at: datetime, period: str, enrollment: str) -> dict:
    await _seed_monthly_enrollment(
        real_db,
        acad,
        enrollment_id=enrollment,
        session_id=f"sess-{enrollment}",
        student_id=f"student-{enrollment}",
        parent_id=f"parent-{enrollment}",
    )
    await real_db["sessions"].update_one(
        {"session_id": f"sess-{enrollment}"},
        {"$set": {"start_date": "2026-12-01", "end_date": "2027-02-28"}},
    )
    repo = MongoPaymentRepository(
        real_db, clock=lambda: at, ledger_repo=MongoBillingLedgerRepository(real_db)
    )
    assert (await repo.generate_monthly_payments(period)).created >= 1
    invoice = await real_db["invoices"].find_one({"enrollment_id": enrollment, "period": period})
    assert invoice is not None
    return invoice


@pytest.mark.asyncio
async def test_december_generates_on_todays_schedule_and_january_on_the_new_one(
    real_db, acad
) -> None:
    await MongoBillingSettingsRepository(real_db).upsert(
        BillingSettings(academy_id=acad, schedule_change=JAN_CHANGE)
    )

    dec = await _generate(
        real_db,
        acad,
        at=datetime(2026, 12, 1, 9, 0, tzinfo=UTC),
        period="2026-12",
        enrollment="e-dec",
    )
    assert _day(dec["due_date"]) == date(2026, 12, 8)
    assert dec["autopay_charge_date"] is None

    jan = await _generate(
        real_db,
        acad,
        at=datetime(2027, 1, 1, 9, 0, tzinfo=UTC),
        period="2027-01",
        enrollment="e-jan",
    )
    assert _day(jan["due_date"]) == date(2027, 1, 5)
    assert _day(jan["autopay_charge_date"]) == date(2027, 1, 1)


# --- the ladder -----------------------------------------------------------------


async def _autopay_invoice(
    real_db, acad: str, invoice_id: str, *, due: date, charge: date | None
) -> None:
    await real_db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": invoice_id,
            "parent_id": f"parent-{invoice_id}",
            "enrollment_id": f"enr-{invoice_id}",
            "period": "2027-01",
            "status": "open",
            "subtotal_cents": 10_000,
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "currency": "usd",
            "due_date": datetime.combine(due, datetime.min.time(), tzinfo=UTC),
            "autopay_charge_date": (
                datetime.combine(charge, datetime.min.time(), tzinfo=UTC) if charge else None
            ),
            "created_at": datetime(2027, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2027, 1, 1, tzinfo=UTC),
        }
    )
    await real_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": f"enr-{invoice_id}",
            "student_id": f"student-{invoice_id}",
            "parent_id": f"parent-{invoice_id}",
            "session_type_id": "st-1",
            "autopay_enrollment_status": "active",
        }
    )


@pytest.mark.asyncio
async def test_stamped_invoice_ladder_opens_on_the_charge_day_unstamped_on_the_due_day(
    real_db, acad
) -> None:
    repo = MongoDunningStateRepository(real_db)
    await _autopay_invoice(
        real_db, acad, "inv-stamped", due=date(2027, 1, 5), charge=date(2027, 1, 1)
    )
    await _autopay_invoice(real_db, acad, "inv-plain", due=date(2027, 1, 5), charge=None)

    assert await repo.prepare_due_states(now=datetime(2027, 1, 1, 8, 0, tzinfo=UTC), limit=10) == 0
    assert await repo.prepare_due_states(now=datetime(2027, 1, 1, 10, 0, tzinfo=UTC), limit=10) == 1
    assert await real_db["dunning_states"].find_one({"invoice_id": "inv-stamped"}) is not None
    assert await real_db["dunning_states"].find_one({"invoice_id": "inv-plain"}) is None

    assert await repo.prepare_due_states(now=datetime(2027, 1, 4, 10, 0, tzinfo=UTC), limit=10) == 0
    assert await repo.prepare_due_states(now=datetime(2027, 1, 5, 10, 0, tzinfo=UTC), limit=10) == 1
    assert await real_db["dunning_states"].find_one({"invoice_id": "inv-plain"}) is not None


# --- overdue --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_past_due_starts_the_day_after_the_due_date_and_drafts_never_count(
    real_db, acad
) -> None:
    for invoice_id, parent, status in (
        ("inv-manual", "parent-manual", "open"),
        ("inv-draft", "parent-draft", "draft"),
    ):
        await real_db["invoices"].insert_one(
            {
                "academy_id": acad,
                "invoice_id": invoice_id,
                "parent_id": parent,
                "period": "2027-01",
                "status": status,
                "total_cents": 10_000,
                "balance_due_cents": 10_000,
                "currency": "usd",
                "due_date": datetime(2027, 1, 5, tzinfo=UTC),
                "created_at": datetime(2027, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2027, 1, 1, tzinfo=UTC),
            }
        )

    async def _utc(_: str) -> str:
        return "UTC"

    def reader(day: int) -> OverdueFamiliesReader:
        return OverdueFamiliesReader(
            real_db,
            academy_timezone=_utc,
            clock=lambda: datetime(2027, 1, day, 12, 0, tzinfo=UTC),
        )

    assert (await reader(5).counts())["past_due"] == 0
    assert (await reader(6).counts())["past_due"] == 1


@pytest.mark.asyncio
async def test_unreadable_settings_fall_back_and_page_ops(real_db, acad, monkeypatch) -> None:
    """Review fix: generation must not block on unreadable settings, but a silent
    default on the 1st would date a month of invoices wrong, so it pages."""
    from backend.v2.contexts.billing.infrastructure import mongo_monthly_billing

    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mongo_monthly_billing,
        "capture_message",
        lambda message, level="info", **_: alerts.append((level, message)),
    )

    async def _boom(self, *, on=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("settings read failed")

    monkeypatch.setattr(MongoBillingSettingsRepository, "get", _boom)
    generator = mongo_monthly_billing.MongoMonthlyBillingGenerator(
        MongoPaymentRepository(real_db, clock=lambda: datetime(2027, 1, 1, 9, tzinfo=UTC))
    )

    assert await generator._load_schedule(date(2027, 1, 1)) == (7, None)
    assert [level for level, _ in alerts] == ["error"]
