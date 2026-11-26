"""S44: a coach hears, in their inbox, when an admin changes their classes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition import coach_schedule_notices as csn
from backend.v2.contexts.enrollment.domain.events import CoachScheduleNoticeRequested

ACADEMY = "test-academy"
SESSION = {
    "session_id": "ses_tue",
    "academy_id": ACADEMY,
    "coach_id": "demo",
    "title": "Tuesday Intermediate",
    "location": "Court 2",
    "start_at": datetime(2026, 12, 1, 23, 30, tzinfo=UTC),
    "end_at": datetime(2026, 12, 2, 0, 30, tzinfo=UTC),
    "capacity": 12,
    "days_of_week": ["Tue"],
    "start_time": "17:30",
    "end_time": "18:30",
    "timezone": "America/Chicago",
    "assistant_coach_ids": [],
}
OCCURRENCE = {
    "occurrence_id": "occ_dec1",
    "academy_id": ACADEMY,
    "session_id": "ses_tue",
    "start_at": datetime(2026, 12, 1, 23, 30, tzinfo=UTC),
    "end_at": datetime(2026, 12, 2, 0, 30, tzinfo=UTC),
    "status": "scheduled",
    "scheduled_coach_id": "casey",
    "assistant_coach_ids": ["helper"],
}


class _Outbox:
    """Mirrors MongoOutbox: a repeated event_id converges instead of duplicating."""

    def __init__(self) -> None:
        self.events: list[CoachScheduleNoticeRequested] = []

    async def append(self, event: Any, *, session: Any = None) -> None:
        if any(e.event_id == event.event_id for e in self.events):
            return
        self.events.append(event)

    def kinds(self) -> list[tuple[str, str]]:
        return sorted((e.payload.kind, e.payload.coach_id) for e in self.events)


class _Push:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def direct_message(self, message: Any) -> None:
        self.sent.append(message)


async def _seed(db: Any) -> None:
    await db["sessions"].insert_one(dict(SESSION))
    await db["session_occurrences"].insert_one(dict(OCCURRENCE))
    await db["academies"].insert_one(
        {"academy_id": ACADEMY, "name": "Demo Academy", "timezone": "America/Chicago"}
    )


@pytest.mark.asyncio
async def test_new_lead_is_assigned_and_old_lead_unassigned(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")
    after = before.model_copy(update={"coach_id": "casey", "assistant_coach_ids": ("helper",)})

    await notices.session_changed(before, after, actor_id="owner")

    assert outbox.kinds() == [
        ("assigned", "casey"),
        ("assigned", "helper"),
        ("unassigned", "demo"),
    ]
    roles = {e.payload.coach_id: e.payload.role for e in outbox.events}
    assert roles["casey"] == "lead" and roles["helper"] == "assistant"


@pytest.mark.asyncio
async def test_time_change_moves_only_the_coaches_who_stay(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")

    await notices.session_changed(
        before, before.model_copy(update={"start_time": "17:35"}), actor_id="owner"
    )
    assert outbox.kinds() == [("moved", "demo")]

    outbox.events.clear()
    await notices.session_changed(
        before, before.model_copy(update={"capacity": 20}), actor_id="owner"
    )
    assert outbox.events == []


@pytest.mark.asyncio
async def test_the_admin_making_the_change_is_never_notified(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")

    await notices.session_changed(
        before, before.model_copy(update={"coach_id": "owner"}), actor_id="owner"
    )
    assert outbox.kinds() == [("unassigned", "demo")]


@pytest.mark.asyncio
async def test_cancel_notifies_each_coach_once_and_never_twice(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.occurrence_snapshot("occ_dec1")

    await notices.occurrence_cancelled(before, reason="Gym closed", actor_id="owner")
    await notices.occurrence_cancelled(before, reason="Gym closed", actor_id="owner")
    assert outbox.kinds() == [("cancelled", "casey"), ("cancelled", "helper")]

    already = before.model_copy(update={"status": "cancelled"})
    outbox.events.clear()
    await notices.occurrence_cancelled(already, reason="again", actor_id="owner")
    assert outbox.events == []


@pytest.mark.asyncio
async def test_cover_assigns_the_new_coach_and_releases_the_old(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = csn.occurrence_staff(await notices.occurrence_snapshot("occ_dec1"))
    await db["session_occurrences"].update_one(
        {"occurrence_id": "occ_dec1"}, {"$set": {"substitute_coach_id": "demo"}}
    )

    await notices.occurrence_changed("occ_dec1", before, actor_id="owner")

    assert outbox.kinds() == [("date_assigned", "demo"), ("date_unassigned", "casey")]
    assert all(e.payload.occurrence_id == "occ_dec1" for e in outbox.events)


@pytest.mark.asyncio
async def test_delivery_writes_one_message_to_the_affected_coach_only(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")
    await notices.session_changed(
        before, before.model_copy(update={"coach_id": "casey"}), actor_id="owner"
    )
    assigned = next(e for e in outbox.events if e.payload.kind == "assigned")
    # Round-trip through the outbox's JSON payload, as the dispatcher does.
    event = CoachScheduleNoticeRequested.model_validate(assigned.model_dump(mode="json"))
    push = _Push()
    delivery = csn.CoachScheduleNoticeDelivery(db, push)

    first = await delivery.deliver(event)
    replay = await delivery.deliver(event)

    assert first is not None and replay is None
    docs = [d async for d in db["messages"].find({})]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["recipient_id"] == "casey" and doc["academy_id"] == ACADEMY
    assert doc["kind"] == "dm" and doc["sender_id"] == "owner"
    assert "Tuesday Intermediate" in doc["body"]
    assert "Tuesday, 5:30 PM to 6:30 PM" in doc["body"] and "Court 2" in doc["body"]
    assert [m.recipient_id for m in push.sent] == ["casey"]


@pytest.mark.asyncio
async def test_cancel_message_names_the_date_and_reason(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    await notices.occurrence_cancelled(
        await notices.occurrence_snapshot("occ_dec1"), reason="Gym closed", actor_id="owner"
    )
    delivery = csn.CoachScheduleNoticeDelivery(db)
    message = await delivery.deliver(outbox.events[0])
    assert message is not None
    assert message.body.startswith("Tuesday Intermediate on Tuesday, December 1 at 5:30 PM")
    assert message.body.endswith("is cancelled. Reason: Gym closed")


@pytest.mark.asyncio
async def test_handler_delivers_inside_the_events_academy(db: Any, acad: str) -> None:
    await _seed(db)
    outbox = _Outbox()
    notices = csn.compose_coach_schedule_notices(db, outbox)
    try:
        await notices.occurrence_cancelled(
            await notices.occurrence_snapshot("occ_dec1"), reason=None, actor_id="owner"
        )
        for event in outbox.events:
            await csn.on_coach_schedule_notice(event)
            await csn.on_coach_schedule_notice(event)  # redelivery
    finally:
        csn.install_coach_schedule_delivery(None)
    recipients = sorted([d["recipient_id"] async for d in db["messages"].find({})])
    assert recipients == ["casey", "helper"]


# --- the admin routes emit after their write --------------------------------


def _route_client(db: Any, outbox: _Outbox) -> Any:
    from fastapi.testclient import TestClient

    from backend.v2.tests.interface.test_assistant_coach import _mongo_admin_app

    app = _mongo_admin_app(db)
    app.state.coach_schedule_notices = csn.CoachScheduleNotices(db, outbox)
    return TestClient(app)


@pytest.mark.asyncio
async def test_routes_emit_on_assistants_and_coach_change() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.tests.interface.test_assistant_coach import _seed_admin_db

    db = mongomock_motor.AsyncMongoMockClient()["coach-notices"]
    await _seed_admin_db(db)
    outbox = _Outbox()
    with _route_client(db, outbox) as client:
        r = client.put(
            "/api/v2/admin/sessions/sess-a/assistants", json={"assistant_coach_ids": ["asst-1"]}
        )
        assert r.status_code == 200, r.text
        assert outbox.kinds() == [("assigned", "asst-1")]

        outbox.events.clear()
        r = client.patch("/api/v2/admin/sessions/sess-a", json={"coach_id": "coach-2"})
        assert r.status_code == 200, r.text
        assert outbox.kinds() == [("assigned", "coach-2"), ("unassigned", "coach-1")]


# --- S54: the assignment email through the gated send port -------------------


def _gated_sender(db: Any) -> Any:
    from types import SimpleNamespace

    from backend.v2.composition.digests import _build_email_sender

    settings = SimpleNamespace(email_delivery_enabled=False, resend_api_key=None, env="test")
    return _build_email_sender(settings, db)


async def _seed_casey(db: Any, *, opted_out: bool = False) -> None:
    await db["users"].insert_one(
        {
            "user_id": "casey",
            "academy_id": ACADEMY,
            "email": "casey@example.com",
            "display_name": "Casey Newcoach",
            "is_active": True,
        }
    )
    await db["academy_memberships"].insert_one(
        {"academy_id": ACADEMY, "user_id": "casey", "roles": ["coach"], "status": "active"}
    )
    if opted_out:
        await db["email_preferences"].insert_one(
            {"academy_id": ACADEMY, "user_id": "casey", "notifications_opted_out": True}
        )


async def _deliver_all(db: Any, outbox: _Outbox, sender: Any) -> None:
    delivery = csn.CoachScheduleNoticeDelivery(db, sender=sender)
    for event in outbox.events:
        await delivery.deliver(event)
        await delivery.deliver(event)  # a replay sends nothing more


@pytest.mark.asyncio
async def test_assignment_sends_one_notification_email(db: Any, acad: str) -> None:
    from backend.v2.composition.digests import unwrap_send_port
    from backend.v2.contexts.communications.domain.email_category import EmailCategory

    await _seed(db)
    await _seed_casey(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")
    assigned = before.model_copy(update={"coach_id": "casey"})
    await notices.session_changed(before, assigned, actor_id="owner")
    # A five-minute time change afterwards is in-app only.
    await notices.session_changed(
        assigned, assigned.model_copy(update={"start_time": "17:35"}), actor_id="owner"
    )
    sender = _gated_sender(db)

    await _deliver_all(db, outbox, sender)

    sent = [row for row in unwrap_send_port(sender).sent if row["user_id"] == "casey"]
    assert len(sent) == 1
    assert sent[0]["category"] is EmailCategory.NOTIFICATION
    assert sent[0]["subject"] == "You're coaching Tuesday Intermediate"
    assert sent[0]["sender_name"]  # the academy's name on the From line


@pytest.mark.asyncio
async def test_cancellation_is_not_emailed_twice(db: Any, acad: str) -> None:
    from backend.v2.composition.digests import unwrap_send_port

    await _seed(db)
    await _seed_casey(db)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    await notices.occurrence_cancelled(
        await notices.occurrence_snapshot("occ_dec1"), reason="Rain", actor_id="owner"
    )
    sender = _gated_sender(db)
    await _deliver_all(db, outbox, sender)
    # The #671 staff roster email already tells the class's coach.
    assert unwrap_send_port(sender).sent == []
    assert await db["messages"].count_documents({"recipient_id": "casey"}) == 1


@pytest.mark.asyncio
async def test_no_email_when_the_coach_switched_notifications_off(db: Any, acad: str) -> None:
    from backend.v2.composition.digests import unwrap_send_port

    await _seed(db)
    await _seed_casey(db, opted_out=True)
    outbox = _Outbox()
    notices = csn.CoachScheduleNotices(db, outbox)
    before = await notices.session_snapshot("ses_tue")
    await notices.session_changed(
        before, before.model_copy(update={"coach_id": "casey"}), actor_id="owner"
    )
    sender = _gated_sender(db)
    await _deliver_all(db, outbox, sender)
    assert [r for r in unwrap_send_port(sender).sent if r["user_id"] == "casey"] == []
    # The in-app message still arrives.
    assert await db["messages"].count_documents({"recipient_id": "casey"}) == 1
