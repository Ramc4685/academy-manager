"""People reports L5b on a real ``mongod`` with every migration applied.

Attendance risk by class and coach reads the enrollment context's own
lifecycle derivation (``MongoStudentRepository.lifecycle_snapshots``), so the
seeds below exercise that rule, not a copy of it:

* a student with no mark in the last three class dates is at risk; one who
  was present last week is not;
* an absent-only student and a student whose only present mark was voided
  are at risk (absent marks and voided marks never count as "seen");
* a class with only two past dates flags nobody;
* a withdrawn student holds no seat and is not counted;
* a student in two of one coach's classes counts in both classes, once for
  the coach;
* a coach with no membership in the academy is not named;
* another academy's students and classes never appear.

Families lost counts the family index's Left families whose departure took
effect in the window, by the latest recorded ``reason_code``, else by how the
last class ended; a split family, a family that came back, an older
departure and another academy's events are not counted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.composition.families_crm import compose_admin_family_index
from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.crm.application.people_reports import (
    FamiliesLost,
    FamiliesLostReport,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.crm.infrastructure.people_reports_read_model import (
    MongoDepartureSource,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

ACAD = "acad-l5b-a"
OTHER = "acad-l5b-b"


async def _academy(db: Any, academy_id: str) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "display_name": "Test Academy", "timezone": "America/Chicago"}
    )


async def _student(db: Any, academy_id: str, student_id: str, parent_id: str) -> None:
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": student_id,
            "parent_id": parent_id,
            "full_name": f"Testchild {student_id}",
            "status": "active",
        }
    )


async def _enroll(
    db: Any, academy_id: str, student_id: str, session_id: str, status: str = "active"
) -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": academy_id,
            "enrollment_id": f"enr-{student_id}-{session_id}",
            "student_id": student_id,
            "session_id": session_id,
            "status": status,
        }
    )


async def _session(
    db: Any, academy_id: str, session_id: str, title: str, coach: str | None
) -> None:
    doc: dict[str, Any] = {"academy_id": academy_id, "session_id": session_id, "title": title}
    if coach:
        doc["coach_id"] = coach
    await db["sessions"].insert_one(doc)


async def _occurrences(
    db: Any, academy_id: str, session_id: str, weeks: int, now: datetime
) -> None:
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": academy_id,
                "occurrence_id": f"occ-{session_id}-{n}",
                "session_id": session_id,
                "start_at": now - timedelta(days=n * 7),
                "end_at": now - timedelta(days=n * 7) + timedelta(hours=1),
                "status": "scheduled",
            }
            for n in range(1, weeks + 1)
        ]
    )


async def _mark(
    db: Any, academy_id: str, student_id: str, occurrence_id: str, status: str, now: datetime
) -> None:
    await db["attendance"].insert_one(
        {
            "academy_id": academy_id,
            "attendance_id": f"att-{student_id}-{occurrence_id}",
            "student_id": student_id,
            "occurrence_id": occurrence_id,
            "status": status,
            "marked_at": now - timedelta(days=7),
        }
    )


async def _seed_attendance(db: Any) -> None:
    now = datetime.now(UTC)
    await _academy(db, ACAD)
    await _academy(db, OTHER)
    await db["users"].insert_many(
        [
            {"user_id": "coach-l5b-1", "display_name": "Testcoach One", "roles": ["coach"]},
            {"user_id": "coach-l5b-2", "display_name": "Testcoach Elsewhere", "roles": ["coach"]},
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "membership_id": "m-l5b-1",
                "academy_id": ACAD,
                "user_id": "coach-l5b-1",
                "roles": ["coach"],
                "status": "active",
            },
            # coach-2 teaches here on paper but is a member of OTHER only.
            {
                "membership_id": "m-l5b-2",
                "academy_id": OTHER,
                "user_id": "coach-l5b-2",
                "roles": ["coach"],
                "status": "active",
            },
        ]
    )
    await _session(db, ACAD, "sess-l5b-tue", "Tuesday Juniors", "coach-l5b-1")
    await _session(db, ACAD, "sess-l5b-thu", "Thursday Juniors", "coach-l5b-1")
    await _session(db, ACAD, "sess-l5b-sat", "Saturday Squad", "coach-l5b-2")
    await _session(db, ACAD, "sess-l5b-new", "Brand New Class", None)
    for sid in ("sess-l5b-tue", "sess-l5b-thu", "sess-l5b-sat"):
        await _occurrences(db, ACAD, sid, 4, now)
    await _occurrences(db, ACAD, "sess-l5b-new", 2, now)

    for student, sessions in {
        "st-a": ("sess-l5b-tue", "sess-l5b-thu"),  # never marked: at risk
        "st-b": ("sess-l5b-tue",),  # present last week
        "st-c": ("sess-l5b-sat",),  # absent-only: at risk
        "st-d": ("sess-l5b-sat",),  # voided present only: at risk
        "st-e": ("sess-l5b-sat",),  # present last week
        "st-f": ("sess-l5b-new",),  # class too new to judge
    }.items():
        await _student(db, ACAD, student, f"p-{student}")
        for sid in sessions:
            await _enroll(db, ACAD, student, sid)
    await _student(db, ACAD, "st-g", "p-st-g")
    await _enroll(db, ACAD, "st-g", "sess-l5b-tue", status="withdrawn")

    await _mark(db, ACAD, "st-b", "occ-sess-l5b-tue-1", "present", now)
    await _mark(db, ACAD, "st-c", "occ-sess-l5b-sat-1", "absent", now)
    await _mark(db, ACAD, "st-d", "occ-sess-l5b-sat-1", "voided", now)
    await _mark(db, ACAD, "st-e", "occ-sess-l5b-sat-1", "present", now)

    # Another academy: an at-risk student in its own class.
    await _session(db, OTHER, "sess-l5b-other", "Other Academy Class", "coach-l5b-2")
    await _occurrences(db, OTHER, "sess-l5b-other", 4, now)
    await _student(db, OTHER, "st-other", "p-other")
    await _enroll(db, OTHER, "st-other", "sess-l5b-other")


async def test_attendance_risk_by_class_and_coach(real_db) -> None:
    await _seed_attendance(real_db)
    services = compose_admin_family_index(real_db)
    with tenant_scope(ACAD):
        report = await services.reports.attendance_risk.run(ACAD)

    by_class = {
        row.session_id: (row.title, row.coach_name, row.students, row.at_risk)
        for row in report.by_class
    }
    assert by_class == {
        "sess-l5b-sat": ("Saturday Squad", None, 3, 2),
        "sess-l5b-thu": ("Thursday Juniors", "Testcoach One", 1, 1),
        "sess-l5b-tue": ("Tuesday Juniors", "Testcoach One", 2, 1),
        "sess-l5b-new": ("Brand New Class", None, 1, 0),
    }
    # Most at-risk first, then the highest share.
    assert [row.session_id for row in report.by_class] == [
        "sess-l5b-sat",
        "sess-l5b-thu",
        "sess-l5b-tue",
        "sess-l5b-new",
    ]
    by_coach = {
        row.coach_id: (row.coach_name, row.classes, row.students, row.at_risk)
        for row in report.by_coach
    }
    assert by_coach == {
        "coach-l5b-2": (None, 1, 3, 2),
        # st-a is in both of coach 1's classes: one student.
        "coach-l5b-1": ("Testcoach One", 2, 2, 1),
        None: (None, 1, 1, 0),
    }
    assert (report.students, report.at_risk) == (6, 3)


async def test_attendance_risk_never_reads_another_academy(real_db) -> None:
    await _seed_attendance(real_db)
    services = compose_admin_family_index(real_db)
    with tenant_scope(OTHER):
        other = await services.reports.attendance_risk.run(OTHER)
    with tenant_scope(ACAD):
        mine = await services.reports.attendance_risk.run(ACAD)

    assert [row.session_id for row in other.by_class] == ["sess-l5b-other"]
    assert (other.students, other.at_risk) == (1, 1)
    # A member of OTHER is named on OTHER's report only.
    assert other.by_coach[0].coach_name == "Testcoach Elsewhere"
    assert "sess-l5b-other" not in {row.session_id for row in mine.by_class}
    assert (mine.students, mine.at_risk) == (6, 3)


# ------------------------------------------------------------ families lost

#: 10:00 in Chicago: the academy's today is 2026-09-23; default window
#: 2026-06-26 .. 2026-09-23.
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _at(day: date, hour: int = 17) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


async def _event(
    db: Any,
    academy_id: str,
    event_id: str,
    student_id: str,
    event_type: str,
    effective_at: datetime,
    reason_code: str | None = None,
) -> None:
    await db["enrollment_events"].insert_one(
        {
            "event_id": event_id,
            "academy_id": academy_id,
            "event_type": event_type,
            "student_id": student_id,
            "session_id": "sess-l5b-lost",
            "reason": "note",
            "reason_code": reason_code,
            "effective_at": effective_at,
            "occurred_at": effective_at,
        }
    )


async def _left_child(db: Any, academy_id: str, student_id: str, parent_id: str) -> None:
    await _student(db, academy_id, student_id, parent_id)
    await _enroll(db, academy_id, student_id, "sess-l5b-lost", status="withdrawn")


async def _seed_lost(db: Any) -> None:
    await _academy(db, ACAD)
    await _academy(db, OTHER)
    # F1: one child, moved away.
    await _left_child(db, ACAD, "stu-l1", "p-moved")
    await _event(db, ACAD, "ev-1", "stu-l1", "withdrawn", _at(date(2026, 9, 10)), "moved_away")
    await _event(db, ACAD, "ev-1b", "stu-l1", "enrolled", _at(date(2026, 9, 11)))
    # F2: two children; the latest CODED reason wins over a later uncoded drop.
    await _left_child(db, ACAD, "stu-l2a", "p-cost")
    await _left_child(db, ACAD, "stu-l2b", "p-cost")
    await _event(db, ACAD, "ev-2a", "stu-l2a", "dropped", _at(date(2026, 8, 1)), "cost")
    await _event(db, ACAD, "ev-2b", "stu-l2b", "dropped", _at(date(2026, 9, 5)))
    # F3: the family cancelled itself, no reason recorded.
    await _left_child(db, ACAD, "stu-l3", "p-self")
    await _event(db, ACAD, "ev-3", "stu-l3", "cancelled", _at(date(2026, 9, 15)))
    # F4: a hold ran out.
    await _left_child(db, ACAD, "stu-l4", "p-hold")
    await _event(db, ACAD, "ev-4", "stu-l4", "hold_expired", _at(date(2026, 9, 1)))
    # F5: split family (one child still active): not lost.
    await _left_child(db, ACAD, "stu-l5a", "p-split")
    await _student(db, ACAD, "stu-l5b", "p-split")
    await _enroll(db, ACAD, "stu-l5b", "sess-l5b-other-class")
    await _event(db, ACAD, "ev-5", "stu-l5a", "withdrawn", _at(date(2026, 9, 2)), "cost")
    # F6: left before the window: not lost in it.
    await _left_child(db, ACAD, "stu-l6", "p-old")
    await _event(db, ACAD, "ev-6", "stu-l6", "withdrawn", _at(date(2026, 3, 1)), "cost")
    # F7: left in the window and came back to another class: not lost.
    await _left_child(db, ACAD, "stu-l7", "p-back")
    await _enroll(db, ACAD, "stu-l7", "sess-l5b-other-class")
    await _event(db, ACAD, "ev-7", "stu-l7", "withdrawn", _at(date(2026, 9, 3)), "cost")
    # Another academy's event for a student id that also exists in ACAD.
    await _left_child(db, OTHER, "stu-l1", "p-other")
    await _event(
        db, OTHER, "ev-x", "stu-l1", "withdrawn", _at(date(2026, 9, 20)), "switched_academy"
    )


def _lost_report(db: Any) -> FamiliesLostReport:
    index = MongoFamilyIndexReadModel(
        db,
        parents=MongoUserRepository(db),
        children=MongoStudentRepository(db),
        money=MongoFamilyMoneyReadModel(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )
    return FamiliesLostReport(
        index=index,
        departures=MongoDepartureSource(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )


def _reasons(report: FamiliesLost) -> dict[str, int]:
    return {row.key: row.families for row in report.by_reason if row.families}


async def test_families_lost_by_recorded_reason_else_by_transition(real_db) -> None:
    await _seed_lost(real_db)
    with tenant_scope(ACAD):
        report = await _lost_report(real_db).run(ACAD)

    assert (report.date_from, report.date_to) == (date(2026, 6, 26), date(2026, 9, 23))
    assert report.timezone == "America/Chicago"
    assert report.families_lost == 4
    assert _reasons(report) == {"moved_away": 1, "cost": 1}
    assert report.with_reason == 2
    assert [(row.key, row.label, row.families) for row in report.by_transition] == [
        ("cancelled_by_family", "Cancelled by the family", 1),
        ("hold_expired", "Hold ran out", 1),
    ]
    assert report.without_reason == 2
    # Every code is listed, zeros included, so the table never drops one.
    assert len(report.by_reason) == 10


async def test_families_lost_window_edges_are_academy_local_days(real_db) -> None:
    await _seed_lost(real_db)
    # 2026-09-15 23:59 in Chicago is 04:59 UTC on the 16th: inside "to 15th".
    await _left_child(real_db, ACAD, "stu-edge-in", "p-edge-in")
    await _event(
        real_db, ACAD, "ev-in", "stu-edge-in", "withdrawn", datetime(2026, 9, 16, 4, 59, tzinfo=UTC)
    )
    await _left_child(real_db, ACAD, "stu-edge-out", "p-edge-out")
    await _event(
        real_db, ACAD, "ev-out", "stu-edge-out", "removed", datetime(2026, 9, 16, 5, 0, tzinfo=UTC)
    )
    with tenant_scope(ACAD):
        report = await _lost_report(real_db).run(
            ACAD, date_from=date(2026, 9, 15), date_to=date(2026, 9, 15)
        )

    # F3 (cancelled on the 15th, 17:00 UTC) and the 23:59 local drop.
    assert report.families_lost == 2
    assert {row.key: row.families for row in report.by_transition} == {
        "dropped_by_staff": 1,
        "cancelled_by_family": 1,
    }


async def test_families_lost_is_tenant_scoped(real_db) -> None:
    await _seed_lost(real_db)
    with tenant_scope(OTHER):
        other = await _lost_report(real_db).run(OTHER)
    assert other.families_lost == 1
    assert _reasons(other) == {"switched_academy": 1}

    services = compose_admin_family_index(real_db)
    with tenant_scope(ACAD):
        mine = await services.reports.families_lost.run(
            ACAD, date_from=date(2026, 6, 26), date_to=date(2026, 9, 23)
        )
    assert "switched_academy" not in _reasons(mine)
    assert mine.families_lost == 4
