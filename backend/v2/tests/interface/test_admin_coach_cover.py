"""The "Coach is sick" cover flow (S66, D-20, D-21; docs/design/coach-sick.md).

Over the real Mongo readers (mongomock): who is free or busy, the families a
cover notice reaches, the write-time re-check, and the D-21 choice.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.composition.coach_cover import (
    Candidate,
    CoachCoverReader,
    cover_notice,
    split_free_busy,
)
from backend.v2.composition.coach_roster_health import compose_coach_roster_health
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant_var
from backend.v2.shared.tenancy.context import set_academy_id

ACADEMY = "academy-a"
OTHER = "academy-b"
TZ = "America/Chicago"
# Tue Dec 8 2026, 5:30-6:30 PM Chicago (UTC-6).
TUE = datetime(2026, 12, 8, 23, 30, tzinfo=UTC)


def _occ(oid: str, sid: str, start: datetime, coach: str, **extra: Any) -> dict[str, Any]:
    return {
        "academy_id": extra.pop("academy", ACADEMY),
        "occurrence_id": oid,
        "session_id": sid,
        "start_at": start,
        "end_at": start + timedelta(hours=1),
        "status": extra.pop("status", "scheduled"),
        "scheduled_coach_id": coach,
        **extra,
    }


def _occurrence(oid: str, start: datetime, coach: str, **extra: Any) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=oid,
        academy_id=ACADEMY,
        session_id="s",
        start_at=start,
        end_at=start + timedelta(hours=1),
        scheduled_coach_id=coach,
        **extra,
    )


COACHES = [
    Candidate("coach-casey", "Casey Lee"),
    Candidate("coach-demo", "Demo Coach"),
    Candidate("coach-priya", "Priya Nair"),
    Candidate("coach-jordan", "Jordan Kim"),
]


def test_free_excludes_the_scheduled_coach_and_anyone_teaching_then() -> None:
    target = _occurrence("occ-ti", TUE, "coach-casey")
    others = [
        target,
        # Priya leads a class that overlaps by half an hour: busy.
        _occurrence("occ-jb", TUE - timedelta(minutes=30), "coach-priya"),
        # Jordan assists one that ends exactly when the target starts: free.
        _occurrence(
            "occ-early", TUE - timedelta(hours=1), "coach-x", assistant_coach_ids=("coach-jordan",)
        ),
        # A cancelled overlap never makes anyone busy.
        _occurrence("occ-off", TUE, "coach-demo", status="cancelled"),
    ]
    free, busy = split_free_busy(target, COACHES, others, {"s": "Junior Beginners"})
    assert [c.coach_id for c in free] == ["coach-demo", "coach-jordan"]
    assert [(b.coach_id, b.class_title) for b in busy] == [("coach-priya", "Junior Beginners")]


def test_the_current_cover_is_not_offered_again() -> None:
    target = _occurrence("occ-ti", TUE, "coach-casey", substitute_coach_id="coach-demo")
    free, _ = split_free_busy(target, COACHES, [target], {})
    assert "coach-demo" not in [c.coach_id for c in free]


def test_cover_notice_copy() -> None:
    assert cover_notice(
        title="Tuesday Intermediate", day="Tue, Dec 8", time="5:30 PM", cover="Demo", coach="Casey"
    ) == (
        "Tuesday Intermediate on Tue, Dec 8 at 5:30 PM will be taught by Coach Demo "
        "instead of Coach Casey. Same time, same place."
    )


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["coach-cover"]

    async def seed() -> None:
        await db["academies"].insert_many(
            [{"academy_id": ACADEMY, "timezone": TZ}, {"academy_id": OTHER, "timezone": TZ}]
        )
        await db["sessions"].insert_many(
            [
                {"academy_id": ACADEMY, "session_id": sid, "title": title, "status": "scheduled"}
                for sid, title in (
                    ("sess-ti", "Tuesday Intermediate"),
                    ("sess-jb", "Junior Beginners"),
                )
            ]
            + [{"academy_id": OTHER, "session_id": "sess-b", "title": "B", "status": "scheduled"}]
        )
        await db["session_occurrences"].insert_many(
            [
                _occ("occ-ti", "sess-ti", TUE, "coach-casey"),
                _occ("occ-jb", "sess-jb", TUE - timedelta(minutes=30), "coach-priya"),
                _occ("occ-b", "sess-b", TUE, "coach-b", academy=OTHER),
            ]
        )
        await db["enrollments"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "enrollment_id": f"enr-{sid}",
                    "session_id": "sess-ti",
                    "student_id": sid,
                    "status": "active",
                }
                for sid in ("stu-sam", "stu-dev")
            ]
        )
        await db["students"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "student_id": "stu-sam",
                    "full_name": "Sam Demo",
                    "parent_id": "par-demo",
                },
                {
                    "academy_id": ACADEMY,
                    "student_id": "stu-dev",
                    "full_name": "Dev Patel",
                    "parent_id": "par-patel",
                },
            ]
        )
        await db["users"].insert_many(
            [
                {"user_id": "par-demo", "display_name": "Demo Parent", "email": "demo@example.com"},
                {"user_id": "par-patel", "display_name": "Asha Patel"},
                {"user_id": "coach-casey", "display_name": "Casey Lee"},
            ]
        )

    asyncio.run(seed())
    return db


class _Replacement:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "occurrence_id": kwargs["occurrence_id"],
            "session_id": "sess-ti",
            "start_at": TUE,
            "end_at": TUE + timedelta(hours=1),
            "status": "scheduled",
            "scheduled_coach_id": "coach-casey",
            "substitute_coach_id": kwargs["replacement_coach_id"],
        }


class _Announcements:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def post(self, **kwargs: Any) -> Any:
        self.posts.append(kwargs)
        return SimpleNamespace(sent_count=1, failed_count=0)


def _client(db: Any, academy: str = ACADEMY) -> tuple[TestClient, SimpleNamespace]:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(academy)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    async def list_users(**_: Any) -> list[Any]:
        return [
            SimpleNamespace(user_id=c.coach_id, display_name=c.name, email="", status="active")
            for c in COACHES
        ] + [
            SimpleNamespace(user_id="coach-gone", display_name="Gone", email="", status="inactive")
        ]

    use_cases = SimpleNamespace(
        list_admin_users=SimpleNamespace(execute=list_users),
        update_session_occurrence_replacement=_Replacement(),
        session_announcements=_Announcements(),
        cancel_session_occurrence=None,
    )
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin", email="admin@example.com", academy_id=academy, roles=("admin",)
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    app.state.coach_cover = CoachCoverReader(db=db, health=compose_coach_roster_health(db))
    return TestClient(app), use_cases


def test_options_list_free_and_busy_coaches_and_the_families(db: Any) -> None:
    client, _ = _client(db)
    res = client.get("/api/v2/admin/coach-cover/options?occurrence_ids=occ-ti")
    assert res.status_code == 200, res.text
    (opt,) = res.json()["options"]
    assert opt["scheduled_coach"] == {"coach_id": "coach-casey", "name": "Casey Lee"}
    assert [c["coach_id"] for c in opt["free"]] == ["coach-demo", "coach-jordan"]
    assert [(b["coach_id"], b["class_title"]) for b in opt["busy"]] == [
        ("coach-priya", "Junior Beginners")
    ]
    assert opt["enrolled_count"] == 2
    assert [(f["family_name"], f["has_email"]) for f in opt["families"]] == [
        ("Asha Patel", False),
        ("Demo Parent", True),
    ]


def test_another_academys_class_date_is_not_found(db: Any) -> None:
    client, _ = _client(db)
    assert client.get("/api/v2/admin/coach-cover/options?occurrence_ids=occ-b").status_code == 404
    res = client.post(
        "/api/v2/admin/coach-cover/occ-b/assign", json={"replacement_coach_id": "coach-demo"}
    )
    assert res.status_code == 404


def test_assign_refuses_the_scheduled_coach_and_a_busy_one(db: Any) -> None:
    client, use_cases = _client(db)
    for coach in ("coach-casey", "coach-priya", "coach-gone"):
        res = client.post(
            "/api/v2/admin/coach-cover/occ-ti/assign", json={"replacement_coach_id": coach}
        )
        assert res.status_code == 409, coach
    assert use_cases.update_session_occurrence_replacement.calls == []


def test_assign_tells_families_only_when_the_admin_leaves_it_ticked(db: Any) -> None:
    client, use_cases = _client(db)
    res = client.post(
        "/api/v2/admin/coach-cover/occ-ti/assign",
        json={"replacement_coach_id": "coach-demo", "notify_families": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["announcement_posted"] is False
    assert use_cases.session_announcements.posts == []
    assert use_cases.update_session_occurrence_replacement.calls[0]["reason"] == (
        "Cover: coach unavailable"
    )

    res = client.post(
        "/api/v2/admin/coach-cover/occ-ti/assign",
        json={"replacement_coach_id": "coach-demo", "notify_families": True},
    )
    assert res.json()["families_notified"] == 1
    (post,) = use_cases.session_announcements.posts
    assert post["email"] is True and post["session_id"] == "sess-ti"
    assert post["body"] == (
        "Tuesday Intermediate on Tue, Dec 8 at 5:30 PM will be taught by Coach Demo Coach "
        "instead of Coach Casey Lee. Same time, same place."
    )


def test_a_coachs_dates_are_the_next_two_weeks(db: Any) -> None:
    now = datetime.now(UTC)

    async def seed() -> None:
        await db["session_occurrences"].insert_many(
            [
                _occ("occ-soon", "sess-ti", now + timedelta(days=2), "coach-jordan"),
                _occ("occ-far", "sess-ti", now + timedelta(days=20), "coach-jordan"),
                _occ(
                    "occ-off",
                    "sess-ti",
                    now + timedelta(days=3),
                    "coach-jordan",
                    status="cancelled",
                ),
            ]
        )

    asyncio.run(seed())
    client, _ = _client(db)
    res = client.get("/api/v2/admin/coach-cover/options?coach_id=coach-jordan")
    assert res.status_code == 200, res.text
    assert [d["occurrence_id"] for d in res.json()["dates"]] == ["occ-soon"]
    assert client.get("/api/v2/admin/coach-cover/options?coach_id=nobody").status_code == 404


# --- S67: the coach's "I can't make it" --------------------------------------


def _coach_client(db: Any, user_id: str) -> TestClient:
    """The admin test app with the coach router mounted, signed in as a coach."""
    from backend.v2.interfaces.coach.router import router as coach_router

    client, _ = _client(db)
    app = client.app
    app.include_router(coach_router, prefix="/api/v2")  # type: ignore[attr-defined]
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(  # type: ignore[attr-defined]
        user_id=user_id, email=f"{user_id}@example.com", academy_id=ACADEMY, roles=("coach",)
    )
    return client


def _seed_next(db: Any) -> None:
    start = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
    asyncio.run(
        db["session_occurrences"].insert_one(_occ("occ-next", "sess-ti", start, "coach-casey"))
    )


def test_a_cover_request_is_one_inbox_message_and_nothing_else(db: Any) -> None:
    _seed_next(db)
    client = _coach_client(db, "coach-casey")
    url = "/api/v2/coach/cover-requests"
    assert client.get(f"{url}?occurrence_id=occ-next").json() == {"requested_at": None}
    res = client.post(url, json={"occurrence_id": "occ-next", "reason": "Unwell"})
    assert res.status_code == 200, res.text
    first = res.json()["requested_at"]
    # Idempotent: a second tap returns the same request.
    assert client.post(url, json={"occurrence_id": "occ-next"}).json()["requested_at"] == first
    assert client.get(f"{url}?occurrence_id=occ-next").json() == {"requested_at": first}

    async def check() -> None:
        (msg,) = await db["messages"].find({}).to_list(None)
        assert msg["kind"] == "dm" and msg["recipient_id"] is None
        assert msg["inbox_thread_id"] == "coach-casey"
        assert (msg["scope_type"], msg["scope_id"]) == ("cover_request", "occ-next")
        assert msg["body"].startswith("Casey Lee can't ")
        assert " Tuesday Intermediate on " in msg["body"]
        assert msg["body"].endswith(". Reason: Unwell.")
        occ = await db["session_occurrences"].find_one({"occurrence_id": "occ-next"})
        assert occ["status"] == "scheduled" and not occ.get("substitute_coach_id")

    asyncio.run(check())


def test_only_an_assigned_coach_can_ask_and_only_for_a_future_date(db: Any) -> None:
    _seed_next(db)
    url = "/api/v2/coach/cover-requests"
    other = _coach_client(db, "coach-priya")
    assert other.post(url, json={"occurrence_id": "occ-next"}).status_code == 404
    assert other.get(f"{url}?occurrence_id=occ-next").status_code == 404
    casey = _coach_client(db, "coach-casey")
    assert casey.post(url, json={"occurrence_id": "occ-b"}).status_code == 404

    past = datetime.now(UTC) - timedelta(hours=2)
    asyncio.run(
        db["session_occurrences"].insert_many(
            [
                _occ("occ-past", "sess-ti", past, "coach-casey"),
                _occ(
                    "occ-gone",
                    "sess-ti",
                    past + timedelta(days=5),
                    "coach-casey",
                    status="cancelled",
                ),
            ]
        )
    )
    for oid in ("occ-past", "occ-gone"):
        assert casey.post(url, json={"occurrence_id": oid}).status_code == 409, oid


def test_the_front_desk_sees_an_open_request_until_cover_is_assigned(db: Any) -> None:
    _seed_next(db)
    _coach_client(db, "coach-casey").post(
        "/api/v2/coach/cover-requests", json={"occurrence_id": "occ-next"}
    )
    reader = CoachCoverReader(db=db, health=compose_coach_roster_health(db))

    async def check() -> None:
        set_academy_id(ACADEMY)  # this task's own context copy
        (occ,) = await reader.upcoming_open_cover_requests(now=datetime.now(UTC))
        assert occ.occurrence_id == "occ-next"
        assert await reader.open_cover_requests([occ]) == {"occ-next": "coach-casey"}
        # The coach's thread waits on staff until someone replies.
        assert await reader.messages_waiting() == 1
        await db["session_occurrences"].update_one(
            {"occurrence_id": "occ-next"}, {"$set": {"substitute_coach_id": "coach-demo"}}
        )
        assert await reader.upcoming_open_cover_requests(now=datetime.now(UTC)) == []

    asyncio.run(check())


def test_admin_messages_offer_find_cover_on_a_cover_request() -> None:
    from backend.v2.interfaces.admin.comms_routes import _message_view
    from backend.v2.shared.comms.messages import Message

    def msg(scope_type: str, scope_id: str) -> Message:
        return Message(
            message_id="m1",
            academy_id=ACADEMY,
            kind="dm",
            sender_id="coach-casey",
            sender_persona="coach",
            recipient_id=None,
            body="x",
            created_at=datetime.now(UTC),
            scope_type=scope_type,
            scope_id=scope_id,
            inbox_thread_id="coach-casey",
        )

    assert _message_view(msg("cover_request", "occ-next"), "u-admin").scope_id == "occ-next"
    # Other scoped messages keep their scope id to themselves.
    assert _message_view(msg("session", "sess-ti"), "u-admin").scope_id is None
