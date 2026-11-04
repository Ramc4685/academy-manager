"""Family follow-ups: list, add, change, mark done, and the cross-family queue.

People CRM spec §3.5 and §5 "Follow-ups". A follow-up belongs to one family
(proved through ``FamilyDirectory``, canonical id stored) and is assigned to a
staff member of the academy (admin or owner, checked through
``StaffDirectory``). Any admin may change or complete any follow-up: they are
the team's shared to-do list.

``ListFollowUps`` is ``GET /admin/follow-ups``: the academy's open
follow-ups split into Overdue / Today / Upcoming by ``due_on`` against the
academy's local today, or its Done ones, for everyone or only the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.crm.application.ports import (
    FamilyDirectory,
    FamilyFollowUpRepository,
    StaffDirectory,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    Actor,
    resolve_family,
    utc_now_ms,
)
from backend.v2.contexts.crm.domain.errors import FamilyFollowUpNotFound, InvalidFollowUp
from backend.v2.contexts.crm.domain.family_notes import (
    FOLLOW_UP_BUCKETS,
    MAX_FOLLOW_UP_TITLE_LEN,
    FamilyFollowUp,
    FollowUpBucket,
    follow_up_bucket,
    normalize_follow_up_title,
    parse_follow_up_status,
)
from backend.v2.shared.ids import new_ulid

# Re-exported for the admin BFF (interfaces may not import the domain).
__all__ = [
    "MAX_FOLLOW_UP_TITLE_LEN",
    "AddFamilyFollowUp",
    "FamilyFollowUp",
    "FamilyFollowUps",
    "FollowUpChanges",
    "FollowUpQueue",
    "FollowUpQueueItem",
    "ListFamilyFollowUps",
    "ListFollowUps",
    "UpdateFamilyFollowUp",
    "academy_today",
    "follow_up_bucket",
]

log = logging.getLogger(__name__)

AcademyTimezone = Callable[[str], Awaitable[str | None]]

#: A follow-up due more than this far out is almost certainly a typo.
MAX_DAYS_AHEAD = 3 * 366


async def academy_today(timezone: AcademyTimezone, academy_id: str, now: datetime) -> date:
    """The academy's local date. An unset or unknown zone reads as UTC."""
    try:
        zone = ZoneInfo((await timezone(academy_id)) or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return aware.astimezone(zone).date()


def _check_due_on(due_on: date, today: date) -> date:
    if (due_on - today).days > MAX_DAYS_AHEAD:
        raise InvalidFollowUp("Pick a due date within the next three years.", field="due_on")
    return due_on


async def _check_assignee(staff: StaffDirectory, academy_id: str, user_id: str) -> str:
    assignee = (user_id or "").strip()
    if not assignee or not await staff.is_staff(academy_id, assignee):
        raise InvalidFollowUp("Assign it to a staff member of this academy.", field="assignee")
    return assignee


class _FollowUpUseCase:
    def __init__(
        self,
        follow_ups: FamilyFollowUpRepository,
        families: FamilyDirectory,
        staff: StaffDirectory,
        timezone: AcademyTimezone,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._follow_ups = follow_ups
        self._families = families
        self._staff = staff
        self._timezone = timezone
        self._clock = clock
        self._new_id = new_id

    async def today(self, academy_id: str) -> date:
        return await academy_today(self._timezone, academy_id, self._clock())


@dataclass(frozen=True)
class FamilyFollowUps:
    family_id: str
    today: date
    follow_ups: list[FamilyFollowUp]


class ListFamilyFollowUps(_FollowUpUseCase):
    async def execute(self, *, academy_id: str, parent_id: str) -> FamilyFollowUps:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        rows = await self._follow_ups.list_for_family(family_id)
        return FamilyFollowUps(family_id, await self.today(academy_id), rows)


class AddFamilyFollowUp(_FollowUpUseCase):
    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        title: str,
        due_on: date,
        assignee_user_id: str,
        actor: Actor,
    ) -> FamilyFollowUp:
        clean_title = normalize_follow_up_title(title)
        family_id = await resolve_family(self._families, academy_id, parent_id)
        _check_due_on(due_on, await self.today(academy_id))
        assignee = await _check_assignee(self._staff, academy_id, assignee_user_id)
        now = self._clock()
        return await self._follow_ups.add(
            FamilyFollowUp(
                follow_up_id=self._new_id(),
                academy_id=academy_id,
                parent_id=family_id,
                title=clean_title,
                due_on=due_on,
                assignee_user_id=assignee,
                status="open",
                created_by=actor.user_id,
                created_at=now,
                updated_at=now,
            )
        )


@dataclass(frozen=True)
class FollowUpChanges:
    """Only the fields the caller sent; None means "leave it"."""

    title: str | None = None
    due_on: date | None = None
    assignee_user_id: str | None = None
    status: str | None = None


class UpdateFamilyFollowUp(_FollowUpUseCase):
    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        follow_up_id: str,
        changes: FollowUpChanges,
        actor: Actor,
    ) -> FamilyFollowUp:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        current = await self._follow_ups.get(family_id, follow_up_id)
        if current is None:
            raise FamilyFollowUpNotFound("follow-up not found", follow_up_id=follow_up_id)
        now = self._clock()
        fields: dict[str, Any] = {}
        if changes.title is not None:
            fields["title"] = normalize_follow_up_title(changes.title)
        if changes.due_on is not None:
            fields["due_on"] = _check_due_on(changes.due_on, await self.today(academy_id))
        if changes.assignee_user_id is not None:
            fields["assignee_user_id"] = await _check_assignee(
                self._staff, academy_id, changes.assignee_user_id
            )
        if changes.status is not None:
            status = parse_follow_up_status(changes.status)
            if status != current.status:
                fields["status"] = status
                fields["done_at"] = now if status == "done" else None
                fields["done_by"] = actor.user_id if status == "done" else None
        if not fields:
            return current
        fields["updated_at"] = now
        updated = await self._follow_ups.update(family_id, follow_up_id, changes=fields)
        if updated is None:  # pragma: no cover - follow-ups are never deleted
            raise FamilyFollowUpNotFound("follow-up not found", follow_up_id=follow_up_id)
        return updated


