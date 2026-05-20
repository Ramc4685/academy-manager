"""Unit tests for QuoteEnrollment use case (in-memory fakes, no Mongo)."""

from __future__ import annotations

from datetime import datetime, timezone
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

_NOW = datetime(2026, 5, 18, 22, 0, tzinfo=timezone.utc)

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
        from ulid import ULID
        from datetime import timedelta

        stored = snapshot.model_copy(
            update={
                "snapshot_id": str(ULID()),
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
            start_at=datetime(2026, 5, day, 23, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, day, 23, 59, tzinfo=timezone.utc),
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
            billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
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
                billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
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
            billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
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
            billing_start_at=datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
            calculated_by="admin",
        )
    )
    assert result.final_amount_cents == 0
    assert result.status == "OPEN"
