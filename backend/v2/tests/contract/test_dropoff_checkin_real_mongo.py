"""Parent drop-off check-in on a real ``mongod``: report, confirm, reconcile.

Production composition (``compose_dropoff_checkins``) and the real parent,
coach and admin routers, every migration applied (0246's unique index
included). Times are relative to the real clock: the window is 30 minutes
before to 15 minutes after the occurrence's current start.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.composition.dropoff_checkins import (
    DropoffCheckinComposition,
    compose_dropoff_checkins,
)
from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    ConfirmDropoffCommand,
    OccurrenceRef,
    ReportArrivalCommand,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    DropoffCheckinDisabled,
    DropoffWindowClosed,
    SessionNotAssigned,
)
from backend.v2.contexts.coaching.infrastructure.mongo_dropoff_checkin_repo import (
    MongoDropoffCheckinRepository,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.idempotency.decorator import IdempotentRequestInFlight
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore

pytestmark = pytest.mark.asyncio

ACADEMY = "test-academy"
SESSION = "sess-dropoff"
OCC = "occ-dropoff-1"
STUDENT = "stu-ava"
SIBLING = "stu-ben"
PARENT = "u-parent"
COACH = "u-coach"


def _now() -> datetime:
    return datetime.now(UTC)


def _compose(db: Any) -> DropoffCheckinComposition:
    return compose_dropoff_checkins(db, MongoOutbox(db), MongoIdempotencyStore(db))


def _client(db: Any, *, user_id: str, roles: tuple[str, ...]) -> httpx.AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    for r in (admin_router, coach_router, parent_router):
        app.include_router(r, prefix="/api/v2")
    claims = AuthClaims(
        user_id=user_id, email=f"{user_id}@example.com", academy_id=ACADEMY, roles=roles
    )  # type: ignore[arg-type]
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.dropoff_checkins = _compose(db)
    app.state.parent = compose_parent(
        db,
        outbox=MongoOutbox(db),
        idempotency_store=MongoIdempotencyStore(db),
        stripe=object(),  # type: ignore[arg-type]
        academy_id=ACADEMY,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _policy(db: Any, *, enabled: bool = True, academy: str = ACADEMY) -> None:
    await db["parent_self_service_policies"].update_one(
        {"academy_id": academy},
        {
            "$set": {
                "dropoff_checkin_enabled": enabled,
                "dropoff_checkin_opens_minutes_before": 30,
                "dropoff_checkin_closes_minutes_after": 15,
            }
        },
        upsert=True,
    )


async def _occurrence(
    db: Any,
    *,
    start: datetime,
    occurrence_id: str = OCC,
    academy: str = ACADEMY,
    status: str = "scheduled",
) -> None:
    await db["session_occurrences"].insert_one(
        {
            "occurrence_id": occurrence_id,
            "academy_id": academy,
            "session_id": SESSION,
            "template_session_id": SESSION,
            "start_at": start,
            "end_at": start + timedelta(minutes=45),
            "status": status,
            "scheduled_coach_id": COACH,
            "is_billable": True,
            "is_payable": True,
        }
    )


async def _student(db: Any, student_id: str, *, parent_id: str = PARENT, enrolled: bool = True):
    await db["students"].insert_one(
        {
            "academy_id": ACADEMY,
            "student_id": student_id,
            "first_name": student_id,
            "last_name": "Test",
            "full_name": f"{student_id} Test",
            "dob": "2016-05-01",
            "skill_level": "beginner",
            "parent_id": parent_id,
            "parent_user_id": parent_id,
            "status": "active",
            "is_deleted": False,
            "created_at": _now(),
        }
    )
    if enrolled:
        await db["enrollments"].insert_one(
            {
                "academy_id": ACADEMY,
                "enrollment_id": f"enr-{student_id}",
                "session_id": SESSION,
                "student_id": student_id,
                "parent_id": parent_id,
                "parent_user_id": parent_id,
                "billing_type": "Standard",
                "approval_status": "approved",
                "status": "active",
                "enrolled_at": _now(),
                "is_deleted": False,
            }
        )


async def _seed(db: Any, *, start_in: timedelta = timedelta(minutes=10)) -> None:
    await _policy(db)
    await _occurrence(db, start=_now() + start_in)
    await _student(db, STUDENT)
    await _student(db, SIBLING)
    await db["users"].insert_many(
        [
            {"user_id": PARENT, "email": "p@example.com", "display_name": "Pat Parent"},
            {"user_id": COACH, "email": "c@example.com", "display_name": "Casey Coach"},
            {"user_id": "u-desk", "email": "d@example.com", "display_name": "Dana Desk"},
        ]
    )


@pytest.fixture
async def parent(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(real_db, user_id=PARENT, roles=("parent",)) as client:
        yield client


@pytest.fixture
async def coach(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(real_db, user_id=COACH, roles=("coach",)) as client:
        yield client


@pytest.fixture
async def desk(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(real_db, user_id="u-desk", roles=("admin",)) as client:
        yield client


def _arrival(student_id: str = STUDENT, occurrence_id: str = OCC) -> str:
    return f"/api/v2/parent/children/{student_id}/occurrences/{occurrence_id}/arrival"


def _code(resp: httpx.Response) -> str:
    return str(resp.json()["error"]["code"])


# --- Report: refusals -------------------------------------------------------


async def test_report_refused_when_the_academy_has_it_off(parent, real_db) -> None:
    await _seed(real_db)
    await _policy(real_db, enabled=False)
    resp = await parent.post(_arrival())
    assert (resp.status_code, _code(resp)) == (403, "Coaching.DropoffCheckinDisabled")
    assert await real_db["dropoff_checkins"].count_documents({}) == 0


async def test_report_refused_for_another_familys_child(parent, real_db) -> None:
    await _seed(real_db)
    await _student(real_db, "stu-other", parent_id="u-someone-else")
    resp = await parent.post(_arrival("stu-other"))
    assert (resp.status_code, _code(resp)) == (404, "Coaching.DropoffCheckinNotFound")


async def test_report_refused_for_another_academys_class(parent, real_db) -> None:
    await _seed(real_db)
    await _policy(real_db, academy="other-academy")
    await _occurrence(real_db, start=_now(), occurrence_id="occ-elsewhere", academy="other-academy")
    resp = await parent.post(_arrival(occurrence_id="occ-elsewhere"))
    assert (resp.status_code, _code(resp)) == (404, "Coaching.DropoffCheckinNotFound")


async def test_report_refused_when_not_enrolled(parent, real_db) -> None:
    await _seed(real_db)
    await _student(real_db, "stu-unenrolled", enrolled=False)
    resp = await parent.post(_arrival("stu-unenrolled"))
    assert (resp.status_code, _code(resp)) == (409, "Coaching.StudentNotEnrolled")


async def test_report_refused_for_a_cancelled_class(parent, real_db) -> None:
    await _seed(real_db)
    await real_db["session_occurrences"].update_one(
        {"occurrence_id": OCC}, {"$set": {"status": "cancelled"}}
    )
    resp = await parent.post(_arrival())
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "cancelled"


@pytest.mark.parametrize(
    ("start_in", "reason"),
    [(timedelta(minutes=45), "not_open_yet"), (timedelta(minutes=-20), "closed")],
)
async def test_report_refused_outside_the_window(
    parent, real_db, start_in: timedelta, reason: str
) -> None:
    await _seed(real_db, start_in=start_in)
    resp = await parent.post(_arrival())
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == reason
    assert await real_db["dropoff_checkins"].count_documents({}) == 0


async def test_a_reschedule_moves_the_window(parent, real_db) -> None:
    await _seed(real_db, start_in=timedelta(hours=3))
    assert (await parent.post(_arrival())).status_code == 409
    await real_db["session_occurrences"].update_one(
        {"occurrence_id": OCC}, {"$set": {"start_at": _now() + timedelta(minutes=5)}}
    )
    resp = await parent.post(_arrival())
    assert resp.status_code == 200 and resp.json()["state"] == "pending"


# --- Report: idempotency and siblings ---------------------------------------


async def test_repeat_and_concurrent_taps_store_one_row(parent, real_db) -> None:
    await _seed(real_db)
    first = await parent.post(_arrival())
    assert first.status_code == 200
    body = first.json()
    assert body["state"] == "pending" and body["can_report_arrival"] is False
    replies = await asyncio.gather(*(parent.post(_arrival()) for _ in range(5)))
    assert {r.status_code for r in replies} == {200}
    assert {r.json()["reported_at"] for r in replies} == {body["reported_at"]}
    assert await real_db["dropoff_checkins"].count_documents({}) == 1
    # A report is never attendance.
    assert await real_db["attendance"].count_documents({}) == 0


async def test_siblings_are_separate_rows(parent, real_db, acad) -> None:
    await _seed(real_db)
    assert (await parent.post(_arrival(STUDENT))).status_code == 200
    reads = _compose(real_db).reads
    ref = OccurrenceRef(
        occurrence_id=OCC, starts_at=_now() + timedelta(minutes=10), status="scheduled"
    )
    mine = await reads.for_student(STUDENT, [ref])
    sibling = await reads.for_student(SIBLING, [ref])
    assert mine and mine[OCC].state == "pending"
    assert sibling and sibling[OCC].state == "none" and sibling[OCC].can_report_arrival
    assert (await parent.post(_arrival(SIBLING))).status_code == 200
    assert await real_db["dropoff_checkins"].count_documents({}) == 2


# --- Confirm -----------------------------------------------------------------


def _confirm_coach(student_id: str = STUDENT) -> str:
    return f"/api/v2/coach/occurrences/{OCC}/checkins/{student_id}/confirm"


def _confirm_admin(student_id: str = STUDENT) -> str:
    return f"/api/v2/admin/session-occurrences/{OCC}/checkins/{student_id}/confirm"


async def test_coach_confirm_writes_one_present_mark(parent, coach, real_db) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    resp = await coach.post(_confirm_coach())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed" and body["confirmed_by"] == COACH
    assert body["reconciled_with_existing_mark"] is False
    [mark] = await real_db["attendance"].find({}).to_list(None)
    assert mark["attendance_id"] == body["attendance_id"]
    assert mark["attendance_id"].startswith("dropoff:")
    assert (mark["status"], mark["marked_by"]) == ("present", COACH)
    # Confirming again is a no-op.
    again = await coach.post(_confirm_coach())
    assert again.json()["attendance_id"] == body["attendance_id"]
    assert await real_db["attendance"].count_documents({}) == 1


async def test_two_concurrent_confirms_write_exactly_one_mark(parent, real_db, acad) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    comp = _compose(real_db)
    cmd = ConfirmDropoffCommand(occurrence_id=OCC, student_id=STUDENT)
    results = await asyncio.gather(
        comp.confirm.execute(cmd, staff_id=COACH, supervisor=False),
        comp.confirm.execute(cmd, staff_id="u-admin", supervisor=True),
        comp.confirm.execute(cmd, staff_id="u-owner", supervisor=True),
        # The same coach double-tapping may meet its own in-flight request.
        comp.confirm.execute(cmd, staff_id=COACH, supervisor=False),
        return_exceptions=True,
    )
    snapshots = [r for r in results if not isinstance(r, BaseException)]
    assert all(isinstance(r, IdempotentRequestInFlight) for r in results if r not in snapshots)
    assert len(snapshots) >= 3
    final = await comp.confirm.execute(cmd, staff_id=COACH, supervisor=False)
    ids = {s.checkin.attendance_id for s in [*snapshots, final] if s.checkin}
    assert final.state == "confirmed" and len(ids) == 1
    assert await real_db["attendance"].count_documents({}) == 1
    mark = await real_db["attendance"].find_one({"student_id": STUDENT})
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["confirmed_by"] == mark["marked_by"]


async def test_failure_after_the_mark_is_saved_is_finished_by_a_retry(
    parent, real_db, acad, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    real_finish = MongoDropoffCheckinRepository.finish_confirm
    calls = {"n": 0}

    async def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection dropped")
        return await real_finish(self, *args, **kwargs)

    monkeypatch.setattr(MongoDropoffCheckinRepository, "finish_confirm", flaky)
    comp = _compose(real_db)
    cmd = ConfirmDropoffCommand(occurrence_id=OCC, student_id=STUDENT)
    with pytest.raises(RuntimeError):
        await comp.confirm.execute(cmd, staff_id=COACH, supervisor=False)
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["status"] == "confirming"
    assert await real_db["attendance"].count_documents({}) == 1
    # Still pending inside the window; a different staff
    # member's retry finishes the job without a second mark.
    done = await comp.confirm.execute(cmd, staff_id="u-admin", supervisor=True)
    assert done.state == "confirmed"
    assert done.checkin and done.checkin.attendance_id == row["confirm_mutation_id"]
    assert done.checkin.reconciled_with_existing_mark is False
    assert await real_db["attendance"].count_documents({}) == 1
    # Attribution follows the saved mark, not whoever happened to finish.
    mark = await real_db["attendance"].find_one({"student_id": STUDENT})
    final = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert mark["marked_by"] == COACH and final["confirmed_by"] == COACH


async def _manual_mark(db: Any, status: str, *, attendance_id: str = "manual-1") -> None:
    await db["attendance"].insert_one(
        {
            "attendance_id": attendance_id,
            "academy_id": ACADEMY,
            "occurrence_id": OCC,
            "session_id": SESSION,
            "student_id": STUDENT,
            "marked_by": COACH,
            "marked_at": _now(),
            "marked_at_client": None,
            "status": status,
            "client_app_version": "test",
            "entry_source": "enrollment",
        }
    )


@pytest.mark.parametrize("existing_status", ["present", "late"])
async def test_an_existing_present_mark_is_linked_not_duplicated(
    parent, coach, real_db, existing_status: str
) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    await _manual_mark(real_db, existing_status)
    resp = await coach.post(_confirm_coach())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert (body["attendance_id"], body["reconciled_with_existing_mark"]) == ("manual-1", True)
    [mark] = await real_db["attendance"].find({}).to_list(None)
    assert mark["status"] == existing_status  # untouched
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["confirmed_by"] == COACH  # the staffer who confirmed


@pytest.mark.parametrize("existing_status", ["absent", "voided"])
async def test_an_absent_or_voided_mark_is_refused_not_papered_over(
    parent, coach, real_db, acad, existing_status: str
) -> None:
    """Roll call marked the child Absent before they arrived: confirm must
    not say "Checked in" while the official record says absent."""
    await _seed(real_db)
    await parent.post(_arrival())
    await _manual_mark(real_db, existing_status)
    resp = await coach.post(_confirm_coach())
    assert (resp.status_code, _code(resp)) == (409, "Coaching.ConflictAttendanceExists")
    assert resp.json()["error"]["details"]["existing_status"] == existing_status
    # Not claimed: the row stays reported and simply expires if nobody acts.
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["status"] == "reported"
    [mark] = await real_db["attendance"].find({}).to_list(None)
    assert mark["status"] == existing_status
    summary = await _compose(real_db).reads.occurrence_summary(OCC)
    assert summary is not None and [s.state for s in summary.checkins] == ["pending"]
    # Staff correct the mark to Present: the report now reads as confirmed.
    await real_db["attendance"].update_one(
        {"attendance_id": "manual-1"}, {"$set": {"status": "present"}}
    )
    summary = await _compose(real_db).reads.occurrence_summary(OCC)
    assert summary is not None and [s.state for s in summary.checkins] == ["confirmed"]


async def test_a_manual_present_mark_resolves_a_pending_report(parent, real_db, acad) -> None:
    """Coach taps "Mark all present" instead of Confirm: parents see Checked in."""
    await _seed(real_db)
    await parent.post(_arrival())
    comp = _compose(real_db)
    await comp.confirm._mark.execute(
        MarkAttendanceCommand(
            mutation_id="bulk-1",
            occurrence_id=OCC,
            session_id=SESSION,
            student_id=STUDENT,
            status="present",
        ),
        COACH,
    )
    ref = OccurrenceRef(
        occurrence_id=OCC, starts_at=_now() + timedelta(minutes=10), status="scheduled"
    )
    mine = await comp.reads.for_student(STUDENT, [ref])
    assert mine and mine[OCC].state == "confirmed"
    staff = await comp.reads.for_occurrences([ref])
    assert staff[OCC][STUDENT].state == "confirmed"


async def test_a_voided_dropoff_mark_no_longer_reads_checked_in(
    parent, coach, real_db, acad
) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    body = (await coach.post(_confirm_coach())).json()
    assert body["state"] == "confirmed"
    await real_db["attendance"].update_one(
        {"attendance_id": body["attendance_id"]}, {"$set": {"status": "voided"}}
    )
    summary = await _compose(real_db).reads.occurrence_summary(OCC)
    assert summary is not None and [s.state for s in summary.checkins] == ["pending"]
    again = await coach.post(_confirm_coach())
    assert (again.status_code, _code(again)) == (409, "Coaching.ConflictAttendanceExists")


async def test_a_withdrawn_child_is_refused_before_the_claim(parent, real_db, acad) -> None:
    """Enrollment withdrawn after the report: confirm refuses and the row is
    not stranded ``confirming`` (it stays reported and expires)."""
    await _seed(real_db)
    await parent.post(_arrival())
    await real_db["enrollments"].update_one(
        {"student_id": STUDENT}, {"$set": {"status": "withdrawn"}}
    )
    async with _client(real_db, user_id=COACH, roles=("coach",)) as coach:
        resp = await coach.post(_confirm_coach())
    assert (resp.status_code, _code(resp)) == (409, "Coaching.StudentNotEnrolled")
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["status"] == "reported"
    assert await real_db["attendance"].count_documents({}) == 0


async def test_parent_schedule_still_lists_a_started_class_with_its_checkin(
    parent, coach, real_db
) -> None:
    """Class began 5 minutes ago (window open until +15): the parent's
    default schedule read still carries it, report and confirmation."""
    await _seed(real_db, start_in=timedelta(minutes=-5))
    schedule = f"/api/v2/parent/children/{STUDENT}/schedule"
    [entry] = [
        e for e in (await parent.get(schedule)).json()["entries"] if e["occurrence_id"] == OCC
    ]
    assert entry["can_report_arrival"] is True
    assert (await parent.post(_arrival())).status_code == 200
    assert (await coach.post(_confirm_coach())).status_code == 200
    [entry] = [
        e for e in (await parent.get(schedule)).json()["entries"] if e["occurrence_id"] == OCC
    ]
    assert entry["checkin"]["state"] == "confirmed"
    # Feature off: the default read is upcoming-only again.
    await _policy(real_db, enabled=False)
    entries = (await parent.get(schedule)).json()["entries"]
    assert OCC not in {e["occurrence_id"] for e in entries}


async def test_unassigned_coach_is_refused(parent, real_db) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    async with _client(real_db, user_id="u-other-coach", roles=("coach",)) as other:
        resp = await other.post(_confirm_coach())
    assert (resp.status_code, _code(resp)) == (409, "Coaching.SessionNotAssigned")
    assert await real_db["attendance"].count_documents({}) == 0


async def test_admin_confirms_and_sees_names(parent, desk, real_db) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    resp = await desk.post(_confirm_admin())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert (body["reported_by_name"], body["confirmed_by_name"]) == ("Pat Parent", "Dana Desk")
    assert await real_db["attendance"].count_documents({"status": "present"}) == 1


async def test_parent_coach_and_front_desk_cannot_use_the_admin_confirm(
    parent, coach, real_db
) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    assert (await parent.post(_confirm_admin())).status_code == 404
    assert (await coach.post(_confirm_admin())).status_code == 404
    # Front desk cannot open the attendance dialog, so it gets no blind write.
    async with _client(real_db, user_id="u-fd", roles=("front_desk",)) as front_desk:
        assert (await front_desk.post(_confirm_admin())).status_code == 404
    assert await real_db["attendance"].count_documents({}) == 0


async def test_confirm_without_a_report_is_404(coach, real_db) -> None:
    await _seed(real_db)
    resp = await coach.post(_confirm_coach())
    assert (resp.status_code, _code(resp)) == (404, "Coaching.DropoffCheckinNotFound")


async def test_an_expired_report_is_not_attendance_and_cannot_be_confirmed(
    coach, real_db, acad
) -> None:
    await _seed(real_db, start_in=timedelta(minutes=-30))
    await real_db["dropoff_checkins"].insert_one(
        {
            "checkin_id": "chk-old",
            "academy_id": ACADEMY,
            "occurrence_id": OCC,
            "session_id": SESSION,
            "student_id": STUDENT,
            "reported_by": PARENT,
            "reported_at": _now() - timedelta(minutes=35),
            "status": "reported",
        }
    )
    resp = await coach.post(_confirm_coach())
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "expired"
    summary = await _compose(real_db).reads.occurrence_summary(OCC)
    assert summary is not None
    assert [s.state for s in summary.checkins] == ["expired"]
    assert await real_db["attendance"].count_documents({}) == 0


# --- Reads and the feature-off path ----------------------------------------


async def test_staff_summary_lists_expected_and_reports(parent, real_db, acad) -> None:
    await _seed(real_db)
    await parent.post(_arrival(STUDENT))
    summary = await _compose(real_db).reads.occurrence_summary(OCC)
    assert summary is not None and summary.enabled
    assert set(summary.expected_student_ids) == {STUDENT, SIBLING}
    [only] = summary.checkins
    assert (only.student_id, only.state) == (STUDENT, "pending")
    assert await _compose(real_db).reads.occurrence_summary("occ-missing") is None
    ref = OccurrenceRef(occurrence_id=OCC, starts_at=_now(), status="scheduled")
    window = (await _compose(real_db).reads.windows([ref]))[OCC]
    assert window.closes_at - window.opens_at == timedelta(minutes=45)


async def test_feature_off_leaves_the_attendance_flow_unchanged(real_db, acad) -> None:
    await _seed(real_db)
    await _policy(real_db, enabled=False)
    comp = _compose(real_db)
    ref = OccurrenceRef(
        occurrence_id=OCC, starts_at=_now() + timedelta(minutes=10), status="scheduled"
    )
    assert await comp.reads.for_student(STUDENT, [ref]) is None
    assert await comp.reads.for_occurrences([ref]) == {OCC: {}}
    assert await comp.reads.windows([ref]) == {}  # coach roster does not poll
    with pytest.raises(DropoffCheckinDisabled):
        await comp.report.execute(
            ReportArrivalCommand(parent_id=PARENT, student_id=STUDENT, occurrence_id=OCC)
        )
    # The coach's manual mark works exactly as before.
    result = await comp.confirm._mark.execute(
        MarkAttendanceCommand(
            mutation_id="manual-mark",
            occurrence_id=OCC,
            session_id=SESSION,
            student_id=STUDENT,
            status="present",
        ),
        COACH,
    )
    assert result.attendance_id == "manual-mark"
    assert await real_db["dropoff_checkins"].count_documents({}) == 0


async def test_unassigned_coach_refused_at_the_use_case_before_any_write(
    parent, real_db, acad
) -> None:
    await _seed(real_db)
    await parent.post(_arrival())
    with pytest.raises(SessionNotAssigned):
        await _compose(real_db).confirm.execute(
            ConfirmDropoffCommand(occurrence_id=OCC, student_id=STUDENT),
            staff_id="u-stranger",
            supervisor=False,
        )
    row = await real_db["dropoff_checkins"].find_one({"student_id": STUDENT})
    assert row["status"] == "reported"


async def test_window_closed_error_is_typed(real_db, acad) -> None:
    await _seed(real_db, start_in=timedelta(hours=2))
    with pytest.raises(DropoffWindowClosed):
        await _compose(real_db).report.execute(
            ReportArrivalCommand(parent_id=PARENT, student_id=STUDENT, occurrence_id=OCC)
        )
