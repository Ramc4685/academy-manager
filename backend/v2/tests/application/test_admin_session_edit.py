from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    EditSession,
    EditSessionCommand,
)
from backend.v2.contexts.enrollment.domain.errors import SessionNotFound
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.shared.tenancy.context import tenant_scope


@dataclass
class FakeSessionStore:
    rows: dict[str, Session] = field(default_factory=dict)
    updated: list[Session] = field(default_factory=list)

    async def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)

    async def update(self, session: Session) -> None:
        self.rows[session.session_id] = session
        self.updated.append(session)


def _session() -> Session:
    return Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 22, 10, 0, tzinfo=UTC),
        capacity=8,
        status="scheduled",
    )


@pytest.mark.asyncio
async def test_admin_can_edit_session_metadata_without_touching_pricing() -> None:
    store = FakeSessionStore(rows={"sess-1": _session()})
    use_case = EditSession(sessions=store)

    updated = await use_case.execute(
        EditSessionCommand(
            session_id="sess-1",
            title="Junior Advanced",
            capacity=10,
            location="Court 3",
            start_at=datetime(2026, 5, 22, 9, 30, tzinfo=UTC),
            end_at=datetime(2026, 5, 22, 11, 0, tzinfo=UTC),
            coach_id="coach-2",
            actor_id="admin-1",
            reason="schedule cleanup",
        )
    )

    assert updated.title == "Junior Advanced"
    assert updated.capacity == 10
    assert updated.location == "Court 3"
    assert updated.start_at == datetime(2026, 5, 22, 9, 30, tzinfo=UTC)
    assert updated.end_at == datetime(2026, 5, 22, 11, 0, tzinfo=UTC)
    assert updated.coach_id == "coach-2"
    assert len(store.updated) == 1
    assert not hasattr(updated, "monthly_price_cents")


@pytest.mark.asyncio
async def test_session_edit_raises_not_found_for_missing_or_cross_tenant_session() -> None:
    store = FakeSessionStore(rows={})
    use_case = EditSession(sessions=store)

    with pytest.raises(SessionNotFound):
        await use_case.execute(
            EditSessionCommand(
                session_id="missing-session",
                title="Blocked",
                actor_id="admin-1",
                reason="wrong tenant or missing",
            )
        )

    assert store.updated == []


@pytest.mark.asyncio
async def test_mongo_session_edit_does_not_cross_tenant_boundary() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["sessions"].insert_one(
        {
            "session_id": "sess-shared",
            "academy_id": "academy-b",
            "coach_id": "coach-1",
            "title": "Other Tenant",
            "location": "Court 1",
            "start_at": datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 22, 10, 0, tzinfo=UTC),
            "capacity": 8,
            "status": "scheduled",
        }
    )

    with tenant_scope("academy-a"):
        use_case = EditSession(sessions=MongoSessionWriter(db))
        with pytest.raises(SessionNotFound):
            await use_case.execute(
                EditSessionCommand(
                    session_id="sess-shared",
                    title="Should Not Apply",
                    actor_id="admin-1",
                    reason="tenant mismatch",
                )
            )

    row = await db["sessions"].find_one({"session_id": "sess-shared"})
    assert row["title"] == "Other Tenant"
