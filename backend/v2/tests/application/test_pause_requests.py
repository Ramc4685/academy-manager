from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
    RequestEnrollmentPause,
    RequestEnrollmentPauseCommand,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


def test_fixed_pause_requires_resume_on() -> None:
    with pytest.raises(ValidationError, match="resume_on is required"):
        PauseRequest(
            pause_request_id="pause-1",
            enrollment_id="enr-1",
            parent_id="parent-1",
            pause_kind="fixed",
            reason="summer break",
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )


def test_indefinite_pause_rejects_resume_on() -> None:
    with pytest.raises(ValidationError, match="resume_on is only allowed"):
        PauseRequest(
            pause_request_id="pause-1",
            enrollment_id="enr-1",
            parent_id="parent-1",
            pause_kind="indefinite",
            resume_on=date(2026, 7, 1),
            reason="not sure",
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_request_pause_derives_legacy_period_from_resume_on() -> None:
    repo = _FakePauseRequests()
    use_case = RequestEnrollmentPause(pause_requests=repo)

    request = await use_case.execute(
        RequestEnrollmentPauseCommand(
            parent_id="parent-1",
            enrollment_id="enr-1",
            pause_kind="fixed",
            resume_on=date(2026, 7, 15),
            reason="summer travel",
        )
    )

    assert request.pause_kind == "fixed"
    assert request.resume_on == date(2026, 7, 15)
    assert request.period == "2026-07"


@pytest.mark.asyncio
async def test_mongo_pause_request_round_trips_pause_kind_and_resume_on() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["pause-requests-contract"]
    repo = MongoPauseRequestRepository(db)
    request = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="fixed",
        resume_on=date(2026, 7, 15),
        reason="summer travel",
        created_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    with tenant_scope("acad-1"):
        await repo.add(request)
        loaded = await repo.get("pause-1")

    assert loaded is not None
    assert loaded.pause_kind == "fixed"
    assert loaded.resume_on == date(2026, 7, 15)
    assert loaded.period == "2026-07"


class _FakePauseRequests:
    async def add(self, request: PauseRequest) -> None:
        self.request = request

    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool:
        return True
