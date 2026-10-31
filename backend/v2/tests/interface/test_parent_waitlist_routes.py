"""Parent waitlist offer routes (#828, X2): list, confirm, decline.

Until X2 nothing called the confirm route and there was no way to list or
decline an offer, so every offer expired unclaimed. These run the real use
cases over the offer fakes, so the HTTP shape and the seat arithmetic are
checked together.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.waitlist_offers import (
    ConfirmWaitlistOffer,
    DeclineWaitlistOffer,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_waitlist_offers import (
    ACADEMY,
    FakeEnrollments,
    FakeOfferNotifier,
    FakeOutbox,
    FakeSessions,
    FakeWaitlist,
    _entry,
    _promote,
)

NOW = datetime.now(UTC)


def _claims(role: str = "parent", user_id: str = "par-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id=ACADEMY,
        roles=(role,),  # type: ignore[arg-type]
    )


class _World:
    """wl-1 (par-1) holds the class's one seat as an open offer; wl-2 waits."""

    def __init__(self) -> None:
        self.waitlist = FakeWaitlist(
            entries={
                "wl-1": _entry("wl-1", parent_id="par-1", student_id="stu-1", days_ago=10),
                "wl-2": _entry("wl-2", parent_id="par-2", student_id="stu-2", days_ago=5),
            }
        )
        self.sessions = FakeSessions()
        self.enrollments = FakeEnrollments()
        self.notifier = FakeOfferNotifier()

    def promote(self):
        return _promote(
            self.waitlist, self.sessions, self.enrollments, FakeOutbox(), self.notifier, now=NOW
        )

    def use_cases(self) -> SimpleNamespace:
        async def list_parent_waitlist(parent_id: str):
            return [
                {
                    "waitlist_id": e.waitlist_id,
                    "session_id": e.session_id,
                    "session_title": "Beginners",
                    "schedule_label": "Thursdays 6:00 PM CDT",
                    "location": None,
                    "student_id": e.student_id,
                    "student_name": "Kid",
                    "status": e.status,
                    "joined_at": e.joined_at,
                    "offer_expires_at": e.offer_expires_at,
                }
                for e in await self.waitlist.list_for_parent(parent_id)
            ]

        return SimpleNamespace(
            list_parent_waitlist=list_parent_waitlist,
            confirm_waitlist_offer=ConfirmWaitlistOffer(
                waitlist=self.waitlist,
                enrollments=self.enrollments,
                outbox=FakeOutbox(),
                academy_id=lambda: ACADEMY,
            ),
            decline_waitlist_offer=DeclineWaitlistOffer(
                waitlist=self.waitlist, sessions=self.sessions, promote=self.promote()
            ),
        )


@contextmanager
def _client(world: _World, *, role: str = "parent", user_id: str = "par-1") -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    app.dependency_overrides[get_parent_use_cases] = world.use_cases
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def world() -> _World:
    w = _World()
    await w.promote().execute("sess-1")
    assert w.waitlist.entries["wl-1"].status == "offered"
    return w


def test_list_shows_only_this_familys_rows_with_the_deadline(world: _World) -> None:
    with _client(world) as client:
        response = client.get("/api/v2/parent/waitlist")

    assert response.status_code == 200, response.text
    [row] = response.json()["entries"]
    assert row["waitlist_id"] == "wl-1"
    assert row["status"] == "offered"
    assert row["offer_expires_at"] is not None


def test_confirm_enrolls_the_child_on_the_held_seat(world: _World) -> None:
    with _client(world) as client:
        response = client.post("/api/v2/parent/waitlist/wl-1/confirm")

    assert response.status_code == 200, response.text
    enrollment_id = response.json()["enrollment_id"]
    assert world.enrollments.rows[enrollment_id].status == "active"
    assert world.waitlist.entries["wl-1"].status == "promoted"
    assert world.sessions.reserved == 1


def test_confirming_an_expired_offer_is_a_409_with_its_code(world: _World) -> None:
    world.waitlist.entries["wl-1"] = world.waitlist.entries["wl-1"].model_copy(
        update={"offer_expires_at": NOW - timedelta(minutes=1)}
    )
    with _client(world) as client:
        response = client.post("/api/v2/parent/waitlist/wl-1/confirm")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Enrollment.WaitlistOfferExpired"
    assert world.enrollments.rows == {}


def test_confirming_a_declined_offer_is_a_409_not_open(world: _World) -> None:
    with _client(world) as client:
        assert client.post("/api/v2/parent/waitlist/wl-1/decline").status_code == 200
        response = client.post("/api/v2/parent/waitlist/wl-1/confirm")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Enrollment.WaitlistOfferNotOpen"


def test_decline_releases_the_seat_to_the_next_family(world: _World) -> None:
    with _client(world) as client:
        response = client.post("/api/v2/parent/waitlist/wl-1/decline")

    assert response.status_code == 200, response.text
    assert response.json() == {"waitlist_id": "wl-1", "status": "removed"}
    assert world.waitlist.entries["wl-1"].status == "removed"
    assert world.waitlist.entries["wl-2"].status == "offered"
    assert world.sessions.reserved == 1


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_another_familys_offer_is_a_404(world: _World, action: str) -> None:
    with _client(world, user_id="par-2") as client:
        response = client.post(f"/api/v2/parent/waitlist/wl-1/{action}")

    assert response.status_code == 404
    assert world.waitlist.entries["wl-1"].status == "offered"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v2/parent/waitlist"),
        ("post", "/api/v2/parent/waitlist/wl-1/confirm"),
        ("post", "/api/v2/parent/waitlist/wl-1/decline"),
    ],
)
def test_wrong_persona_is_a_404(world: _World, method: str, path: str) -> None:
    with _client(world, role="coach") as client:
        response = getattr(client, method)(path)

    assert response.status_code == 404
