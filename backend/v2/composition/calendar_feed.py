"""Parent class-calendar subscription: the link a parent adds to their phone,
and the ``.ics`` file that link serves.

Fail-closed: with no signing secret (``unsubscribe_token_secret``, reused with
its own ``calendar-feed:v1`` domain prefix) there is no link and no feed.

The feed carries every child of the parent from about a month back up to the
end of the academy's last published month (or ~6 months ahead when the
academy never publishes), so a phone never shows tentative dates as final.
"""

from __future__ import annotations

import calendar
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.composition.academy_links import academy_frontend_base_url_lookup
from backend.v2.contexts.enrollment.application.calendar_feed import (
    FeedEvent,
    feed_signature_matches,
    mint_feed_token,
    parse_feed_token,
    render_feed,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_calendar_feed_link_repo import (
    MongoCalendarFeedLinkRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
    MongoSelfServicePolicyRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy import current_academy_id

_LOOKBACK_DAYS = 31
_UNPUBLISHED_LOOKAHEAD_DAYS = 183
_SCHEDULE_LIMIT = 1000
_FEED_PATH = "/api/v2/calendar-feed/{token}.ics"


def feed_window(*, today: date, published_through: str | None) -> tuple[date, date] | None:
    """``(from, to)`` inclusive, or ``None`` when nothing is published yet
    that is not already in the past."""
    start = today - timedelta(days=_LOOKBACK_DAYS)
    if published_through is None:
        return start, today + timedelta(days=_UNPUBLISHED_LOOKAHEAD_DAYS)
    year, month = (int(part) for part in published_through.split("-"))
    end = date(year, month, calendar.monthrange(year, month)[1])
    return (start, end) if end >= start else None


def _local_date(value: datetime, zone: ZoneInfo) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)  # stored datetimes are naive UTC
    return value.astimezone(zone).date()


def _no_class_reason(reason: str | None) -> str:
    # A whole-session cancel stamps a machine code, not a sentence.
    if not reason or reason == "session_cancelled":
        return "Class cancelled"
    return reason


@dataclass
class CalendarFeed:
    feed_url: Callable[..., Awaitable[str | None]]
    render: Callable[[str], Awaitable[str | None]]


def compose_calendar_feed(
    db: Any,
    *,
    list_children_for_parent: Callable[[str], Awaitable[list[dict[str, Any]]]],
    get_child_schedule: Callable[..., Awaitable[tuple[list[Any], int]]],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CalendarFeed:
    links = MongoCalendarFeedLinkRepository(db)
    policies = MongoSelfServicePolicyRepository(db)
    memberships = MongoMembershipRepository(db)

    def _secret() -> str | None:
        return get_settings().unsubscribe_token_secret or None

    async def feed_url(*, parent_id: str, reset: bool = False) -> str | None:
        secret = _secret()
        if secret is None:
            return None
        academy_id = current_academy_id()  # request-time tenant (C4)
        version = await links.bump(parent_id) if reset else await links.version_for(parent_id)
        token = mint_feed_token(
            secret=secret, academy_id=academy_id, parent_id=parent_id, version=version
        )
        base_url = academy_frontend_base_url_lookup(db, frontend_url=get_settings().frontend_url)
        return await base_url(academy_id) + _FEED_PATH.format(token=token)

    async def _parent_still_has_access(academy_id: str, parent_id: str) -> bool:
        membership = await memberships.get_membership(academy_id, parent_id)
        # Single-academy legacy parents may have no membership row at all; a
        # row that exists must still be live and still be a parent's.
        if membership is not None and not membership.has_role("parent"):
            return False
        return True

    async def render(token: str) -> str | None:
        """The ``.ics`` body, or ``None`` for any link that is not valid here.

        Runs inside the tenant the request host resolved to."""
        secret = _secret()
        parsed = parse_feed_token(token)
        if secret is None or parsed is None:
            return None
        parent_id, signature = parsed
        academy_id = current_academy_id()
        version = await links.version_for(parent_id)
        if not feed_signature_matches(
            secret=secret,
            academy_id=academy_id,
            parent_id=parent_id,
            version=version,
            signature=signature,
        ):
            return None
        if not await _parent_still_has_access(academy_id, parent_id):
            return None

        academy = await db["academies"].find_one(
            {"academy_id": academy_id}, {"display_name": 1, "timezone": 1}
        )
        try:
            zone = ZoneInfo(str((academy or {}).get("timezone") or "UTC"))
        except (KeyError, ValueError):
            zone = ZoneInfo("UTC")
        now = clock()
        policy = await policies.get_or_default()
        window = feed_window(
            today=now.astimezone(zone).date(),
            published_through=policy.schedule_published_through,
        )
        events: list[FeedEvent] = []
        if window is not None:
            for child in await list_children_for_parent(parent_id):
                first_name = (str(child.get("full_name") or "").split() or ["Class"])[0]
                # The schedule reads ``to`` as a UTC day; ask for one more day
                # and cut on the academy-local date, or a 6:30 pm class on the
                # last day of the month (already the next day in UTC) is lost.
                entries, _total = await get_child_schedule(
                    parent_id=parent_id,
                    student_id=str(child["student_id"]),
                    frm=window[0],
                    to=window[1] + timedelta(days=1),
                    limit=_SCHEDULE_LIMIT,
                    offset=0,
                )
                for entry in entries:
                    if _local_date(entry.start_at, zone) > window[1]:
                        continue
                    cancelled = entry.status == "cancelled"
                    label = f"{first_name} — {entry.session_title}"
                    events.append(
                        FeedEvent(
                            uid=f"{entry.occurrence_id}-{child['student_id']}@academy-manager",
                            title=f"No class — {label}" if cancelled else label,
                            start_at=entry.start_at,
                            end_at=entry.end_at,
                            cancelled=cancelled,
                            location=entry.location,
                            description=(
                                _no_class_reason(entry.cancellation_reason) if cancelled else None
                            ),
                        )
                    )
        name = str((academy or {}).get("display_name") or "Academy")
        return render_feed(calendar_name=f"{name} classes", events=events, now=now)

    return CalendarFeed(feed_url=feed_url, render=render)
