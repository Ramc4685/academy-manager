"""Contract tests for the #593 half-cancelled-session repair script.

Before PR #589 a session cancel flipped ``sessions.status`` only; the
already-materialised ``session_occurrences`` stayed ``"scheduled"`` and
kept accruing expected coach pay. #589 fixed the go-forward DELETE route
but shipped no backfill — ``backend/scripts/recancel_half_cancelled_sessions.py``
is that backfill, and it drives the SAME ``maintain_session_occurrences``
cascade the route drives.

These tests exercise the injected-db entrypoint the way
``test_reconcile_reserved_seats.py`` does, against mongomock. They must
never touch a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.scripts.recancel_half_cancelled_sessions import (
    apply_requested,
    build_arg_parser,
    find_half_cancelled_sessions,
    recancel_half_cancelled_sessions,
)

ACADEMY = "acad-593"

NOW = datetime.now(UTC)
PAST = NOW - timedelta(days=14)
FUTURE = NOW + timedelta(days=14)
FAR_FUTURE = NOW + timedelta(days=120)  # beyond the 60-day maintenance window


def _cancelled_session() -> dict:
    return {
        "session_id": "sess-cancelled",
        "academy_id": ACADEMY,
        "name": "Doomed Recurring",
        "title": "Doomed Recurring",
        "location": "Court 1",
        "coach_id": "coach-1",
        "max_students": 10,
        "capacity": 10,
        "amount_cents": 12000,
        "status": "cancelled",
        "days_of_week": ["Mon", "Wed"],
        "start_time": "09:15",
        "end_time": "10:15",
        "timezone": "America/Chicago",
    }


def _live_session() -> dict:
    doc = _cancelled_session()
    doc.update({"session_id": "sess-live", "title": "Still Running", "status": "active"})
    return doc


def _occurrence(occurrence_id: str, start_at: datetime, **overrides: object) -> dict:
    doc: dict = {
        "occurrence_id": occurrence_id,
        "academy_id": ACADEMY,
        "session_id": "sess-cancelled",
        "template_session_id": "sess-cancelled",
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
        "status": "scheduled",
        "scheduled_coach_id": "coach-1",
        "actual_coach_id": None,
        "substitute_coach_id": None,
        "is_billable": True,
        "is_payable": True,
    }
    doc.update(overrides)
    return doc


async def _seed(db) -> None:
    await db.sessions.insert_many([_cancelled_session(), _live_session()])
    await db.session_occurrences.insert_many(
        [
            # Repairable: clean, future, nobody has touched it.
            _occurrence("occ-clean", FUTURE),
            # Clean but materialised beyond the 60-day window — a cancel has
            # to reach it too (#467).
            _occurrence("occ-clean-far", FAR_FUTURE),
            # History: the class happened, attendance was taken.
            _occurrence("occ-past", PAST),
            # Future but already acted on — must survive untouched.
            _occurrence("occ-coach-assigned", FUTURE, actual_coach_id="coach-2"),
            _occurrence("occ-attended", FUTURE),
            _occurrence("occ-on-payout-line", FUTURE),
            # Already cancelled — not work.
            _occurrence("occ-already-cancelled", FUTURE, status="cancelled"),
            # Belongs to a session that is still running.
            _occurrence(
                "occ-live-session",
                FUTURE,
                session_id="sess-live",
                template_session_id="sess-live",
            ),
        ]
    )
    await db.attendance.insert_one(
        {
            "academy_id": ACADEMY,
            "occurrence_id": "occ-past",
            "student_id": "student-1",
            "status": "present",
        }
    )
    await db.coach_attendance.insert_one(
        {
            "academy_id": ACADEMY,
            "occurrence_id": "occ-attended",
            "coach_id": "coach-1",
            "status": "present",
            "role": "lead",
        }
    )
    await db.payout_period_lines.insert_one(
        {
            "academy_id": ACADEMY,
            "occurrence_id": "occ-on-payout-line",
            "coach_id": "coach-1",
            "amount_minor": 4000,
        }
    )


async def _status_of(db, occurrence_id: str) -> str:
    doc = await db.session_occurrences.find_one({"occurrence_id": occurrence_id})
    assert doc is not None
    return str(doc["status"])


@pytest.mark.asyncio
async def test_finder_reports_only_cancelled_sessions_with_live_future_occurrences(db) -> None:
    await _seed(db)

    rows = await find_half_cancelled_sessions(db, now=NOW)

    assert [r["session_id"] for r in rows] == ["sess-cancelled"]
    # occ-clean, occ-clean-far, occ-coach-assigned, occ-attended,
    # occ-on-payout-line. Not the past one, not the already-cancelled one,
    # not the live session's occurrence.
    assert rows[0]["future_scheduled"] == 5
    assert rows[0]["academy_id"] == ACADEMY


@pytest.mark.asyncio
async def test_dry_run_is_the_default_and_writes_nothing(db) -> None:
    await _seed(db)
    before = await db.session_occurrences.find({}).to_list(length=None)

    result = await recancel_half_cancelled_sessions(db, apply=False, now=NOW)

    assert result["applied"] is False
    assert result["sessions_found"] == 1
    assert result["before_total"] == 5
    assert result["occurrences_cancelled"] == 0

    after = await db.session_occurrences.find({}).to_list(length=None)
    assert {d["occurrence_id"]: d["status"] for d in after} == {
        d["occurrence_id"]: d["status"] for d in before
    }
    # Not one occurrence was soft-cancelled by the dry run.
    assert all("cancellation_reason" not in d for d in after)


@pytest.mark.asyncio
async def test_apply_cancels_only_the_clean_future_occurrences(db) -> None:
    await _seed(db)

    result = await recancel_half_cancelled_sessions(db, apply=True, now=NOW)

    assert result["applied"] is True
    assert result["failed"] == []
    assert result["sessions_repaired"] == 1
    assert result["occurrences_cancelled"] == 2
    assert result["before_total"] == 5
    assert result["after_total"] == 3

    # Repaired: soft-cancelled with the cascade's own reason, including the
    # occurrence past the 60-day maintenance window.
    for occurrence_id in ("occ-clean", "occ-clean-far"):
        doc = await db.session_occurrences.find_one({"occurrence_id": occurrence_id})
        assert doc is not None, occurrence_id
        assert doc["status"] == "cancelled", occurrence_id
        assert doc["cancellation_reason"] == "session_cancelled", occurrence_id

    # Untouched: history and anything already acted on or paid.
    assert await _status_of(db, "occ-past") == "scheduled"
    assert await _status_of(db, "occ-coach-assigned") == "scheduled"
    assert await _status_of(db, "occ-attended") == "scheduled"
    assert await _status_of(db, "occ-on-payout-line") == "scheduled"
    # A live session is never collateral damage.
    assert await _status_of(db, "occ-live-session") == "scheduled"

    # Soft cancel only — nothing is ever deleted.
    assert await db.session_occurrences.count_documents({}) == 8


@pytest.mark.asyncio
async def test_second_apply_run_is_a_no_op(db) -> None:
    await _seed(db)

    first = await recancel_half_cancelled_sessions(db, apply=True, now=NOW)
    assert first["occurrences_cancelled"] == 2

    second = await recancel_half_cancelled_sessions(db, apply=True, now=NOW)

    assert second["occurrences_cancelled"] == 0
    assert second["sessions_repaired"] == 0
    assert second["failed"] == []
    assert second["before_total"] == second["after_total"] == 3

    third = await recancel_half_cancelled_sessions(db, apply=True, now=NOW)
    assert third["occurrences_cancelled"] == 0


# --- the flag itself is a safety control, so it gets its own tests ----------


def test_no_flag_means_dry_run() -> None:
    args = build_arg_parser().parse_args([])
    assert apply_requested(args) is False


def test_apply_flag_is_the_only_way_to_enable_writes() -> None:
    args = build_arg_parser().parse_args(["--apply"])
    assert apply_requested(args) is True


def test_dry_run_wins_when_both_flags_are_passed() -> None:
    args = build_arg_parser().parse_args(["--apply", "--dry-run"])
    assert apply_requested(args) is False


@pytest.mark.parametrize("flag", ["--aply", "--Apply", "--apply-all", "-apply"])
def test_misspelled_apply_flag_never_enables_writes(flag: str) -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args([flag])
