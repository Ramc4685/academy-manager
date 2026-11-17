"""Calendar subscription end to end over mongomock: link, reset, access, window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from backend.v2.composition import calendar_feed as module
from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    ChildScheduleEntry,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)


@pytest.fixture
def db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            unsubscribe_token_secret="secret", frontend_url="https://academy.example.com"
        ),
    )


def _entry(oid: str, day: date, status: str = "scheduled", reason: str | None = None):
    start = datetime(day.year, day.month, day.day, 23, 0, tzinfo=UTC)
    return ChildScheduleEntry(
        occurrence_id=oid,
        session_id="s1",
        session_title="Beginner",
        location="YWCA",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status=status,
        cancellation_reason=reason,
    )


class _Schedule:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []
        self.entries = [
            _entry("o1", date(2026, 12, 22)),
            _entry("o2", date(2026, 12, 24), "cancelled", "Gym not available"),
        ]

    async def __call__(self, *, parent_id, student_id, frm, to, limit, offset):
        self.calls.append((frm, to))
        rows = [e for e in self.entries if frm <= e.start_at.date() <= to]
        return rows, len(rows)


async def _children(parent_id: str) -> list[dict[str, Any]]:
    return [{"student_id": "stu-1", "full_name": "Maithri Rao"}]


async def _feed(db, schedule=None):
    await db["academies"].insert_one(
        {
            "academy_id": "acad-1",
            "slug": "blno",
            "display_name": "BLNO",
            "timezone": "America/Chicago",
        }
    )
    return module.compose_calendar_feed(
        db,
        list_children_for_parent=_children,
        get_child_schedule=schedule or _Schedule(),
        clock=lambda: NOW,
    )


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1].removesuffix(".ics")


@pytest.mark.asyncio
async def test_link_serves_classes_and_struck_through_no_class_days(db) -> None:
    feed = await _feed(db)
    with tenant_scope("acad-1"):
        url = await feed.feed_url(parent_id="P1")
        assert url is not None
        assert url.startswith("https://blno.example.com/api/v2/calendar-feed/P1.")
        assert await feed.feed_url(parent_id="P1") == url  # stable until reset
        body = await feed.render(_token(url))
    assert body is not None
    assert "SUMMARY:Maithri — Beginner" in body
    assert "SUMMARY:No class — Maithri — Beginner" in body
    assert "DESCRIPTION:Gym not available" in body
    assert "STATUS:CANCELLED" in body
    assert "X-WR-CALNAME:BLNO classes" in body


@pytest.mark.asyncio
async def test_reset_kills_the_old_link(db) -> None:
    feed = await _feed(db)
    with tenant_scope("acad-1"):
        old = await feed.feed_url(parent_id="P1")
        new = await feed.feed_url(parent_id="P1", reset=True)
        assert old != new
        assert await feed.render(_token(old)) is None
        assert await feed.render(_token(new)) is not None


@pytest.mark.asyncio
async def test_link_does_not_work_on_another_academy(db) -> None:
    feed = await _feed(db)
    with tenant_scope("acad-1"):
        url = await feed.feed_url(parent_id="P1")
    with tenant_scope("acad-2"):
        assert await feed.render(_token(url)) is None


@pytest.mark.asyncio
async def test_removed_parent_loses_the_feed(db) -> None:
    feed = await _feed(db)
    with tenant_scope("acad-1"):
        url = await feed.feed_url(parent_id="P1")
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "P1",
            "roles": ["parent"],
            "status": "removed",
            "membership_id": "m1",
        }
    )
    with tenant_scope("acad-1"):
        assert await feed.render(_token(url)) is None


@pytest.mark.asyncio
async def test_feed_stops_at_the_last_published_month(db) -> None:
    schedule = _Schedule()
    feed = await _feed(db, schedule)
    await db["parent_self_service_policies"].insert_one(
        {"academy_id": "acad-1", "schedule_published_through": "2026-11"}
    )
    with tenant_scope("acad-1"):
        url = await feed.feed_url(parent_id="P1")
        body = await feed.render(_token(url))
    assert schedule.calls[-1][1] == date(2026, 11, 30)
    assert body is not None and "VEVENT" not in body  # December is not published


@pytest.mark.asyncio
async def test_no_secret_means_no_link_and_no_feed(db, monkeypatch) -> None:
    feed = await _feed(db)
    with tenant_scope("acad-1"):
        url = await feed.feed_url(parent_id="P1")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(unsubscribe_token_secret=None, frontend_url=""),
    )
    with tenant_scope("acad-1"):
        assert await feed.feed_url(parent_id="P1") is None
        assert await feed.render(_token(url)) is None
