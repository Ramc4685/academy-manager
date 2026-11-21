"""HTTP surface of the class-calendar feature: parent link, public .ics,
admin publish month, and the no-class reason on the parent schedule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    ChildScheduleEntry,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.calendar_feed_routes import router as feed_router
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id="P1",
        email="p@example.com",
        academy_id="acad-1",
        roles=(role,),  # type: ignore[arg-type]
    )


class _Feed:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.resets = 0
        self.rendered_in: list[str] = []

    async def feed_url(self, *, parent_id: str, reset: bool = False) -> str | None:
        if not self.configured:
            return None
        self.resets += int(reset)
        return f"https://blno.example.com/api/v2/calendar-feed/{parent_id}.v{self.resets}.ics"

    async def render(self, token: str) -> str | None:
        from backend.v2.shared.tenancy import current_academy_id

        self.rendered_in.append(current_academy_id())
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n" if token == "good" else None


def _parent_app(feed: _Feed | None, *, entries: list[ChildScheduleEntry] | None = None):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")

    async def get_child_schedule(**_kwargs):
        return entries or [], len(entries or [])

    use_cases = SimpleNamespace(calendar_feed=feed, get_child_schedule=get_child_schedule)
    app.dependency_overrides[get_auth_claims] = lambda: _claims("parent")
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    return TestClient(app)


def test_parent_gets_and_resets_their_link() -> None:
    feed = _Feed()
    client = _parent_app(feed)
    first = client.get("/api/v2/parent/calendar-feed")
    assert first.status_code == 200
    assert first.json()["url"].endswith("/calendar-feed/P1.v0.ics")
    reset = client.post("/api/v2/parent/calendar-feed/reset")
    assert reset.status_code == 200 and reset.json()["url"].endswith("P1.v1.ics")


def test_parent_link_is_404_when_not_configured() -> None:
    assert (
        _parent_app(_Feed(configured=False)).get("/api/v2/parent/calendar-feed").status_code == 404
    )
    assert _parent_app(None).get("/api/v2/parent/calendar-feed").status_code == 404


def test_schedule_carries_the_no_class_reason() -> None:
    start = datetime(2026, 12, 24, 23, tzinfo=UTC)
    entry = ChildScheduleEntry(
        occurrence_id="o2",
        session_id="s1",
        session_title="Beginner",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status="cancelled",
        cancellation_reason="Gym not available",
    )
    body = (
        _parent_app(_Feed(), entries=[entry]).get("/api/v2/parent/children/stu-1/schedule").json()
    )
    assert body["entries"][0]["cancellation_reason"] == "Gym not available"


def _feed_app(feed: _Feed | None, *, academy_id: str | None = "acad-1") -> TestClient:
    app = FastAPI()
    app.include_router(feed_router, prefix="/api/v2")
    app.state.parent = SimpleNamespace(calendar_feed=feed)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):
        request.state.resolved_academy_id = academy_id
        return await call_next(request)

    return TestClient(app)


def test_public_feed_serves_ics_inside_the_host_tenant_without_login() -> None:
    feed = _Feed()
    response = _feed_app(feed).get("/api/v2/calendar-feed/good.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("BEGIN:VCALENDAR")
    assert feed.rendered_in == ["acad-1"]


def test_public_feed_failures_are_one_opaque_404() -> None:
    assert _feed_app(_Feed()).get("/api/v2/calendar-feed/bad.ics").status_code == 404
    assert (
        _feed_app(_Feed(), academy_id=None).get("/api/v2/calendar-feed/good.ics").status_code == 404
    )
    assert _feed_app(None).get("/api/v2/calendar-feed/good.ics").status_code == 404


class _Policies:
    def __init__(self) -> None:
        self.month: str | None = None

    async def execute(self, month: str | None = "unset"):  # serves both use cases
        if month != "unset":
            self.month = month
        return SimpleNamespace(schedule_published_through=self.month)


def _admin_app(role: str = "admin") -> tuple[TestClient, _Policies]:
    policies = _Policies()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    use_cases = SimpleNamespace(
        self_service_policy=policies, set_schedule_published_through=policies
    )
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return TestClient(app), policies


def test_admin_publishes_and_withdraws_a_month() -> None:
    client, policies = _admin_app()
    assert client.get("/api/v2/admin/schedule/publish").json() == {"published_through": None}
    put = client.put("/api/v2/admin/schedule/publish", json={"published_through": "2026-12"})
    assert put.status_code == 200 and put.json() == {"published_through": "2026-12"}
    assert policies.month == "2026-12"
    cleared = client.put("/api/v2/admin/schedule/publish", json={"published_through": None})
    assert cleared.json() == {"published_through": None}


def test_admin_publish_rejects_bad_month_and_non_admins() -> None:
    client, _ = _admin_app()
    assert (
        client.put(
            "/api/v2/admin/schedule/publish", json={"published_through": "2026-13"}
        ).status_code
        == 422
    )
    parent_client, _ = _admin_app(role="parent")
    assert parent_client.get("/api/v2/admin/schedule/publish").status_code == 404
