"""Staff cancel one approved guest booking (L9): its seat, inbox and day
claims are released, and only bookings whose date is still ahead count toward
the per-academy inbox limit."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    CancelGuestTrialBooking,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    TrialBookingNotCancellable,
    TrialRequest,
    TrialRequestNotFound,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy import tenant_scope

_M0236 = importlib.import_module("backend.v2.migrations.0236_trial_guest_bookings")
A = "acad-l9-cancel"
NOW = datetime.now(UTC).replace(microsecond=0)


def _guest(request_id: str, session_id: str, starts_at: datetime) -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id=A,
        contact_id=f"contact-{request_id}",
        student_ref="prospective",
        requested_session_id=session_id,
        preferred_start=starts_at.date().isoformat(),
        preferred_end=starts_at.date().isoformat(),
        status="approved",
        assigned_occurrence_id=f"occ-{request_id}",
        decided_at=NOW,
        created_at=NOW,
        guest_mailbox="jamie@example.test",
        guest_starts_at=starts_at,
    )


@pytest.mark.asyncio
async def test_cancelling_a_guest_booking_releases_its_claims(real_db: Any) -> None:
    await _M0236.up(real_db)
    trials = MongoTrialRequestRepository(real_db)
    cancel = CancelGuestTrialBooking(trials=trials)
    starts = NOW + timedelta(days=3)
    with tenant_scope(A):
        assert isinstance(
            await trials.add_guest(_guest("tr-1", "sess-1", starts), max_slot=1, day_ceiling=1),
            TrialRequest,
        )
        before = await cancel.execute("tr-1")
        # Seat, inbox-per-class and day number are all free again.
        again = await trials.add_guest(_guest("tr-2", "sess-1", starts), max_slot=1, day_ceiling=1)
        with pytest.raises(TrialBookingNotCancellable):
            await cancel.execute("tr-1")
        with pytest.raises(TrialRequestNotFound):
            await cancel.execute("tr-missing")

    assert before.status == "approved" and before.guest_starts_at == starts
    assert isinstance(again, TrialRequest)
    row = await real_db["trial_requests"].find_one({"request_id": "tr-1"})
    assert row["status"] == "pending" and row["assigned_occurrence_id"] is None
    for field in ("guest_slot", "guest_mailbox", "guest_day_claim", "guest_starts_at"):
        assert field not in row


@pytest.mark.asyncio
async def test_account_parent_trial_is_not_a_guest_booking(real_db: Any) -> None:
    trials = MongoTrialRequestRepository(real_db)
    trial = _guest("tr-p", "sess-1", NOW + timedelta(days=2)).model_copy(
        update={"contact_id": None, "parent_user_id": "parent-1", "guest_mailbox": None}
    )
    with tenant_scope(A):
        await trials.add(trial)
        with pytest.raises(TrialBookingNotCancellable):
            await CancelGuestTrialBooking(trials=trials).execute("tr-p")


@pytest.mark.asyncio
async def test_only_dates_still_ahead_count_toward_the_inbox_limit(real_db: Any) -> None:
    await _M0236.up(real_db)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        await trials.add_guest(
            _guest("tr-past", "sess-1", NOW - timedelta(hours=1)), max_slot=5, day_ceiling=10
        )
        await trials.add_guest(
            _guest("tr-next", "sess-2", NOW + timedelta(days=1)), max_slot=5, day_ceiling=10
        )
        active = await trials.count_active_guests("jamie@example.test", now=NOW)

    assert active == 1
