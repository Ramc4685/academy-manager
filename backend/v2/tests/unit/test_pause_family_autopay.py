from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _sbe(eid: str, status: str) -> StudentBillingEnrollment:
    return StudentBillingEnrollment(
        enrollment_id=eid,
        academy_id="acad",
        student_id="s-1",
        parent_id="p-1",
        session_type_id="st-1",
        billing_start_date=NOW,
        autopay_enrollment_status=status,  # type: ignore[arg-type]
        enrolled_at=NOW,
        updated_at=NOW,
    )


class FakeEnrollments:
    def __init__(self, rows):
        self.rows = {r.enrollment_id: r for r in rows}
        self.writes: list[tuple[str, str]] = []
        self.reject: set[str] = set()

    async def list_for_parent(self, parent_id: str):
        return list(self.rows.values())

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
        self.writes.append((enrollment_id, status))
        return enrollment_id not in self.reject


class FakeAudit:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)


class FakeIdem:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def put(self, key, value):
        self.store[key] = value


def _uc(enrollments, audit=None, idem=None):
    return PauseFamilyAutopay(
        enrollments=enrollments,
        audit=audit or FakeAudit(),
        idempotency=idem or FakeIdem(),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_pauses_only_active_enrollments_and_audits_once() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active"), _sbe("e-2", "paused"), _sbe("e-3", "active")])
    audit = FakeAudit()

    result = await _uc(enr, audit).execute(
        academy_id="acad",
        parent_id="p-1",
        actor_id="admin-1",
        reason="moving away",
        request_id="req-1",
    )

    assert result.paused_count == 2
    assert result.active_count_before == 2
    assert result.warnings == []
    assert sorted(enr.writes) == [("e-1", "paused"), ("e-3", "paused")]
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "autopay_paused"
    assert entry.parent_id == "p-1"
    assert entry.reason == "moving away"
    assert entry.audit_id == "baud-family-autopay-pause-acad-p-1-req-1"
    assert entry.before == {"enrollment_ids": ["e-1", "e-3"], "status": "active"}
    assert entry.after == {"enrollment_ids": ["e-1", "e-3"], "status": "paused"}


@pytest.mark.asyncio
async def test_nothing_active_raises() -> None:
    with pytest.raises(NothingToPause):
        await _uc(FakeEnrollments([_sbe("e-1", "paused")])).execute(
            academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r"
        )


@pytest.mark.asyncio
async def test_replay_with_same_request_id_returns_first_result_without_rewriting() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active")])
    idem = FakeIdem()
    audit = FakeAudit()
    first = await _uc(enr, audit, idem).execute(
        academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r"
    )
    enr.rows["e-1"] = _sbe("e-1", "paused")

    second = await _uc(enr, audit, idem).execute(
        academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r"
    )

    assert second == first
    assert enr.writes == [("e-1", "paused")]
    assert len(audit.entries) == 1


@pytest.mark.asyncio
async def test_rejected_transition_is_reported_not_raised() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active"), _sbe("e-2", "active")])
    enr.reject.add("e-2")

    result = await _uc(enr).execute(
        academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r"
    )

    assert result.paused_count == 1
    assert result.warnings == ["e-2: transition rejected"]
