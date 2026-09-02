"""Regression coverage for the parent catalog's timezone contract.

A parent on "Review & pay" was shown a 6:00 PM class as "1:00 PM" — the wrong
hour on the screen where they commit to paying. Two defects made that possible
and both are guarded here:

1. ``start_at``/``end_at`` came back from Motor *naive* for stored dated rows
   (the client is built without ``tz_aware=True``) while rows synthesized in
   Python were aware. Serialized, one array carried both ``...Z`` and
   offset-less strings, which JS parses with opposite meanings.
2. The row carried no timezone at all, so no client could render the academy's
   hour even if it wanted to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    LEGACY_FALLBACK_TIMEZONE,
    synthesize_recurring_session_docs,
)
from backend.v2.interfaces.parent.views import ParentAvailableSessionView
from backend.v2.shared.time import ensure_utc

RANGE_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
RANGE_END = datetime(2026, 9, 30, 23, 59, tzinfo=UTC)


def test_ensure_utc_stamps_naive_mongo_datetime() -> None:
    naive = datetime(2026, 9, 3, 23, 0)
    assert ensure_utc(naive) == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)


def test_ensure_utc_normalizes_an_offset_aware_datetime() -> None:
    chicago = datetime(2026, 9, 3, 23, 0, tzinfo=UTC).astimezone(ZoneInfo("America/Chicago"))
    assert ensure_utc(chicago) == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)


def test_catalog_view_serializes_utc_instants_with_a_z_suffix() -> None:
    """A naive datetime serializes offset-less; JS then reads it as LOCAL."""
    naive = ParentAvailableSessionView(
        session_id="s1",
        title="Thursday 6:00 PM Intermediate",
        location="Court 1",
        start_at=datetime(2026, 9, 3, 23, 0),
        end_at=datetime(2026, 9, 3, 23, 45),
        capacity=10,
        enrolled_count=0,
        available_seats=10,
        amount_cents=15000,
    )
    assert "2026-09-03T23:00:00Z" not in naive.model_dump_json()

    stamped = naive.model_copy(
        update={
            "start_at": ensure_utc(naive.start_at),
            "end_at": ensure_utc(naive.end_at),
        }
    )
    payload = stamped.model_dump_json()
    assert '"start_at":"2026-09-03T23:00:00Z"' in payload
    assert '"end_at":"2026-09-03T23:45:00Z"' in payload


def test_catalog_view_carries_the_session_timezone() -> None:
    view = ParentAvailableSessionView(
        session_id="s1",
        title="Thursday 6:00 PM Intermediate",
        location="Court 1",
        start_at=datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 3, 23, 45, tzinfo=UTC),
        timezone="America/Chicago",
        capacity=10,
        enrolled_count=0,
        available_seats=10,
        amount_cents=15000,
    )
    assert '"timezone":"America/Chicago"' in view.model_dump_json()


def test_catalog_view_timezone_defaults_to_null_not_utc() -> None:
    """Null means "unknown, fall back to the academy zone" — never "UTC"."""
    view = ParentAvailableSessionView(
        session_id="s1",
        title="Session",
        location="Court 1",
        start_at=datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 3, 23, 45, tzinfo=UTC),
        capacity=10,
        enrolled_count=0,
        available_seats=10,
        amount_cents=15000,
    )
    assert view.timezone is None


def _template(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "_id": "oid-tpl-1",
        "academy_id": "academy-b",
        "session_id": "tpl-1",
        "name": "Thursday 6:00 PM Intermediate",
        "location": "Court 1",
        "coach_id": "coach-1",
        "max_students": 10,
        "days_of_week": ["Thu"],
        "start_time": "18:00",
        "end_time": "18:45",
        "timezone": "America/Chicago",
    }
    doc.update(overrides)
    return doc


def test_synthesized_rows_are_utc_instants_of_the_local_wall_clock() -> None:
    """18:00 America/Chicago on 2026-09-03 (CDT, UTC-5) is 23:00Z."""
    rows = synthesize_recurring_session_docs(
        [_template()],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
    )
    assert len(rows) == 1
    assert rows[0]["start_at"] == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)
    assert rows[0]["end_at"] == datetime(2026, 9, 3, 23, 45, tzinfo=UTC)


def test_synthesized_row_reports_the_zone_its_instants_were_computed_in() -> None:
    """A template with no `timezone` still tells consumers which zone was used.

    Otherwise the row's instants are only interpretable by a client that
    happens to share this module's private default.
    """
    rows = synthesize_recurring_session_docs(
        [_template(timezone=None)],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
    )
    assert len(rows) == 1
    assert rows[0]["timezone"] == LEGACY_FALLBACK_TIMEZONE
    # And the instants match that zone, not UTC: 18:00 CDT == 23:00Z.
    assert rows[0]["start_at"] == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)


def test_null_template_zone_falls_back_to_the_academy_not_the_module_constant() -> None:
    """Reads must never raise, but they must still ask the TENANT first.

    A legacy row with no `timezone` is expanded in the academy's zone; the
    single-tenant module constant is only the last rung.
    """
    rows = synthesize_recurring_session_docs(
        [_template(timezone=None)],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
        fallback_timezone="Asia/Kolkata",
    )
    assert rows[0]["timezone"] == "Asia/Kolkata"
    # 18:00 IST (UTC+5:30) on 2026-09-03 is 12:30Z.
    assert rows[0]["start_at"] == datetime(2026, 9, 3, 12, 30, tzinfo=UTC)


def test_template_zone_beats_the_academy_fallback() -> None:
    rows = synthesize_recurring_session_docs(
        [_template(timezone="America/Chicago")],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
        fallback_timezone="Asia/Kolkata",
    )
    assert rows[0]["timezone"] == "America/Chicago"


def test_utc_timezone_field_is_honoured_and_shifts_the_class_five_hours() -> None:
    """Pins the exact production symptom.

    A session document whose `timezone` says "UTC" while its title says
    6:00 PM is stored at 18:00Z — which is 1:00 PM in Chicago. The synthesizer
    is faithful to the field; the defect is the *field*, written by an admin
    form that used to default to the literal "UTC".
    """
    rows = synthesize_recurring_session_docs(
        [_template(timezone="UTC")],
        range_start=RANGE_START,
        range_end=RANGE_END,
        first_per_template=True,
    )
    assert rows[0]["start_at"] == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
    assert rows[0]["timezone"] == "UTC"