@dataclass(frozen=True)
class FollowUpQueueItem:
    follow_up: FamilyFollowUp
    family_name: str | None


@dataclass(frozen=True)
class FollowUpQueue:
    today: date
    bucket: FollowUpBucket | None
    items: list[FollowUpQueueItem]


class ListFollowUps(_FollowUpUseCase):
    async def execute(
        self,
        *,
        academy_id: str,
        assignee_user_id: str | None,
        bucket: str | None,
        limit: int = 200,
    ) -> FollowUpQueue:
        if bucket is not None and bucket not in FOLLOW_UP_BUCKETS:
            raise InvalidFollowUp("Unknown follow-up bucket.", field="bucket")
        today = await self.today(academy_id)
        if bucket == "done":
            rows = await self._follow_ups.list_by_status(
                "done", assignee_user_id=assignee_user_id, limit=limit
            )
        else:
            rows = await self._follow_ups.list_by_status(
                "open",
                assignee_user_id=assignee_user_id,
                due_before=today if bucket == "overdue" else None,
                due_on=today if bucket == "today" else None,
                due_after=today if bucket == "upcoming" else None,
                limit=limit,
            )
        names: Mapping[str, str | None] = {}
        if rows:
            try:
                names = await self._families.names(academy_id)
            except Exception:  # a missing label never hides the queue
                log.warning("follow-up queue: family names unavailable", exc_info=True)
        return FollowUpQueue(
            today=today,
            bucket=bucket,  # type: ignore[arg-type]
            items=[FollowUpQueueItem(row, names.get(row.parent_id)) for row in rows],
        )
