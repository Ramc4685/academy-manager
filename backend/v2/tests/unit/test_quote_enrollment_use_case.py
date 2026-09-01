"""Unit tests for QuoteEnrollment use case (in-memory fakes, no Mongo)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.quote_enrollment import (
    QuoteEnrollment,
    QuoteEnrollmentCommand,
)
from backend.v2.contexts.billing.domain.errors import PaymentNotFound
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
)

# ---------------------------------------------------------------------------
# In-memory port fakes
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 18, 22, 0, tzinfo=UTC)

_SESSION_DOC: dict[str, Any] = {
    "session_id": "sess-1",
    "timezone": "America/Chicago",
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "days_of_week": ["Mon", "Fri"],
    "start_time": "18:00",
    "end_time": "19:00",
    "monthly_price_cents": 10_000,
}


class _FakeSessionLoader:
    def __init__(self, doc: dict | None) -> None:
        self._doc = doc

    async def get_by_id(self, session_id: str) -> dict | None:
        if self._doc and self._doc.get("session_id") == session_id:
            return self._doc
        return None


class _FakeOccurrenceCatalog:
    def __init__(self, occurrences: list[ClassOccurrence]) -> None:
        self._occurrences = occurrences

    async def list_for_session(
        self, session_doc: dict, period: BillingPeriod
    ) -> list[ClassOccurrence]:
        return self._occurrences


class _FakeSnapshotWriter:
    def __init__(self) -> None:
        self.stored: list[BillingCalculationSnapshot] = []
        self.consumed_ids: list[str] = []

    async def persist_open(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        session_id: str,
        parent_id: str | None,
        student_id: str | None,
        enrollment_id: str | None,
        ttl_minutes: int,
        now: datetime,
    ) -> BillingCalculationSnapshot:
        from datetime import timedelta

        from backend.v2.shared.ids import new_ulid

        stored = snapshot.model_copy(
            update={
                "snapshot_id": str(new_ulid()),
                "status": "OPEN",
                "expires_at": now + timedelta(minutes=ttl_minutes),
            }
        )
        self.stored.append(stored)
        return stored

    async def consume(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        self.consumed_ids.append(snapshot_id)
        return None

    async def persist_consumed_first_month(self, **_kwargs):
        return "fake-snap-id"

    async def persist_monthly_tuition(self, **_kwargs):
        return "fake-snap-id"


def _make_occurrences(days: list[int]) -> list[ClassOccurrence]:
    return [
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-05-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 5, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, day, 23, 59, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in days
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quote_enrollment_returns_open_snapshot() -> None:
    """QuoteEnrollment should produce an OPEN BillingCalculationSnapshot."""
    # 9 class days in May; billing starts May 18 so 3 remain after cutoff.
    occ_days = [1, 4, 8, 11, 15, 18, 22, 25, 29]
    occurrences = _make_occurrences(occ_days)

    sessions = _FakeSessionLoader(_SESSION_DOC)
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog(occurrences)

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _NOW,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
            calculated_by="parent-1",
            parent_id="parent-1",
        )
    )

    assert result.status == "OPEN"
    assert result.snapshot_id is not None
    assert result.monthly_price_cents == 10_000
    assert result.total_eligible_classes == 9
    # 22nd, 25th, 29th are after cutoff; 18th is SAME_DAY_CUTOFF (< 2 hours)
    assert result.billable_remaining_classes == 3
    assert len(snapshots.stored) == 1
    assert snapshots.stored[0].snapshot_id == result.snapshot_id


@pytest.mark.asyncio
async def test_quote_enrollment_raises_if_session_not_found() -> None:
    """QuoteEnrollment must raise PaymentNotFound when the session is absent."""
    sessions = _FakeSessionLoader(None)
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
    )
    with pytest.raises(PaymentNotFound):
        await uc.execute(
            QuoteEnrollmentCommand(
                session_id="nonexistent",
                billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
                calculated_by="admin",
            )
        )


@pytest.mark.asyncio
async def test_quote_enrollment_uses_session_timezone() -> None:
    """Timezone from session doc must flow into the BillingPeriod."""
    session_doc = {**_SESSION_DOC, "timezone": "America/New_York"}
    sessions = _FakeSessionLoader(session_doc)
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _NOW,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
            calculated_by="admin",
        )
    )
    assert result.timezone == "America/New_York"


@pytest.mark.asyncio
async def test_quote_enrollment_zero_classes_yields_zero_amount() -> None:
    """Empty occurrence list → final_amount_cents is 0, snapshot still stored."""
    sessions = _FakeSessionLoader(_SESSION_DOC)
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _NOW,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 5, 31, 15, 0, tzinfo=UTC),
            calculated_by="admin",
        )
    )
    assert result.final_amount_cents == 0
    assert result.status == "OPEN"


# ---------------------------------------------------------------------------
# #541 — the period label must be session-local, not UTC
# ---------------------------------------------------------------------------

# 8:15pm CDT on Aug 31 2026 is already 00:15 UTC on Sep 1: the five evening
# hours in which a UTC-derived label disagrees with the session-local period
# bounds it is supposed to describe.
_MONTH_END_EVENING_CHICAGO = datetime(2026, 9, 1, 0, 15, tzinfo=UTC)


def _august_chicago_occurrences() -> list[ClassOccurrence]:
    """Four Monday evening classes plus a late one on Aug 31, all local-August."""
    rows = [
        # Mon 6:00pm CDT -> 23:00 UTC the same day.
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-08-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 8, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 8, day, 23, 59, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in (3, 10, 17, 24)
    ]
    # Mon Aug 31, 9:30pm CDT -> 02:30 UTC on Sep 1. Still August locally, and
    # far enough out to clear the 2h same-day cutoff from the 8:15pm quote.
    rows.append(
        ClassOccurrence(
            occurrence_id="sess-1:2026-08-31:21:30",
            session_id="sess-1",
            start_at=datetime(2026, 9, 1, 2, 30, tzinfo=UTC),
            end_at=datetime(2026, 9, 1, 3, 30, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
    )
    return rows


@pytest.mark.asyncio
async def test_month_end_evening_quote_labels_the_local_month() -> None:
    """A month-end evening checkout for a US tenant must quote the LOCAL month.

    Regression for #541: the label was derived from the UTC instant while
    ``BillingPeriod.from_label`` builds the bounds in the session timezone, so
    an 8:15pm Chicago quote on Aug 31 was labelled "2026-09". That skipped the
    remaining August class entirely (September has no occurrences yet), and
    priced the parent's "first month" against the wrong month.
    """
    sessions = _FakeSessionLoader(_SESSION_DOC)  # America/Chicago
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog(_august_chicago_occurrences())

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _MONTH_END_EVENING_CHICAGO,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=_MONTH_END_EVENING_CHICAGO,
            calculated_by="parent-1",
        )
    )

    assert result.billing_period_label == "2026-08"
    # Bounds are local August, and the label agrees with them.
    assert result.billing_period_start.astimezone(UTC) == datetime(2026, 8, 1, 5, 0, tzinfo=UTC)
    assert result.billing_period_end.astimezone(UTC) == datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
    # All five August classes are eligible; only the 9:30pm one is still
    # billable, so the parent is prorated 1/5 of August instead of being
    # quoted a phantom September.
    assert result.total_eligible_classes == 5
    assert result.billable_remaining_classes == 1
    assert result.proration_ratio == "1/5"
    assert result.final_amount_cents == 2_000


@pytest.mark.asyncio
async def test_month_end_evening_quote_keeps_utc_month_for_a_utc_session() -> None:
    """The local-month rule is a no-op for a session that really is on UTC."""
    sessions = _FakeSessionLoader({**_SESSION_DOC, "timezone": "UTC"})
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _MONTH_END_EVENING_CHICAGO,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=_MONTH_END_EVENING_CHICAGO,
            calculated_by="parent-1",
        )
    )

    assert result.billing_period_label == "2026-09"


@pytest.mark.asyncio
async def test_naive_billing_start_is_read_as_a_utc_instant() -> None:
    """Mongo round-trips drop tzinfo; a naive start must not crash or shift."""
    sessions = _FakeSessionLoader(_SESSION_DOC)  # America/Chicago
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: _MONTH_END_EVENING_CHICAGO,
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 9, 1, 0, 15),  # naive == UTC
            calculated_by="parent-1",
        )
    )

    assert result.billing_period_label == "2026-08"


def _september_pacific_occurrences() -> list[ClassOccurrence]:
    """Four Tuesday 6pm classes in LOCAL September for a Los Angeles session.

    Sep 1 2026 is a Tuesday, so the September Tuesdays are the 1st, 8th, 15th
    and 22nd (plus the 29th). 6pm PDT is 01:00 UTC the following day.
    """
    rows: list[ClassOccurrence] = []
    for day in (1, 8, 15, 22, 29):
        rows.append(
            ClassOccurrence(
                occurrence_id=f"sess-la:2026-09-{day:02d}:18:00",
                session_id="sess-la",
                start_at=datetime(2026, 9, day + 1, 1, 0, tzinfo=UTC),
                end_at=datetime(2026, 9, day + 1, 2, 0, tzinfo=UTC),
                status="scheduled",
                is_billable=True,
                timezone="America/Los_Angeles",
            )
        )
    return rows


@pytest.mark.asyncio
async def test_explicit_start_date_resolves_in_the_session_timezone() -> None:
    """An explicit start date must be local midnight of the SESSION's zone.

    Regression for the first remediation of #541. The composition layer used
    to pin a caller-supplied ``start_date`` to ``America/Chicago`` midnight
    and pass the resulting instant down as ``billing_start_at``. Once the
    period label began reading that instant in the *session's* timezone, that
    hardcoded Chicago midnight landed on the previous day for every session
    west of Chicago — 2026-09-01 00:00 CDT is 2026-08-31 22:00 PDT — so a
    Los Angeles academy asking for a September 1st start was quoted the
    already-generated month of August, in which every class precedes the
    billing start. The quote silently collapsed to $0.00.

    The calendar date now travels down as a ``date`` and is resolved against
    the session's own clock, so the label, the bounds and the proration
    cutoff all agree in every timezone.
    """
    session_doc = {
        **_SESSION_DOC,
        "session_id": "sess-la",
        "timezone": "America/Los_Angeles",
    }
    sessions = _FakeSessionLoader(session_doc)
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog(_september_pacific_occurrences())

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-la",
            billing_start_at=datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
            billing_start_date=date(2026, 9, 1),
            calculated_by="admin",
        )
    )

    assert result.billing_period_label == "2026-09"
    # Local September bounds: Sep 1 00:00 PDT == 07:00 UTC.
    assert result.billing_period_start.astimezone(UTC) == datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
    assert result.billing_period_end.astimezone(UTC) == datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
    # Every September class is on or after local midnight Sep 1, so a full
    # month is quoted rather than the $0 that a stale August period produced.
    assert result.total_eligible_classes == 5
    assert result.billable_remaining_classes == 5
    assert result.proration_ratio == "5/5"
    assert result.final_amount_cents == 10_000


@pytest.mark.asyncio
async def test_explicit_start_date_is_unchanged_for_a_chicago_session() -> None:
    """The same start date on a Chicago session keeps its pre-existing bounds."""
    sessions = _FakeSessionLoader(_SESSION_DOC)  # America/Chicago
    snapshots = _FakeSnapshotWriter()
    occurrences_catalog = _FakeOccurrenceCatalog([])

    uc = QuoteEnrollment(
        sessions=sessions,
        snapshots=snapshots,
        occurrences=occurrences_catalog,
        clock=lambda: datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
    )
    result = await uc.execute(
        QuoteEnrollmentCommand(
            session_id="sess-1",
            billing_start_at=datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
            billing_start_date=date(2026, 9, 1),
            calculated_by="admin",
        )
    )

    assert result.billing_period_label == "2026-09"
    assert result.billing_period_start.astimezone(UTC) == datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
