"""Credit a missed class (#1207): a PAST date recorded as no class.

Same use case as a pre-class call-off (``CancelSessionOccurrence``) so the
occurrence CAS, the billing sync and the lifecycle events are the ones a
called-off date gets. The fakes are shared with the call-off tests; the
occurrence CAS refuses anything but a ``scheduled`` row, as Mongo does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
    CancelSessionOccurrenceCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    MissedClassHadAttendance,
    OccurrenceAlreadyCancelled,
    OccurrenceNotPast,
)
from backend.v2.tests.application.test_cancel_session_occurrence import (
    NOW,
    FakeEnrollments,
    FakeEvents,
    FakeNotifier,
    FakeOccurrences,
    FakePayoutLock,
    FakeSessions,
    _enrollment,
    _occurrence,
    _session,
)

PAST = NOW - timedelta(days=5)


@dataclass
class FakeAttendance:
    present: dict[str, int] = field(default_factory=dict)

    async def present_count(self, occurrence_id: str) -> int:
        return self.present.get(occurrence_id, 0)


@dataclass
class FakeBillingWithPreview:
    """Mirrors the adapter: ``preview`` prices, ``apply`` writes."""

    applied: list[dict[str, Any]] = field(default_factory=list)
    previewed: list[dict[str, Any]] = field(default_factory=list)

    _families: tuple[dict[str, Any], ...] = (
        {"enrollment_id": "enr-1", "amount_cents": 3000, "outcome": "would_credit"},
        {"enrollment_id": "enr-2", "amount_cents": 0, "outcome": "skipped:covered_by_free_classes"},
    )

    async def preview(self, **kwargs: Any) -> dict[str, Any]:
        self.previewed.append(kwargs)
        return {
            "families": list(self._families),
            "credited_cents": 3000,
            "skip_counts": {"covered_by_free_classes": 1},
        }

    async def apply(self, **kwargs: Any) -> dict[str, Any]:
        self.applied.append(kwargs)
        return {
            "billing_result": "credited=1,skipped=1,override=written",
            "credits": {"enr-1": "cr-1"},
            "credited_cents": 3000,
            "skip_counts": {"covered_by_free_classes": 1},
        }


def _build(
    occurrences: FakeOccurrences,
    *,
    attendance: FakeAttendance | None = None,
    billing: FakeBillingWithPreview | None = None,
    payout_lock: FakePayoutLock | None = None,
    events: FakeEvents | None = None,
    notifier: FakeNotifier | None = None,
) -> CancelSessionOccurrence:
    return CancelSessionOccurrence(
        occurrences=occurrences,  # type: ignore[arg-type]
        sessions=FakeSessions({"sess-1": _session()}),  # type: ignore[arg-type]
        enrollments=FakeEnrollments(  # type: ignore[arg-type]
            [_enrollment("enr-1", "st-1"), _enrollment("enr-2", "st-2")]
        ),
        enrollment_events=events,  # type: ignore[arg-type]
        billing_sync=billing,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        payout_lock=payout_lock,  # type: ignore[arg-type]
        attendance=attendance,
        clock=lambda: NOW,
    )


def _past() -> FakeOccurrences:
    return FakeOccurrences({"occ-1": _occurrence(start_at=PAST, end_at=PAST + timedelta(hours=1))})


def _missed(**overrides: Any) -> CancelSessionOccurrenceCommand:
    values: dict[str, Any] = {
        "occurrence_id": "occ-1",
        "reason": "gym closed, found out late",
        "actor_id": "u-1",
        "notify": False,
        "missed": True,
    }
    values.update(overrides)
    return CancelSessionOccurrenceCommand(**values)


@pytest.mark.asyncio
async def test_preview_quotes_each_family_and_writes_nothing() -> None:
    occurrences, billing = _past(), FakeBillingWithPreview()
    use_case = _build(occurrences, attendance=FakeAttendance(), billing=billing)

    preview = await use_case.preview_missed("occ-1")

    assert occurrences.rows["occ-1"].status == "scheduled"
    assert billing.applied == []
    assert billing.previewed[0]["start_at"] == PAST
    assert [
        (f.enrollment_id, f.student_id, f.amount_cents, f.outcome) for f in preview.families
    ] == [
        ("enr-1", "st-1", 3000, "would_credit"),
        ("enr-2", "st-2", 0, "skipped:covered_by_free_classes"),
    ]
    assert preview.credit_total_cents == 3000
    assert preview.credit_skips == {"covered_by_free_classes": 1}
    assert preview.payroll_flag is None


@pytest.mark.asyncio
async def test_confirm_records_no_class_credits_through_the_call_off_path_and_tells_nobody() -> (
    None
):
    occurrences, billing, events, notifier = (
        _past(),
        FakeBillingWithPreview(),
        FakeEvents(),
        FakeNotifier(),
    )
    use_case = _build(
        occurrences, attendance=FakeAttendance(), billing=billing, events=events, notifier=notifier
    )

    result = await use_case.execute(_missed())

    stored = occurrences.rows["occ-1"]
    assert stored.status == "cancelled" and stored.is_billable is False
    assert stored.is_payable is False  # the coach is not paid for it
    assert stored.cancelled_by == "u-1"
    assert len(billing.applied) == 1 and billing.applied[0]["actor_id"] == "u-1"
    assert result.credits_issued == 1 and result.credit_total_cents == 3000
    assert result.payroll_flag is None
    assert notifier.calls == []
    assert {e.metadata.get("missed_class") for e in events.recorded} == {"true"}


@pytest.mark.asyncio
async def test_a_future_date_must_be_called_off_instead() -> None:
    use_case = _build(FakeOccurrences({"occ-1": _occurrence()}), attendance=FakeAttendance())
    with pytest.raises(OccurrenceNotPast):
        await use_case.preview_missed("occ-1")
    with pytest.raises(OccurrenceNotPast):
        await use_case.execute(_missed())


@pytest.mark.asyncio
async def test_a_date_with_students_marked_present_is_refused() -> None:
    occurrences, billing = _past(), FakeBillingWithPreview()
    use_case = _build(occurrences, attendance=FakeAttendance({"occ-1": 2}), billing=billing)

    with pytest.raises(MissedClassHadAttendance):
        await use_case.preview_missed("occ-1")
    with pytest.raises(MissedClassHadAttendance):
        await use_case.execute(_missed())
    assert occurrences.rows["occ-1"].status == "scheduled"
    assert billing.applied == []


@pytest.mark.asyncio
async def test_without_an_attendance_check_the_date_is_refused() -> None:
    """Unverifiable attendance is not 'nobody came'."""
    use_case = _build(_past(), billing=FakeBillingWithPreview())
    with pytest.raises(MissedClassHadAttendance):
        await use_case.execute(_missed())


@pytest.mark.asyncio
async def test_frozen_payout_still_credits_families_and_flags_payroll() -> None:
    """Owner rule (#1207): families are owed the money either way; a frozen
    payout cannot re-read the date, so payroll is flagged for a hand fix."""
    occurrences, events = _past(), FakeEvents()
    use_case = _build(
        occurrences,
        attendance=FakeAttendance(),
        billing=FakeBillingWithPreview(),
        payout_lock=FakePayoutLock("paid"),
        events=events,
    )

    preview = await use_case.preview_missed("occ-1")
    result = await use_case.execute(_missed())

    assert preview.payroll_flag and "paid" in preview.payroll_flag
    assert result.payroll_flag == preview.payroll_flag
    assert occurrences.rows["occ-1"].status == "cancelled"
    assert {e.metadata.get("payroll_flag") for e in events.recorded} == {"paid"}


@pytest.mark.asyncio
async def test_crediting_the_same_missed_date_twice_is_refused() -> None:
    billing = FakeBillingWithPreview()
    use_case = _build(_past(), attendance=FakeAttendance(), billing=billing)
    await use_case.execute(_missed())

    with pytest.raises(OccurrenceAlreadyCancelled):
        await use_case.execute(_missed())
    assert len(billing.applied) == 1
