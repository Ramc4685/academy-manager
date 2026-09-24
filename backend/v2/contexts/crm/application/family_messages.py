"""The family Messages tab: read the thread, log a contact (People CRM Phase 6, L4c).

``GetFamilyMessages`` proves the id is a family of the caller's academy (the
family index, #664), resolves the parent's aliases, and asks every source for
its newest rows at once (``asyncio.gather``). A source that fails adds
``"<name>_unavailable"`` to ``warnings`` and the thread is built from the rest
(never a silent gap, never a 500).

``LogFamilyContact`` stores one staff-logged contact (WhatsApp, SMS or email
sent from the staff member's own app, a call, a talk in person) on the
canonical family. ``CompleteFamilyContactLog`` turns a ``not_logged`` handoff
into ``logged`` (the staff member who logged it, or an owner).

The sources (``infrastructure/family_message_sources.py``) read the send logs
the app already keeps; the CRM imports no other context. No message is sent
here: the app never sends SMS or WhatsApp (a later phase).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.v2.contexts.crm.application.ports import FamilyDirectory, ParentAliasResolver
from backend.v2.contexts.crm.application.timeline import FamilyRecordDirectory
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    Actor,
    resolve_family,
    utc_now_ms,
)
from backend.v2.contexts.crm.domain.errors import (
    ContactLogEditForbidden,
    ContactLogNotFound,
    FamilyNotFound,
    InvalidContactLog,
)
from backend.v2.contexts.crm.domain.family_messages import (
    MAX_CONTACT_LOG_NOTE_LEN,
    MESSAGES_CAP,
    FamilyContactLog,
    MessageEntry,
    can_complete_contact_log,
    contact_log_entry,
    merge_messages,
    normalize_contact_log_note,
    parse_channel,
    parse_contact_log_status,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

# Re-exported for the admin BFF (interfaces may not import the domain).
__all__ = [
    "MAX_CONTACT_LOG_NOTE_LEN",
    "MESSAGES_CAP",
    "CompleteFamilyContactLog",
    "FamilyContactLog",
    "FamilyContactLogRepository",
    "FamilyMessagesPage",
    "FamilyMessagesScope",
    "GetFamilyMessages",
    "LogFamilyContact",
    "MessageEntry",
    "contact_log_entry",
]


@dataclass(frozen=True)
class FamilyMessagesScope:
    """What a source needs to find the family's rows in one academy."""

    academy_id: str
    family_id: str
    #: Every id the parent is stored under (canonical id first).
    parent_aliases: tuple[str, ...]
    student_ids: tuple[str, ...]
    student_names: Mapping[str, str]


class FamilyMessageSource(Protocol):
    @property
    def name(self) -> str: ...

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]: ...


class FamilyContactLogRepository(Protocol):
    async def add(self, entry: FamilyContactLog) -> FamilyContactLog: ...

    async def get(self, parent_id: str, log_id: str) -> FamilyContactLog | None: ...

    async def list_for_family(
        self, parent_id: str, *, limit: int = MESSAGES_CAP
    ) -> list[FamilyContactLog]: ...

    async def mark_logged(
        self, parent_id: str, log_id: str, *, note: str | None, logged_at: datetime
    ) -> FamilyContactLog | None:
        """Set ``status: logged`` (and the note when given) on a ``not_logged``
        row; ``None`` when there is no such row."""
        ...


@dataclass(frozen=True)
class FamilyMessagesPage:
    family_id: str
    entries: list[MessageEntry]
    warnings: list[str]


