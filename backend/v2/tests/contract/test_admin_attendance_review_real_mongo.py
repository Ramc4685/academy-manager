"""Admin attendance review reads only the requesting academy (real mongod).

PR #1226 fixed class-date rows that counted the boot academy's marks. This
query is new, so it gets the same proof: production composition root booted as
academy A, every read made inside academy B's tenant scope, with colliding
occurrence ids so a cross-tenant read shows up as a wrong answer, not a zero.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

BOOT = "acad-boot-a"
DEMO = "acad-demo-b"
SESSION = "sess-juniors"
NOW = datetime.now(UTC)
THREE_DAYS_AGO = NOW - timedelta(days=3)


@pytest.fixture
def booted_as_a(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", BOOT)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", BOOT)
    get_settings.cache_clear()
    yield BOOT
    get_settings.cache_clear()


def _compose(db: Any) -> Any:
    return compose_admin(
        db,
        outbox=MongoOutbox(db),
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _occurrence(
    db: Any, academy_id: str, occurrence_id: str, start: datetime, status: str = "scheduled"
) -> None:
    await db["session_occurrences"].insert_one(
        {
            "occurrence_id": occurrence_id,
            "academy_id": academy_id,
            "session_id": SESSION,
            "start_at": start,
            "end_at": start + timedelta(hours=1),
            "status": status,
            "scheduled_coach_id": f"coach-{academy_id}",
        }
    )


async def _enroll(
    db: Any, academy_id: str, student_id: str, enrolled_at: datetime, status: str = "active"
) -> None:
    await db["enrollments"].insert_one(
        {
            "enrollment_id": f"enr-{academy_id}-{student_id}",
            "academy_id": academy_id,
            "session_id": SESSION,
            "student_id": student_id,
            "parent_id": f"par-{student_id}",
            "status": status,
            "enrolled_at": enrolled_at,
            "created_at": enrolled_at,
        }
    )


async def _mark(
    db: Any, academy_id: str, occurrence_id: str, student_id: str, status: str, **extra: Any
) -> None:
    await db["attendance"].insert_one(
        {
            "attendance_id": f"att-{academy_id}-{occurrence_id}-{student_id}",
            "academy_id": academy_id,
            "occurrence_id": occurrence_id,
            "session_id": SESSION,
            "student_id": student_id,
            "marked_by": f"coach-{academy_id}",
            "marked_at": THREE_DAYS_AGO + timedelta(minutes=5),
            "marked_at_client": None,
            "status": status,
            "client_app_version": "test",
            "entry_source": "enrollment",
            **extra,
        }
    )


async def _seed(db: Any) -> None:
    for academy_id in (BOOT, DEMO):
        await db["sessions"].insert_one(
            {"session_id": SESSION, "academy_id": academy_id, "title": f"Juniors {academy_id}"}
        )
        await db["students"].insert_one(
            {
                "student_id": "stu-1",
                "academy_id": academy_id,
                "parent_id": "par-stu-1",
                "full_name": f"Ava {academy_id}",
            }
        )
        await _enroll(db, academy_id, "stu-1", NOW - timedelta(days=60))
    # Same ids in both academies on purpose.
    await _occurrence(db, DEMO, "occ-unmarked", THREE_DAYS_AGO)
    await _occurrence(db, BOOT, "occ-unmarked", THREE_DAYS_AGO)
    await _mark(db, BOOT, "occ-unmarked", "stu-1", "present")  # A's mark must not hide B's date
    await _occurrence(db, DEMO, "occ-marked", THREE_DAYS_AGO - timedelta(days=1))
    await _mark(db, DEMO, "occ-marked", "stu-1", "present")
    await _occurrence(db, DEMO, "occ-voided", THREE_DAYS_AGO - timedelta(days=2))
    await _mark(
        db,
        DEMO,
        "occ-voided",
        "stu-1",
        "voided",
        previous_status="present",
        corrected_by="admin-demo",
        corrected_at=NOW - timedelta(hours=2),
        correction_reason="Marked the wrong class",
    )
    await _occurrence(
        db, DEMO, "occ-cancelled", THREE_DAYS_AGO + timedelta(hours=2), status="cancelled"
    )
    await _occurrence(db, DEMO, "occ-in-grace", NOW - timedelta(hours=10))
    await _occurrence(db, BOOT, "occ-boot-only", THREE_DAYS_AGO - timedelta(days=4))
    await db["users"].insert_one(
        {"user_id": "admin-demo", "email": "owner@example.test", "display_name": "Demo Owner"}
    )


async def test_missing_attendance_and_corrections_are_the_request_academys(
    real_db: Any, booted_as_a: str
) -> None:
    await _seed(real_db)
    review_uc = _compose(real_db).list_attendance_review

    with tenant_scope(DEMO):
        review = await review_uc.execute()

    # A voided-only date was taken then annulled, so it is a correction, not missing;
    # cancelled and in-grace dates never show.
    assert [row.occurrence_id for row in review.missing] == ["occ-unmarked"]
    unmarked = next(row for row in review.missing if row.occurrence_id == "occ-unmarked")
    assert unmarked.session_id == SESSION
    assert unmarked.session_name == f"Juniors {DEMO}"
    assert unmarked.enrolled_count == 1

    assert [
        (c.occurrence_id, c.student_name, c.previous_status, c.status) for c in review.corrections
    ] == [("occ-voided", f"Ava {DEMO}", "present", "voided")]
    assert review.corrections[0].corrected_by_name == "Demo Owner"
    assert review.corrections[0].reason == "Marked the wrong class"


async def test_boot_academy_sees_only_its_own_dates(real_db: Any, booted_as_a: str) -> None:
    await _seed(real_db)
    review_uc = _compose(real_db).list_attendance_review

    with tenant_scope(BOOT):
        review = await review_uc.execute()

    # A marked its colliding "occ-unmarked"; B's dates and B's void never leak in.
    assert [row.occurrence_id for row in review.missing] == ["occ-boot-only"]
    assert review.missing[0].session_name == f"Juniors {BOOT}"
    assert review.corrections == []


async def test_roster_counts_ignore_late_joiners_and_inactive_enrollments(
    real_db: Any, booted_as_a: str
) -> None:
    await _occurrence(real_db, DEMO, "occ-1", THREE_DAYS_AGO)
    await _enroll(real_db, DEMO, "stu-joined-later", NOW - timedelta(days=1))
    await _enroll(real_db, DEMO, "stu-dropped", NOW - timedelta(days=60), status="dropped")
    # Another academy's active student on the same session id must not count.
    await _enroll(real_db, BOOT, "stu-other-academy", NOW - timedelta(days=60))

    with tenant_scope(DEMO):
        missing = await _compose(real_db).list_attendance_review.missing()

    assert missing == []  # zero enrolled on that date -> not flagged
