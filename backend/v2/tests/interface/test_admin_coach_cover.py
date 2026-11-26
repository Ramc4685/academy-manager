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
