"""Contract tests for MongoSessionFeedbackRepository — tenant isolation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.domain.models import SessionFeedback
from backend.v2.contexts.coaching.infrastructure.mongo_session_feedback_repo import (
    MongoSessionFeedbackRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

# `db` fixture is provided by contract/conftest.py (mongomock-motor in-process)


def _feedback(
    feedback_id: str,
    academy_id: str,
    session_id: str = "sess-1",
    student_id: str = "stu-1",
) -> SessionFeedback:
    return SessionFeedback(
        feedback_id=feedback_id,
        academy_id=academy_id,
        session_id=session_id,
        coach_id="coach-1",
        student_id=student_id,
        body="Test feedback",
        created_at=datetime(2026, 5, 31, 10, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_tenant_isolation_list_for_session(db):
    """Feedback saved under academy-A must not appear when querying under academy-B."""
    repo = MongoSessionFeedbackRepository(db)

    fb_a = _feedback("fb-a1", "academy-A", session_id="sess-1")
    fb_b = _feedback("fb-b1", "academy-B", session_id="sess-1")

    with tenant_scope("academy-A"):
        await repo.save(fb_a)
    with tenant_scope("academy-B"):
        await repo.save(fb_b)

    with tenant_scope("academy-A"):
        results_a = await repo.list_for_session("sess-1")
    with tenant_scope("academy-B"):
        results_b = await repo.list_for_session("sess-1")

    assert [r.feedback_id for r in results_a] == ["fb-a1"]
    assert [r.feedback_id for r in results_b] == ["fb-b1"]


@pytest.mark.asyncio
async def test_tenant_isolation_cross_academy_returns_empty(db):
    """When academy-B has no feedback for a session that academy-A does, return empty."""
    repo = MongoSessionFeedbackRepository(db)

    fb = _feedback("fb-x1", "academy-A", session_id="sess-x")
    with tenant_scope("academy-A"):
        await repo.save(fb)

    with tenant_scope("academy-B"):
        results = await repo.list_for_session("sess-x")

    assert results == []


@pytest.mark.asyncio
async def test_list_for_student_tenant_isolation(db):
    repo = MongoSessionFeedbackRepository(db)

    fb_a = _feedback("fb-s-a", "academy-A", student_id="stu-common")
    fb_b = _feedback("fb-s-b", "academy-B", student_id="stu-common")

    with tenant_scope("academy-A"):
        await repo.save(fb_a)
    with tenant_scope("academy-B"):
        await repo.save(fb_b)

    with tenant_scope("academy-A"):
        results = await repo.list_for_student("stu-common")

    assert len(results) == 1
    assert results[0].feedback_id == "fb-s-a"
