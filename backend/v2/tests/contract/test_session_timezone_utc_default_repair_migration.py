"""Coverage for the 0160 session-timezone repair.

The dominant risk in this migration is the *false positive*: rewriting a row
that is genuinely UTC. Most of these tests exist to pin that down.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0160_session_timezone_utc_default_repair"


@pytest.fixture
def migration():
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    return importlib.import_module(MODULE_NAME)


async def _insert_academy(db, academy_id: str, timezone: str | None) -> None:
    doc = {"academy_id": academy_id, "display_name": academy_id}
    if timezone is not None:
        doc["timezone"] = timezone
    await db["academies"].insert_one(doc)


async def _insert_utc_defaulted_session(
    db,
    *,
    academy_id: str = "acad-chi",
    session_id: str = "sess-1",
    start_time: str = "18:00",
    end_time: str = "18:45",
    day: str = "Thu",
    # 2026-09-03 is a Thursday. Written as the buggy code would: the admin's
    # local wall clock, stamped as if it were UTC.
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": academy_id,
            "session_id": session_id,
            "coach_id": "coach-1",
            "title": "Thursday 6:00 PM",
            "location": "Court 1",
            "capacity": 10,
            "status": "scheduled",
            "days_of_week": [day],
            "start_time": start_time,
            "end_time": end_time,
            "timezone": "UTC",
            "start_at": start_at or datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
            "end_at": end_at or datetime(2026, 9, 3, 18, 45, tzinfo=UTC),
        }
    )


@pytest.mark.asyncio
async def test_repairs_a_wrongly_defaulted_row(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)

    report = await migration.repair(db, dry_run=False)

    assert len(report.sessions_changed) == 1
    doc = await db["sessions"].find_one({"session_id": "sess-1"})
    assert doc["timezone"] == "America/Chicago"
    # 6:00 PM Chicago on 2026-09-03 (CDT, UTC-5) is 23:00Z the same day.
    assert doc["start_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)
    assert doc["end_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 23, 45, tzinfo=UTC)


@pytest.mark.asyncio
async def test_dry_run_reports_without_writing(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)

    report = await migration.repair(db, dry_run=True)

    assert report.dry_run is True
    assert len(report.sessions_changed) == 1
    change = report.sessions_changed[0]
    assert change.old_start_at == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
    assert change.new_start_at == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)

    doc = await db["sessions"].find_one({"session_id": "sess-1"})
    assert doc["timezone"] == "UTC"
    assert doc["start_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_leaves_a_legitimately_utc_row_alone(db, migration) -> None:
    """The academy really is UTC, so "UTC" on the session is not evidence of a bug."""
    await _insert_academy(db, "acad-utc", "UTC")
    await _insert_utc_defaulted_session(db, academy_id="acad-utc", session_id="sess-utc")

    report = await migration.repair(db, dry_run=False)

    assert report.sessions_changed == []
    assert "acad-utc/sess-utc" in report.skipped["academy_timezone_is_utc"]
    doc = await db["sessions"].find_one({"session_id": "sess-utc"})
    assert doc["timezone"] == "UTC"
    assert doc["start_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_skips_and_reports_a_session_whose_academy_has_no_timezone(db, migration) -> None:
    await _insert_academy(db, "acad-null", None)
    await _insert_utc_defaulted_session(db, academy_id="acad-null", session_id="sess-null")

    report = await migration.repair(db, dry_run=False)

    assert report.sessions_changed == []
    assert report.skipped["academy_timezone_missing"] == ["acad-null/sess-null"]
    doc = await db["sessions"].find_one({"session_id": "sess-null"})
    assert doc["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_rerunning_changes_nothing(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)

    first = await migration.repair(db, dry_run=False)
    assert len(first.sessions_changed) == 1
    after_first = await db["sessions"].find_one({"session_id": "sess-1"})

    second = await migration.repair(db, dry_run=False)

    assert second.sessions_changed == []
    assert second.sessions_scanned == 0  # timezone is no longer "UTC"
    after_second = await db["sessions"].find_one({"session_id": "sess-1"})
    assert after_second["start_at"] == after_first["start_at"]
    assert after_second["end_at"] == after_first["end_at"]
    assert after_second["timezone"] == "America/Chicago"


@pytest.mark.asyncio
async def test_skips_a_row_whose_instants_do_not_match_the_utc_default(db, migration) -> None:
    """A row some other path wrote is not provably mis-defaulted."""
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(
        db,
        session_id="sess-odd",
        # 20:15Z does not correspond to the 18:00 wall clock the bug would stamp.
        start_at=datetime(2026, 9, 3, 20, 15, tzinfo=UTC),
        end_at=datetime(2026, 9, 3, 21, 0, tzinfo=UTC),
    )

    report = await migration.repair(db, dry_run=False)

    assert report.sessions_changed == []
    assert report.skipped["session_not_utc_default_shaped"] == ["acad-chi/sess-odd"]


@pytest.mark.asyncio
async def test_skips_a_dated_one_off_session(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await db["sessions"].insert_one(
        {
            "academy_id": "acad-chi",
            "session_id": "sess-dated",
            "title": "One-off clinic",
            "timezone": "UTC",
            "start_at": datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
            "end_at": datetime(2026, 9, 3, 19, 0, tzinfo=UTC),
        }
    )

    report = await migration.repair(db, dry_run=False)

    assert report.sessions_changed == []
    assert report.skipped["session_not_recurring"] == ["acad-chi/sess-dated"]


@pytest.mark.asyncio
async def test_does_not_apply_a_fixed_offset_across_dst(db, migration) -> None:
    """A January occurrence is CST (-6); a September one is CDT (-5)."""
    await _insert_academy(db, "acad-chi", "America/Chicago")
    # 2027-01-07 is a Thursday.
    await _insert_utc_defaulted_session(
        db,
        session_id="sess-winter",
        start_at=datetime(2027, 1, 7, 18, 0, tzinfo=UTC),
        end_at=datetime(2027, 1, 7, 18, 45, tzinfo=UTC),
    )

    await migration.repair(db, dry_run=False)

    doc = await db["sessions"].find_one({"session_id": "sess-winter"})
    assert doc["start_at"].replace(tzinfo=UTC) == datetime(2027, 1, 8, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_repairs_clean_future_occurrences_and_leaves_settled_ones(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    for occurrence_id, start, end in (
        # Future and clean -> repaired.
        (
            "sess-1:2026-09-03:18:00",
            datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
            datetime(2026, 9, 3, 18, 45, tzinfo=UTC),
        ),
        # Already happened -> history, left alone.
        (
            "sess-1:2026-08-27:18:00",
            datetime(2026, 8, 27, 18, 0, tzinfo=UTC),
            datetime(2026, 8, 27, 18, 45, tzinfo=UTC),
        ),
    ):
        await db["session_occurrences"].insert_one(
            {
                "academy_id": "acad-chi",
                "occurrence_id": occurrence_id,
                "session_id": "sess-1",
                "template_session_id": "sess-1",
                "start_at": start,
                "end_at": end,
                "status": "scheduled",
                "is_billable": True,
            }
        )

    report = await migration.repair(db, dry_run=False, now=now)

    assert [c.doc_key for c in report.occurrences_changed] == ["sess-1:2026-09-03:18:00"]
    assert "acad-chi/sess-1:2026-08-27:18:00" in report.skipped["occurrence_past_or_settled"]

    future = await db["session_occurrences"].find_one({"occurrence_id": "sess-1:2026-09-03:18:00"})
    assert future["start_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)
    past = await db["session_occurrences"].find_one({"occurrence_id": "sess-1:2026-08-27:18:00"})
    assert past["start_at"].replace(tzinfo=UTC) == datetime(2026, 8, 27, 18, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_leaves_an_attended_future_occurrence_alone(db, migration) -> None:
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    await db["session_occurrences"].insert_one(
        {
            "academy_id": "acad-chi",
            "occurrence_id": "sess-1:2026-09-03:18:00",
            "session_id": "sess-1",
            "start_at": datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
            "end_at": datetime(2026, 9, 3, 18, 45, tzinfo=UTC),
            "status": "scheduled",
        }
    )
    await db["payout_period_lines"].insert_one(
        {"academy_id": "acad-chi", "occurrence_id": "sess-1:2026-09-03:18:00"}
    )

    report = await migration.repair(db, dry_run=False, now=now)

    assert report.occurrences_changed == []
    assert "acad-chi/sess-1:2026-09-03:18:00" in report.skipped["occurrence_past_or_settled"]


@pytest.mark.asyncio
async def test_up_is_report_only_without_the_apply_flag(db, migration, monkeypatch) -> None:
    monkeypatch.delenv(migration.APPLY_ENV_VAR, raising=False)
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)

    await migration.up(db)

    doc = await db["sessions"].find_one({"session_id": "sess-1"})
    assert doc["timezone"] == "UTC"
    assert doc["start_at"].replace(tzinfo=UTC) == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_up_writes_when_the_apply_flag_is_set(db, migration, monkeypatch) -> None:
    monkeypatch.setenv(migration.APPLY_ENV_VAR, "1")
    await _insert_academy(db, "acad-chi", "America/Chicago")
    await _insert_utc_defaulted_session(db)

    await migration.up(db)

    doc = await db["sessions"].find_one({"session_id": "sess-1"})
    assert doc["timezone"] == "America/Chicago"
