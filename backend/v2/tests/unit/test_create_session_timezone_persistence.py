"""A created session must record the zone its instants were computed in.

`CreateSession` derives the representative `start_at`/`end_at` from the local
wall-clock `start_time`, but used to persist ``cmd.timezone`` verbatim — so
omitting the field produced a document whose instants were derived from a
hardcoded default and whose `timezone` was null. Every downstream reader
(occurrence synthesis, monthly billing, payroll) re-derives occurrences from
that field, so a null there means the document is only interpretable while each
reader's private default keeps agreeing.

The zone is now resolved from the TENANT (`academies.timezone`), and a tenant
with no zone fails the write closed rather than guessing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    AcademyTimezoneUnset,
    CreateSession,
    CreateSessionCommand,
)
from backend.v2.contexts.enrollment.domain.models import Session


class _StubSessionWriter:
    def __init__(self) -> None:
        self.created: list[Session] = []

    async def create(self, session: Session) -> None:
        self.created.append(session)

    async def find_duplicate_recurring_series(self, **_: object) -> Session | None:
        return None


def _reader(value: str | None):
    async def get_academy_timezone(_academy_id: str) -> str | None:
        return value

    return get_academy_timezone


def _use_case(writer: _StubSessionWriter, academy_timezone: str | None) -> CreateSession:
    return CreateSession(
        sessions=writer,  # type: ignore[arg-type]
        academy_id="acad-1",
        get_academy_timezone=_reader(academy_timezone),
    )


def _command(**overrides: object) -> CreateSessionCommand:
    payload: dict[str, object] = {
        "coach_id": "coach-1",
        "title": "Thursday 6:00 PM Intermediate",
        "location": "Court 1",
        "capacity": 10,
        "days_of_week": ["Thu"],
        "start_time": "18:00",
        "end_time": "18:45",
    }
    payload.update(overrides)
    return CreateSessionCommand(**payload)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_omitted_timezone_resolves_from_the_tenant() -> None:
    """The reported prod bug, from the write side.

    With no explicit zone the session must take the ACADEMY's zone, and an
    18:00 Chicago class must be stored as 23:00Z — not 18:00Z, which is what
    rendered as "1:00 PM" on the parent's Review & pay screen.
    """
    writer = _StubSessionWriter()

    await _use_case(writer, "America/Chicago").execute(_command())

    created = writer.created[0]
    assert created.timezone == "America/Chicago"
    assert created.start_at.astimezone(UTC).hour == 23


@pytest.mark.asyncio
async def test_tenant_without_a_timezone_fails_closed_and_writes_nothing() -> None:
    writer = _StubSessionWriter()

    with pytest.raises(AcademyTimezoneUnset):
        await _use_case(writer, None).execute(_command())

    assert writer.created == []


@pytest.mark.asyncio
async def test_explicit_timezone_beats_the_academy_zone() -> None:
    """Multi-location: a session may legitimately sit in another zone."""
    writer = _StubSessionWriter()

    await _use_case(writer, "America/Chicago").execute(_command(timezone="Asia/Kolkata"))

    assert writer.created[0].timezone == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_invalid_timezone_is_rejected_at_the_write_boundary() -> None:
    writer = _StubSessionWriter()

    with pytest.raises(AcademyTimezoneUnset):
        await _use_case(writer, None).execute(_command(timezone="Not/AZone"))

    assert writer.created == []


@pytest.mark.asyncio
async def test_persisted_timezone_matches_the_zone_start_at_was_derived_in() -> None:
    """The stored instant and the stored zone must agree.

    18:00 local in the persisted zone must round-trip back to 18:00 — if the
    document claimed a different zone than the one used for the arithmetic, the
    class would appear to move.
    """
    writer = _StubSessionWriter()

    await _use_case(writer, "America/Chicago").execute(_command())

    created = writer.created[0]
    assert created.start_at.tzinfo is not None
    local = created.start_at.astimezone(ZoneInfo(created.timezone or ""))
    assert (local.hour, local.minute) == (18, 0)
    # And it is a genuine UTC instant, not a naive wall clock relabelled.
    assert created.start_at.astimezone(UTC) != datetime(
        created.start_at.year,
        created.start_at.month,
        created.start_at.day,
        18,
        0,
        tzinfo=UTC,
    )
