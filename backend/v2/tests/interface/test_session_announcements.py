"""Session announcements: admin + coach routes and the urgent fan-out (#614).

Exercises the real ``SessionAnnouncementService`` and the real ``CommsService``
over in-memory fakes, so the authorization rules, the escaping and the
email-status reporting are all tested through the code that ships rather than
through a mock of it. The send port is a recording stub — the fan-out tests
assert against it and never touch a provider.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.session_announcements import (
    SessionAnnouncementService,
    render_announcement_email,
)
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach.deps import get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.comms import CommsService, Message
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope

SESSION_ID = "sess-1"
ACADEMY = "acad"


def _claims(role: str, user_id: str) -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id=ACADEMY,
        roles=(role,),  # type: ignore[arg-type]
    )


def _session(session_id: str = SESSION_ID, coach_id: str = "coach-1", title: str = "Junior A"):
    return Session(
        session_id=session_id,
        academy_id=ACADEMY,
        coach_id=coach_id,
        title=title,
        location="Court 1",
        start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        capacity=8,
        status="scheduled",
        timezone="America/Chicago",
    )


@dataclass
class _FakeMessageRepo:
    rows: dict[str, Message] = field(default_factory=dict)

    async def insert(self, m: Message) -> None:
        self.rows[m.message_id] = m

    async def for_session(self, session_id: str) -> list[Message]:
        return sorted(
            (
                m
                for m in self.rows.values()
                if m.kind == "announcement"
                and m.scope_type == "session"
                and m.scope_id == session_id
                and m.deleted_at is None
            ),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def get(self, message_id: str) -> Message | None:
        m = self.rows.get(message_id)
        return m if m is not None and m.deleted_at is None else None

    async def soft_delete(self, message_id: str, deleted_by: str) -> None:
        m = self.rows.get(message_id)
        if m is not None:
            self.rows[message_id] = m.model_copy(
                update={"deleted_at": datetime.now(UTC), "deleted_by": deleted_by}
            )


@dataclass
class _FakeSessions:
    sessions: dict[str, Session] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)


class _FakeAcademies:
    async def get_academy_name(self, academy_id: str) -> str | None:
        return "Rally Badminton"


@dataclass
class _FakeUsers:
    names: dict[str, str] = field(default_factory=dict)

    async def get_by_id(self, user_id: str):
        name = self.names.get(user_id)
        return SimpleNamespace(display_name=name) if name else None


@dataclass
class _FakeAudiences:
    recipients: list[ResolvedRecipient] = field(default_factory=list)

    async def resolve_session_audience(self, audience) -> list[ResolvedRecipient]:
        return list(self.recipients)


@dataclass
class _RecordingSendPort:
    """The local/test send port: records, never contacts a provider."""

    sent: list[dict] = field(default_factory=list)
    fail_for: set[str] = field(default_factory=set)
    raises: bool = False

    async def send(self, *, recipient, subject, body, category=None, **_kw) -> SendOutcome:
        if self.raises:
            raise RuntimeError("provider is down")
        self.sent.append(
            {
                "email": recipient.email,
                "subject": subject,
                "body": body,
                "category": category,
            }
        )
        if recipient.email in self.fail_for:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="bounced")
        return SendOutcome(ok=True, provider_message_id="prov-1", failed_reason=None)


@dataclass
class _Harness:
    service: SessionAnnouncementService
    repo: _FakeMessageRepo
    sender: _RecordingSendPort
    audiences: _FakeAudiences


def _harness(
    *,
    sessions: dict[str, Session] | None = None,
    recipients: list[ResolvedRecipient] | None = None,
    sender: _RecordingSendPort | None = None,
) -> _Harness:
    repo = _FakeMessageRepo()
    send_port = sender or _RecordingSendPort()
    audiences = _FakeAudiences(
        recipients if recipients is not None else [ResolvedRecipient("p1", "p1@example.com")]
    )
    service = SessionAnnouncementService(
        comms=CommsService(messages=repo, academy_id=ACADEMY),  # type: ignore[arg-type]
        sessions=_FakeSessions(sessions if sessions is not None else {SESSION_ID: _session()}),
        academies=_FakeAcademies(),
        users=_FakeUsers({"adm-1": "Priya Admin", "coach-1": "Coach Riya"}),
        audiences=audiences,
        sender=send_port,
    )
    return _Harness(service=service, repo=repo, sender=send_port, audiences=audiences)


@contextmanager
def _admin_client(harness: _Harness, role: str = "admin") -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, "adm-1")
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        session_announcements=harness.service
    )
    with TestClient(app) as client:
        yield client


@contextmanager
def _coach_client(
    harness: _Harness, *, coach_id: str = "coach-1", role: str = "coach", assigned: bool = True
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, coach_id)

    class _Assigned:
        async def is_coach_assigned(self, coach: str, session_id: str) -> bool:
            return assigned

    app.dependency_overrides[get_coach_use_cases] = lambda: SimpleNamespace(
        session_announcements=harness.service, assigned_sessions=_Assigned()
    )
    with TestClient(app) as client:
        yield client


# --- admin surface ------------------------------------------------------


def test_admin_posts_a_routine_announcement_and_no_email_is_sent():
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "Bring an extra shirt."},
        )

    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["email_status"] == "skipped"
    assert payload["announcement"]["urgency"] == "routine"
    assert payload["announcement"]["author_display_name"] == "Priya Admin"
    # Stored as a session-scoped announcement in the shared messages store.
    [stored] = list(h.repo.rows.values())
    assert (stored.kind, stored.scope_type, stored.scope_id) == (
        "announcement",
        "session",
        SESSION_ID,
    )
    assert h.sender.sent == []


def test_urgent_announcement_emails_the_roster_as_transactional():
    h = _harness(
        recipients=[
            ResolvedRecipient("p1", "p1@example.com"),
            ResolvedRecipient("p2", "p2@example.com"),
            # No address: silently unreachable, and must not be counted as sent.
            ResolvedRecipient("p3", ""),
        ]
    )
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "Class is cancelled tonight.", "urgent": True},
        )

    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["email_status"] == "sent"
    assert (payload["sent_count"], payload["failed_count"]) == (2, 0)
    assert [s["email"] for s in h.sender.sent] == ["p1@example.com", "p2@example.com"]
    assert {s["category"] for s in h.sender.sent} == {EmailCategory.TRANSACTIONAL}


def test_a_failed_send_is_counted_so_the_admin_sees_who_was_missed():
    sender = _RecordingSendPort(fail_for={"p2@example.com"})
    h = _harness(
        recipients=[
            ResolvedRecipient("p1", "p1@example.com"),
            ResolvedRecipient("p2", "p2@example.com"),
        ],
        sender=sender,
    )
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "Cancelled.", "urgent": True},
        )

    assert (r.json()["sent_count"], r.json()["failed_count"]) == (1, 1)


def test_an_empty_roster_still_posts_the_announcement():
    h = _harness(recipients=[])
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "Cancelled.", "urgent": True},
        )

    assert r.status_code == 201, r.text
    assert r.json()["email_status"] == "no_recipients"
    assert len(h.repo.rows) == 1


def test_a_broken_send_port_still_leaves_the_announcement_posted():
    h = _harness(sender=_RecordingSendPort(raises=True))
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "Cancelled.", "urgent": True},
        )

    assert r.status_code == 201, r.text
    assert r.json()["email_status"] == "failed"
    assert len(h.repo.rows) == 1


def test_two_identical_urgent_posts_each_email_the_roster():
    """Repeating an announcement is a real thing to do, not a duplicate."""
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        for _ in range(2):
            r = client.post(
                f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
                json={"body": "Still cancelled.", "urgent": True},
            )
            assert r.status_code == 201, r.text

    assert len(h.sender.sent) == 2
    assert len(h.repo.rows) == 2


def test_history_is_newest_first_and_hides_deleted_announcements():
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        first = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "One"}
        ).json()["announcement"]["message_id"]
        client.post(f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "Two"})

        listed = client.get(f"/api/v2/admin/sessions/{SESSION_ID}/announcements").json()
        assert [a["body"] for a in listed["announcements"]] == ["Two", "One"]

        deleted = client.delete(f"/api/v2/admin/sessions/{SESSION_ID}/announcements/{first}")
        assert deleted.status_code == 204, deleted.text

        listed = client.get(f"/api/v2/admin/sessions/{SESSION_ID}/announcements").json()
        assert [a["body"] for a in listed["announcements"]] == ["Two"]


def test_admin_may_delete_a_coachs_announcement():
    h = _harness()
    with tenant_scope(ACADEMY), _coach_client(h) as coach:
        mid = coach.post(
            f"/api/v2/coach/sessions/{SESSION_ID}/announcements", json={"body": "Coach post"}
        ).json()["announcement"]["message_id"]
    with tenant_scope(ACADEMY), _admin_client(h) as admin:
        r = admin.delete(f"/api/v2/admin/sessions/{SESSION_ID}/announcements/{mid}")

    assert r.status_code == 204, r.text


def test_deleting_an_announcement_through_a_different_session_is_404():
    """Otherwise session A's owner could delete session B's announcement."""
    h = _harness(sessions={SESSION_ID: _session(), "sess-2": _session("sess-2", title="Other")})
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        mid = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "One"}
        ).json()["announcement"]["message_id"]

        r = client.delete(f"/api/v2/admin/sessions/sess-2/announcements/{mid}")

    assert r.status_code == 404, r.text
    assert h.repo.rows[mid].deleted_at is None


def test_unknown_session_is_404():
    h = _harness(sessions={})
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post("/api/v2/admin/sessions/nope/announcements", json={"body": "Hi"})
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
def test_blank_bodies_are_rejected(body):
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": body})
    assert r.status_code == 422, r.text
    assert h.repo.rows == {}


def test_an_over_long_body_is_rejected():
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        r = client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "x" * 2001}
        )
    assert r.status_code == 422, r.text


def test_parent_on_the_admin_announcement_route_is_404_not_403():
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h, role="parent") as client:
        r = client.get(f"/api/v2/admin/sessions/{SESSION_ID}/announcements")
    assert r.status_code == 404, r.text


# --- coach surface ------------------------------------------------------


def test_assigned_coach_can_post():
    h = _harness()
    with tenant_scope(ACADEMY), _coach_client(h) as client:
        r = client.post(
            f"/api/v2/coach/sessions/{SESSION_ID}/announcements", json={"body": "Bring water"}
        )

    assert r.status_code == 201, r.text
    assert r.json()["announcement"]["author_persona"] == "coach"
    assert r.json()["announcement"]["author_display_name"] == "Coach Riya"


def test_unassigned_coach_is_403():
    h = _harness()
    with tenant_scope(ACADEMY), _coach_client(h, assigned=False) as client:
        posted = client.post(
            f"/api/v2/coach/sessions/{SESSION_ID}/announcements", json={"body": "Nope"}
        )
        listed = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/announcements")

    assert posted.status_code == 403, posted.text
    assert listed.status_code == 403
    assert h.repo.rows == {}


def test_parent_on_the_coach_announcement_route_is_404():
    h = _harness()
    with tenant_scope(ACADEMY), _coach_client(h, role="parent") as client:
        r = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/announcements")
    assert r.status_code == 404, r.text


def test_coach_deletes_own_but_not_someone_elses():
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as admin:
        admin_post = admin.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "Admin post"}
        ).json()["announcement"]["message_id"]

    with tenant_scope(ACADEMY), _coach_client(h) as coach:
        own = coach.post(
            f"/api/v2/coach/sessions/{SESSION_ID}/announcements", json={"body": "Coach post"}
        ).json()["announcement"]["message_id"]

        assert (
            coach.delete(f"/api/v2/coach/sessions/{SESSION_ID}/announcements/{own}").status_code
            == 204
        )
        forbidden = coach.delete(f"/api/v2/coach/sessions/{SESSION_ID}/announcements/{admin_post}")

    assert forbidden.status_code == 403, forbidden.text
    assert h.repo.rows[admin_post].deleted_at is None


# --- rendering ----------------------------------------------------------


def test_the_email_body_escapes_markup_and_keeps_line_breaks():
    subject, html_body = render_announcement_email(
        session_title="<b>Junior A</b> & friends",
        academy_name="Rally",
        author_display_name="<i>Coach</i>",
        body="<script>alert(1)</script>\nSecond line & more",
    )

    assert "<script>" not in html_body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_body
    assert "Second line &amp; more" in html_body
    assert "<br>" in html_body
    # The title is escaped in the heading; the subject is plain text and is
    # escaped by the provider adapter's own subject handling, never injected
    # into HTML here.
    assert "&lt;b&gt;Junior A&lt;/b&gt;" in html_body
    assert "<i>Coach</i>" not in html_body
    assert "Junior A" in subject


def test_the_stored_body_is_not_pre_escaped():
    """Escaping is a render concern; the portal renders a React text child."""
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as client:
        client.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements",
            json={"body": "5 < 6 & bring <kit>"},
        )

    [stored] = list(h.repo.rows.values())
    assert stored.body == "5 < 6 & bring <kit>"


def test_can_delete_is_computed_per_viewer():
    """The client never re-derives the delete rule; the API states it."""
    h = _harness()
    with tenant_scope(ACADEMY), _admin_client(h) as admin:
        admin.post(
            f"/api/v2/admin/sessions/{SESSION_ID}/announcements", json={"body": "Admin post"}
        )
    with tenant_scope(ACADEMY), _coach_client(h) as coach:
        coach.post(
            f"/api/v2/coach/sessions/{SESSION_ID}/announcements", json={"body": "Coach post"}
        )
        coach_view = coach.get(f"/api/v2/coach/sessions/{SESSION_ID}/announcements").json()
    with tenant_scope(ACADEMY), _admin_client(h) as admin:
        admin_view = admin.get(f"/api/v2/admin/sessions/{SESSION_ID}/announcements").json()

    by_body = {a["body"]: a["can_delete"] for a in coach_view["announcements"]}
    assert by_body == {"Coach post": True, "Admin post": False}
    assert all(a["can_delete"] for a in admin_view["announcements"])
