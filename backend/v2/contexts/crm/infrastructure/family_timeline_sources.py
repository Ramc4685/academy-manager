"""Mongo sources of the unified family timeline (People CRM spec §5).

Each source reads its own rows for ONE family of ONE academy, newest first,
at most ``SOURCE_LIMIT`` per query, and turns them into ``TimelineEntry``
values. Every query carries ``academy_id`` (the scope's academy, which is the
request's tenant) and is an equality or ``$in`` lookup on an indexed field;
lookups on a PARTIAL index (the parent-change rows) are asked once per alias,
never as an ``$or`` or ``$in`` across the partial field (#878/#894).

* :class:`AttendanceTimelineSource`: absent marks and corrections of the
  family's children, dated by the class occurrence's ``start_at``.
* :class:`RequestsTimelineSource`: absence notices, pause, makeup and trial
  requests (asked and decided).
* :class:`AdminAuditTimelineSource`: the ``audit_logs`` rows on the parent,
  the children and their enrollments whose action is in
  ``AUDIT_ACTION_ALLOWLIST`` (never ``user_logged_in``), plus "Moved from /
  moved to family" entries from the parent-change rows (#785).
* :class:`CrmRecordsTimelineSource`: the CRM's own family notes, follow-ups
  and family contacts, through their tenant-scoped repositories.

Indexes: migration ``0202_family_timeline_indexes``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from backend.v2.contexts.crm.application.ports import (
    FamilyContactRepository,
    FamilyFollowUpRepository,
    FamilyNoteRepository,
)
from backend.v2.contexts.crm.application.timeline import (
    FamilyTimelineScope,
    TimelineSourceResult,
    day_label,
)
from backend.v2.contexts.crm.domain.timeline import (
    AUDIT_ACTION_ALLOWLIST,
    SOURCE_LIMIT,
    TimelineEntry,
    as_utc,
)


def _dt(value: Any) -> datetime | None:
    return as_utc(value) if isinstance(value, datetime) else None


def _s(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _before(scope: FamilyTimelineScope, field: str) -> dict[str, Any]:
    return {field: {"$lte": scope.before}} if scope.before is not None else {}


def _child(scope: FamilyTimelineScope, student_id: str | None, fallback: Any = None) -> str:
    if student_id and student_id in scope.student_names:
        return scope.student_names[student_id]
    return _s(fallback) or "Child"


# ------------------------------------------------------------------ attendance


class AttendanceTimelineSource:
    name = "attendance"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def _marks(
        self, academy_id: str, student_ids: list[str], extra: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # Served by admin_student_attendance_lookup (academy_id, student_id, marked_at).
        cursor = self._db["attendance"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}, **extra},
            {
                "_id": 0,
                "attendance_id": 1,
                "student_id": 1,
                "session_id": 1,
                "occurrence_id": 1,
                "status": 1,
                "previous_status": 1,
                "marked_at": 1,
                "corrected_at": 1,
                "corrected_by": 1,
                "correction_reason": 1,
                "marked_by": 1,
            },
            sort=[("marked_at", -1)],
            limit=SOURCE_LIMIT,
        )
        return [doc async for doc in cursor]

    async def _occurrence_starts(self, academy_id: str, ids: set[str]) -> dict[str, datetime]:
        if not ids:
            return {}
        cursor = self._db["session_occurrences"].find(
            {"academy_id": academy_id, "occurrence_id": {"$in": sorted(ids)}},
            {"_id": 0, "occurrence_id": 1, "start_at": 1},
        )
        out: dict[str, datetime] = {}
        async for doc in cursor:
            start = _dt(doc.get("start_at"))
            if start is not None:
                out[str(doc["occurrence_id"])] = start
        return out

    async def _session_titles(self, academy_id: str, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": sorted(ids)}},
            {"_id": 0, "session_id": 1, "title": 1, "name": 1},
        )
        return {
            str(doc["session_id"]): str(doc.get("title") or doc.get("name") or "")
            async for doc in cursor
            if doc.get("title") or doc.get("name")
        }

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        if not scope.student_ids:
            return TimelineSourceResult(entries=())
        academy_id = scope.academy_id
        ids = list(scope.student_ids)
        # Two equality-shaped reads, merged by row: absent marks, and any
        # corrected mark (whatever it was corrected to).
        rows: dict[str, dict[str, Any]] = {}
        for extra in ({"status": "absent"}, {"corrected_at": {"$ne": None}}):
            for doc in await self._marks(academy_id, ids, extra):
                key = str(doc.get("attendance_id") or "")
                if key:
                    rows[key] = doc
        starts = await self._occurrence_starts(
            academy_id, {str(d["occurrence_id"]) for d in rows.values() if d.get("occurrence_id")}
        )
        titles = await self._session_titles(
            academy_id, {str(d["session_id"]) for d in rows.values() if d.get("session_id")}
        )
        entries: list[TimelineEntry] = []
        for key, doc in rows.items():
            occurrence = _s(doc.get("occurrence_id"))
            at = (starts.get(occurrence) if occurrence else None) or _dt(doc.get("marked_at"))
            if at is None or (scope.before is not None and at > scope.before):
                continue
            student_id = _s(doc.get("student_id"))
            child = _child(scope, student_id)
            title = titles.get(str(doc.get("session_id") or ""))
            where = f" · {title}" if title else ""
            status = str(doc.get("status") or "")
            if doc.get("corrected_at") is not None:
                previous = _s(doc.get("previous_status")) or "unmarked"
                entries.append(
                    TimelineEntry(
                        entry_id=f"attendance:{key}",
                        at=at,
                        kind="attendance",
                        code="attendance:corrected",
                        summary=f"{child} attendance corrected: {previous} to {status}{where}",
                        source=self.name,
                        student_id=student_id,
                        student_name=child,
                        actor_id=_s(doc.get("corrected_by")),
                        reason=_s(doc.get("correction_reason")),
                    )
                )
            else:
                entries.append(
                    TimelineEntry(
                        entry_id=f"attendance:{key}",
                        at=at,
                        kind="attendance",
                        code="attendance:absent",
                        summary=f"{child} marked absent{where}",
                        source=self.name,
                        student_id=student_id,
                        student_name=child,
                        actor_id=_s(doc.get("marked_by")),
                    )
                )
        return TimelineSourceResult(entries=entries)


# ------------------------------------------------------------------ requests

_DECISIONS = {
    "approved": "approved",
    "declined": "declined",
    "denied": "declined",
    "expired": "expired",
    "completed": "completed",
    "converted": "converted to an application",
}


class RequestsTimelineSource:
    name = "requests"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def _by_students(
        self, collection: str, scope: FamilyTimelineScope, time_field: str
    ) -> list[dict[str, Any]]:
        if not scope.student_ids:
            return []
        cursor = self._db[collection].find(
            {
                "academy_id": scope.academy_id,
                "student_id": {"$in": list(scope.student_ids)},
                **_before(scope, time_field),
            },
            sort=[(time_field, -1)],
            limit=SOURCE_LIMIT,
        )
        return [doc async for doc in cursor]

    async def _trials(self, scope: FamilyTimelineScope) -> list[dict[str, Any]]:
        # One equality lookup per alias on (academy_id, parent_user_id, created_at).
        rows: dict[str, dict[str, Any]] = {}
        for alias in scope.parent_aliases:
            cursor = self._db["trial_requests"].find(
                {
                    "academy_id": scope.academy_id,
                    "parent_user_id": alias,
                    **_before(scope, "created_at"),
                },
                sort=[("created_at", -1)],
                limit=SOURCE_LIMIT,
            )
            async for doc in cursor:
                rows[str(doc.get("request_id") or doc.get("_id"))] = doc
        return list(rows.values())

    @staticmethod
    def _decided(
        prefix: str, row_id: str, doc: dict[str, Any], what: str, **common: Any
    ) -> list[TimelineEntry]:
        decided_at = _dt(doc.get("decided_at"))
        verdict = _DECISIONS.get(str(doc.get("status") or ""))
        if decided_at is None or verdict is None:
            return []
        return [
            TimelineEntry(
                entry_id=f"{prefix}:{row_id}:decided",
                at=decided_at,
                kind="requests",
                code=f"request:{prefix}_{doc.get('status')}",
                summary=f"{what} {verdict}",
                actor_id=_s(doc.get("decided_by")),
                reason=_s(doc.get("denial_reason")),
                **common,
            )
        ]

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        entries: list[TimelineEntry] = []

        for doc in await self._by_students("absence_notices", scope, "submitted_at"):
            at = _dt(doc.get("submitted_at"))
            if at is None:
                continue
            sid = _s(doc.get("student_id"))
            child = _child(scope, sid)
            by = " (recorded by staff)" if doc.get("recorded_by_admin") else ""
            entries.append(
                TimelineEntry(
                    entry_id=f"absence_notice:{doc.get('notice_id') or doc.get('_id')}",
                    at=at,
                    kind="requests",
                    code="request:absence_notice",
                    summary=f"Absence notice for {child}{by}",
                    source=self.name,
                    student_id=sid,
                    student_name=child,
                    actor_id=_s(doc.get("submitted_by")),
                )
            )

        for doc in await self._by_students("pause_requests", scope, "created_at"):
            at = _dt(doc.get("created_at"))
            if at is None:
                continue
            row_id = str(doc.get("pause_request_id") or doc.get("_id"))
            sid = _s(doc.get("student_id"))
            child = _child(scope, sid, doc.get("student_name"))
            title = _s(doc.get("session_title"))
            what = f"Pause request for {child}" + (f" · {title}" if title else "")
            common: dict[str, Any] = {
                "source": self.name,
                "student_id": sid,
                "student_name": child,
                "enrollment_id": _s(doc.get("enrollment_id")),
            }
            entries.append(
                TimelineEntry(
                    entry_id=f"pause:{row_id}:asked",
                    at=at,
                    kind="requests",
                    code="request:pause_asked",
                    summary=f"{what} sent",
                    reason=_s(doc.get("reason")),
                    **common,
                )
            )
            entries.extend(self._decided("pause", row_id, doc, what, **common))

        for doc in await self._by_students("makeup_requests", scope, "created_at"):
            at = _dt(doc.get("created_at"))
            if at is None:
                continue
            row_id = str(doc.get("request_id") or doc.get("_id"))
            sid = _s(doc.get("student_id"))
            child = _child(scope, sid)
            what = f"Makeup class request for {child}"
            common = {"source": self.name, "student_id": sid, "student_name": child}
            entries.append(
                TimelineEntry(
                    entry_id=f"makeup:{row_id}:asked",
                    at=at,
                    kind="requests",
                    code="request:makeup_asked",
                    summary=f"{what} sent",
                    **common,
                )
            )
            entries.extend(self._decided("makeup", row_id, doc, what, **common))

        for doc in await self._trials(scope):
            at = _dt(doc.get("created_at"))
            if at is None:
                continue
            row_id = str(doc.get("request_id") or doc.get("_id"))
            sid = _s(doc.get("student_id"))
            child = _child(scope, sid, doc.get("prospective_child_name"))
            what = f"Trial class request for {child}"
            common = {"source": self.name, "student_id": sid, "student_name": child}
            entries.append(
                TimelineEntry(
                    entry_id=f"trial:{row_id}:asked",
                    at=at,
                    kind="requests",
                    code="request:trial_asked",
                    summary=f"{what} sent",
                    **common,
                )
            )
            entries.extend(self._decided("trial", row_id, doc, what, **common))

        return TimelineSourceResult(entries=entries)


# ------------------------------------------------------------------ admin audit

_PARENT_CHANGED = "student.parent_changed"


class AdminAuditTimelineSource:
    name = "admin_audit"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def _enrollment_ids(self, academy_id: str, student_ids: Sequence[str]) -> list[str]:
        if not student_ids:
            return []
        cursor = self._db["enrollments"].find(
            {"academy_id": academy_id, "student_id": {"$in": list(student_ids)}},
            {"_id": 0, "enrollment_id": 1},
        )
        return [str(d["enrollment_id"]) async for d in cursor if d.get("enrollment_id")]

    async def _student_names(self, academy_id: str, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        cursor = self._db["students"].find(
            {"academy_id": academy_id, "student_id": {"$in": sorted(ids)}},
            {"_id": 0, "student_id": 1, "full_name": 1, "first_name": 1, "last_name": 1, "name": 1},
        )
        out: dict[str, str] = {}
        async for doc in cursor:
            name = doc.get("full_name") or doc.get("name")
            if not name:
                name = " ".join(p for p in (doc.get("first_name"), doc.get("last_name")) if p)
            if name:
                out[str(doc["student_id"])] = str(name)
        return out

    async def _rows(self, scope: FamilyTimelineScope) -> dict[str, dict[str, Any]]:
        academy_id = scope.academy_id
        entity_ids = [
            *scope.parent_aliases,
            *scope.student_ids,
            *await self._enrollment_ids(academy_id, scope.student_ids),
        ]
        rows: dict[str, dict[str, Any]] = {}
        # (academy_id, entity_id, created_at): audit_logs_academy_entity_created.
        cursor = self._db["audit_logs"].find(
            {
                "academy_id": academy_id,
                "entity_id": {"$in": entity_ids},
                "action": {"$in": sorted(AUDIT_ACTION_ALLOWLIST)},
                **_before(scope, "created_at"),
            },
            sort=[("created_at", -1)],
            limit=SOURCE_LIMIT,
        )
        async for doc in cursor:
            rows[str(doc.get("audit_id") or doc.get("_id"))] = doc
        # A child who LEFT this family is no longer among its children: find
        # the parent-change rows by the family's side, one equality per alias
        # and per field on the partial 0202 indexes (never $or, #878).
        for field in ("old_parent_id", "new_parent_id"):
            for alias in scope.parent_aliases:
                cursor = self._db["audit_logs"].find(
                    {
                        "academy_id": academy_id,
                        field: alias,
                        "action": _PARENT_CHANGED,
                        **_before(scope, "created_at"),
                    },
                    sort=[("created_at", -1)],
                    limit=SOURCE_LIMIT,
                )
                async for doc in cursor:
                    rows[str(doc.get("audit_id") or doc.get("_id"))] = doc
        return rows

    def _family_name(self, scope: FamilyTimelineScope, parent_id: Any) -> str:
        name = scope.family_names.get(str(parent_id or ""))
        return f"family {name}" if name else "another family"

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        rows = await self._rows(scope)
        unknown = {
            str(d.get("entity_id"))
            for d in rows.values()
            if d.get("entity_type") == "student"
            and d.get("entity_id")
            and str(d.get("entity_id")) not in scope.student_names
        }
        other_names = await self._student_names(scope.academy_id, unknown)
        aliases = set(scope.parent_aliases)
        entries: list[TimelineEntry] = []
        for audit_id, doc in rows.items():
            at = _dt(doc.get("created_at"))
            action = str(doc.get("action") or "")
            if at is None or action not in AUDIT_ACTION_ALLOWLIST:
                continue
            entity_type = str(doc.get("entity_type") or "")
            entity_id = _s(doc.get("entity_id"))
            student_id = entity_id if entity_type == "student" else None
            child = (
                _child(scope, student_id, other_names.get(student_id or "")) if student_id else None
            )
            enrollment_id = entity_id if entity_type == "enrollment" else None
            reason = _s(doc.get("reason"))
            code = f"audit:{action}"
            if action == _PARENT_CHANGED:
                old, new = _s(doc.get("old_parent_id")), _s(doc.get("new_parent_id"))
                if new in aliases:
                    code = "audit:moved_in"
                    summary = f"{child} moved from {self._family_name(scope, old)}"
                elif old in aliases:
                    code = "audit:moved_out"
                    summary = f"{child} moved to {self._family_name(scope, new)}"
                else:
                    summary = (
                        f"{child} moved from {self._family_name(scope, old)}"
                        f" to {self._family_name(scope, new)}"
                    )
            else:
                label = AUDIT_ACTION_ALLOWLIST[action]
                keys = [str(k).replace("_", " ") for k in doc.get("changed_keys") or ()]
                parts = [label]
                if child:
                    parts.append(child)
                if keys:
                    parts.append(", ".join(keys))
                summary = " · ".join(parts)
            if reason:
                summary = f"{summary} · {reason}"
            entries.append(
                TimelineEntry(
                    entry_id=f"audit:{audit_id}",
                    at=at,
                    kind="admin",
                    code=code,
                    summary=summary,
                    source=self.name,
                    student_id=student_id,
                    student_name=child,
                    enrollment_id=enrollment_id,
                    actor_id=_s(doc.get("actor_id")),
                    reason=reason,
                )
            )
        return TimelineSourceResult(entries=entries)


# ------------------------------------------------------------------ CRM records


class CrmRecordsTimelineSource:
    """The CRM's own rows: team notes, follow-ups and family contacts."""

    name = "crm"

    def __init__(
        self,
        notes: FamilyNoteRepository,
        follow_ups: FamilyFollowUpRepository,
        contacts: FamilyContactRepository,
    ) -> None:
        self._notes = notes
        self._follow_ups = follow_ups
        self._contacts = contacts

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        family_id = scope.family_id
        entries: list[TimelineEntry] = []
        for note in await self._notes.list_for_family(family_id, limit=SOURCE_LIMIT):
            entries.append(
                TimelineEntry(
                    entry_id=f"note:{note.note_id}",
                    at=as_utc(note.created_at),
                    kind="crm",
                    code="crm:note_added",
                    summary="Team note added",
                    source=self.name,
                    detail=note.body,
                    actor_id=note.author_user_id,
                )
            )
        for fu in await self._follow_ups.list_for_family(family_id, limit=SOURCE_LIMIT):
            entries.append(
                TimelineEntry(
                    entry_id=f"follow_up:{fu.follow_up_id}:created",
                    at=as_utc(fu.created_at),
                    kind="crm",
                    code="crm:follow_up_added",
                    summary=f"Follow-up added: {fu.title} · due {day_label(fu.due_on)}",
                    source=self.name,
                    actor_id=fu.created_by,
                )
            )
            if fu.status == "done" and fu.done_at is not None:
                entries.append(
                    TimelineEntry(
                        entry_id=f"follow_up:{fu.follow_up_id}:done",
                        at=as_utc(fu.done_at),
                        kind="crm",
                        code="crm:follow_up_done",
                        summary=f"Follow-up done: {fu.title}",
                        source=self.name,
                        actor_id=fu.done_by,
                    )
                )
        for contact in await self._contacts.list_for_family(family_id, limit=SOURCE_LIMIT):
            relationship = str(contact.relationship).replace("_", " ")
            entries.append(
                TimelineEntry(
                    entry_id=f"family_contact:{contact.contact_id}",
                    at=as_utc(contact.created_at),
                    kind="crm",
                    code="crm:contact_added",
                    summary=f"Contact added: {contact.name} ({relationship})",
                    source=self.name,
                    actor_id=contact.created_by,
                )
            )
        if scope.before is not None:
            entries = [e for e in entries if e.at <= scope.before]
        return TimelineSourceResult(entries=entries)