class GetFamilyMessages:
    def __init__(
        self,
        families: FamilyRecordDirectory,
        aliases: ParentAliasResolver,
        sources: Sequence[FamilyMessageSource],
    ) -> None:
        self._families = families
        self._aliases = aliases
        self._sources = tuple(sources)

    async def execute(self, *, academy_id: str, parent_id: str) -> FamilyMessagesPage:
        record = await self._families.find_record(academy_id, parent_id)
        if record is None:
            raise FamilyNotFound("family not found", parent_id=parent_id)
        warnings: list[str] = []
        scope = FamilyMessagesScope(
            academy_id=academy_id,
            family_id=record.family_id,
            parent_aliases=await self._parent_aliases(record.family_id, warnings),
            student_ids=tuple(c.student_id for c in record.children),
            student_names={c.student_id: c.name for c in record.children},
        )
        results = await asyncio.gather(*(self._fetch(s, scope) for s in self._sources))
        batches: list[Sequence[MessageEntry]] = []
        for source, result in zip(self._sources, results, strict=True):
            if result is None:
                warnings.append(f"{source.name}_unavailable")
            else:
                batches.append(result)
        return FamilyMessagesPage(
            family_id=record.family_id,
            entries=merge_messages(batches, cap=MESSAGES_CAP),
            warnings=list(dict.fromkeys(warnings)),
        )

    async def _fetch(
        self, source: FamilyMessageSource, scope: FamilyMessagesScope
    ) -> Sequence[MessageEntry] | None:
        try:
            return await source.fetch(scope)
        except Exception:
            log.warning("family messages: %s source failed", source.name, exc_info=True)
            return None

    async def _parent_aliases(self, family_id: str, warnings: list[str]) -> tuple[str, ...]:
        try:
            resolved = (await self._aliases.resolve_parent_aliases([family_id])).get(family_id)
        except Exception:
            log.warning("family messages: parent aliases failed", exc_info=True)
            warnings.append("parent_aliases_unavailable")
            resolved = None
        rest = sorted(a for a in (resolved.aliases if resolved else ()) if a and a != family_id)
        return (family_id, *rest)


class LogFamilyContact:
    def __init__(
        self,
        logs: FamilyContactLogRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._logs = logs
        self._families = families
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        channel: str,
        status: str,
        note: str | None,
        actor: Actor,
    ) -> FamilyContactLog:
        parsed_channel = parse_channel(channel)
        parsed_status = parse_contact_log_status(status)
        if parsed_status == "not_logged" and parsed_channel in ("call", "in_person"):
            # Only a handoff to the staff member's own app can be unconfirmed.
            raise InvalidContactLog(
                "A call or a talk in person is logged when it happened.", field="status"
            )
        text = normalize_contact_log_note(note)
        family_id = await resolve_family(self._families, academy_id, parent_id)
        now = self._clock()
        return await self._logs.add(
            FamilyContactLog(
                log_id=self._new_id(),
                academy_id=academy_id,
                parent_id=family_id,
                channel=parsed_channel,
                status=parsed_status,
                note=text,
                author_user_id=actor.user_id,
                created_at=now,
                updated_at=now,
                logged_at=now if parsed_status == "logged" else None,
            )
        )


class CompleteFamilyContactLog:
    """ "Did you send it?" answered later: a ``not_logged`` handoff becomes
    ``logged``. Completing an already logged row is a no-op that returns it."""

    def __init__(
        self,
        logs: FamilyContactLogRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
    ) -> None:
        self._logs = logs
        self._families = families
        self._clock = clock

    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        log_id: str,
        note: str | None,
        actor: Actor,
    ) -> FamilyContactLog:
        text = normalize_contact_log_note(note)
        family_id = await resolve_family(self._families, academy_id, parent_id)
        existing = await self._logs.get(family_id, log_id)
        if existing is None:
            raise ContactLogNotFound("contact log not found", log_id=log_id)
        if not can_complete_contact_log(existing, user_id=actor.user_id, roles=actor.roles):
            raise ContactLogEditForbidden(
                "Only the person who logged this, or the academy owner, can complete it.",
                log_id=log_id,
            )
        if existing.status == "logged":
            return existing
        updated = await self._logs.mark_logged(
            family_id, log_id, note=text, logged_at=self._clock()
        )
        if updated is None:  # completed by someone else between the read and the write
            again = await self._logs.get(family_id, log_id)
            if again is None:
                raise ContactLogNotFound("contact log not found", log_id=log_id)
            return again
        return updated
