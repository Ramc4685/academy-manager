"""Declining a guest trial frees its inbox and day claims (L9, migration 0236),
so staff can release an inbox that was squatted or whose date was cancelled."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy import tenant_scope

_M0236 = importlib.import_module("backend.v2.migrations.0236_trial_guest_bookings")
A = "acad-l9-deny"


def _guest(request_id: str, occurrence_id: str) -> TrialRequest:
    now = datetime.now(UTC).replace(microsecond=0)
    return TrialRequest(
        request_id=request_id,
        academy_id=A,
        contact_id=f"contact-{request_id}",
        student_ref="prospective",
        requested_session_id="sess-1",
        preferred_start="2026-12-01",
        preferred_end="2026-12-01",
        status="approved",
        assigned_occurrence_id=occurrence_id,
        decided_at=now,
        created_at=now + timedelta(days=1),
        guest_mailbox="jamie@example.test",
    )


@pytest.mark.asyncio
async def test_denying_a_guest_frees_its_inbox_for_the_class(real_db: Any) -> None:
    await _M0236.up(real_db)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        first = await trials.add_guest(_guest("tr-1", "occ-1"), max_slot=2, day_ceiling=10)
        assert isinstance(first, TrialRequest)
        squatted = await trials.add_guest(_guest("tr-2", "occ-2"), max_slot=2, day_ceiling=10)
        assert squatted == "mailbox_limit"
        # The date is cancelled (back to pending), then staff decline it.
        await trials.reopen_for_assigned_occurrence("occ-1")
        denied = await trials.transition_from_pending("tr-1", {"status": "denied"})
        again = await trials.add_guest(_guest("tr-3", "occ-2"), max_slot=2, day_ceiling=10)

    assert denied is not None and denied.guest_mailbox is None
    row = await real_db["trial_requests"].find_one({"request_id": "tr-1"})
    assert "guest_mailbox" not in row and "guest_day_claim" not in row
    assert isinstance(again, TrialRequest)
