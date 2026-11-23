"""Admin class-date rows count the requesting academy's attendance marks.

``compose_admin`` captures ``academy_id = primary_academy_id or
default_academy_id`` once, at boot. The class-date row builder
(``_occurrence_row``) filtered ``attendance`` on that boot value, so an admin
in any other academy (the Demo Academy in production) saw
``attendance_marked_count == 0`` for a date its coach had fully marked, and the
UI hid the Attendance action. Worse, with colliding occurrence ids the boot
academy's marks were counted for the other tenant.

Real mongod (``real_db``, every migration applied), production composition
root, booted as academy A.
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
SESSION = "sess-junior-beginners"
# Same occurrence id in both academies on purpose: it makes a cross-tenant
# count visible instead of merely zero.
MARKED = "occ-2026-11-21"
EMPTY = "occ-2026-11-28"
START = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


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


async def _seed_occurrence(db: Any, academy_id: str, occurrence_id: str, start: datetime) -> None:
    await db["session_occurrences"].insert_one(
        {
            "occurrence_id": occurrence_id,
            "academy_id": academy_id,
            "session_id": SESSION,
            "start_at": start,
            "end_at": start + timedelta(hours=1),
            "status": "scheduled",
            "scheduled_coach_id": f"coach-{academy_id}",
        }
    )


async def _seed_mark(
    db: Any, academy_id: str, student_id: str, status: str, occurrence_id: str = MARKED
) -> None:
    await db["attendance"].insert_one(
        {
            "attendance_id": f"att-{academy_id}-{occurrence_id}-{student_id}",
            "academy_id": academy_id,
            "occurrence_id": occurrence_id,
            "session_id": SESSION,
            "student_id": student_id,
            "marked_by": f"coach-{academy_id}",
            "marked_at": START + timedelta(minutes=5),
            "marked_at_client": None,
            "status": status,
            "client_app_version": "test",
            "entry_source": "enrollment",
        }
    )


async def _seed(db: Any) -> None:
    for academy_id in (BOOT, DEMO):
        await _seed_occurrence(db, academy_id, MARKED, START)
    await _seed_occurrence(db, DEMO, EMPTY, START + timedelta(days=7))
    # Demo coach marked 2/2 present; boot academy has one absent mark.
    await _seed_mark(db, DEMO, "stu-demo-1", "present")
    await _seed_mark(db, DEMO, "stu-demo-2", "present")
    await _seed_mark(db, BOOT, "stu-boot-1", "absent")
    # A boot-academy mark on the id of the date Demo never marked: read with
    # the boot academy, Demo's empty date would show 1 and offer Attendance.
    await _seed_mark(db, BOOT, "stu-boot-1", "present", occurrence_id=EMPTY)


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["occurrence_id"]: row for row in rows}


async def test_non_boot_academy_admin_sees_its_coach_marks(real_db: Any, booted_as_a: str) -> None:
    await _seed(real_db)
    admin = _compose(real_db)

    with tenant_scope(DEMO):
        rows = _rows_by_id(await admin.list_session_occurrences(SESSION))
        marks = await admin.list_occurrence_attendance(MARKED)

    assert rows[MARKED]["attendance_marked_count"] == 2
    assert rows[MARKED]["attendance_marked_by"] == [f"coach-{DEMO}"]
    assert rows[MARKED]["attendance_last_marked_at"] is not None
    # Zero-mark dates stay at 0, so the UI keeps the Attendance action hidden.
    assert rows[EMPTY]["attendance_marked_count"] == 0
    assert rows[EMPTY]["attendance_marked_by"] == []
    # The list the Attendance action opens shows the same marks.
    assert sorted((m.student_id, m.status, m.marked_by) for m in marks) == [
        ("stu-demo-1", "present", f"coach-{DEMO}"),
        ("stu-demo-2", "present", f"coach-{DEMO}"),
    ]


async def test_counts_are_isolated_between_academies(real_db: Any, booted_as_a: str) -> None:
    await _seed(real_db)
    admin = _compose(real_db)

    with tenant_scope(BOOT):
        boot_rows = _rows_by_id(await admin.list_session_occurrences(SESSION))
        boot_marks = await admin.list_occurrence_attendance(MARKED)

    assert boot_rows[MARKED]["attendance_marked_count"] == 1
    assert boot_rows[MARKED]["attendance_marked_by"] == [f"coach-{BOOT}"]
    assert EMPTY not in boot_rows  # B's date never surfaces in A
    assert [(m.student_id, m.status) for m in boot_marks] == [("stu-boot-1", "absent")]

    # Remove A's marks: B's count must not move, proving it never read A's rows.
    await real_db["attendance"].delete_many({"academy_id": BOOT})
    with tenant_scope(DEMO):
        demo_rows = _rows_by_id(await admin.list_session_occurrences(SESSION))
    assert demo_rows[MARKED]["attendance_marked_count"] == 2
    with tenant_scope(BOOT):
        boot_rows = _rows_by_id(await admin.list_session_occurrences(SESSION))
    assert boot_rows[MARKED]["attendance_marked_count"] == 0
