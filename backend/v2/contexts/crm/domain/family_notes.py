"""Family notes and follow-ups (People CRM spec §5 "Notes" / "Follow-ups", Phase 4a).

Two team-owned records on a family, keyed by the family's canonical parent id:

* ``FamilyNote``: a plain-text note any staff member writes on a family. Only
  its author or an academy owner may edit or delete it; delete is soft
  (``deleted_at``), so a removed note is hidden, never lost.
* ``FamilyFollowUp``: a dated to-do on a family with an assignee, ``open``
  until someone marks it ``done``.

Coach notes are NOT these records: the CRM shows coach notes read-only from
the #665 data and never writes them.

Pure: no I/O, no Mongo types. ``academy_id`` is carried for reads but is
always stamped by the repository from the tenant context on write.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.crm.domain.errors import InvalidFamilyNote, InvalidFollowUp

#: Plain text, line breaks kept, never rendered as HTML.
MAX_NOTE_BODY_LEN: Final = 4000
MAX_FOLLOW_UP_TITLE_LEN: Final = 200

FollowUpStatus = Literal["open", "done"]
FOLLOW_UP_STATUSES: frozenset[str] = frozenset(get_args(FollowUpStatus))

#: The Follow-ups view's buckets (spec §3.5). Overdue, Today and Upcoming are
#: open follow-ups split by ``due_on`` against the academy's local today; Done
#: is every done follow-up, newest first.
FollowUpBucket = Literal["overdue", "today", "upcoming", "done"]
FOLLOW_UP_BUCKETS: frozenset[str] = frozenset(get_args(FollowUpBucket))

#: Academy roles that may edit or delete a note someone else wrote.
NOTE_MODERATOR_ROLES: Final[frozenset[str]] = frozenset({"owner"})

_SPACES = re.compile(r"[ \t\f\v]+")
_WS = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FamilyNote(BaseModel):
    model_config = ConfigDict(frozen=True)

    note_id: str
    academy_id: str
    parent_id: str
    body: str
    author_user_id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    deleted_by: str | None = None


class FamilyFollowUp(BaseModel):
    model_config = ConfigDict(frozen=True)

    follow_up_id: str
    academy_id: str
    parent_id: str
    title: str
    due_on: date
    assignee_user_id: str
    status: FollowUpStatus = "open"
    created_by: str
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None = None
    done_by: str | None = None


def normalize_note_body(raw: str | None) -> str:
    """The stored body: control characters dropped, each line's runs of spaces
    collapsed, trailing space trimmed, at most two blank lines in a row, and the
    whole trimmed. Raises ``InvalidFamilyNote`` when empty or over the cap."""
    text = _CONTROL.sub("", (raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_SPACES.sub(" ", line).rstrip() for line in text.split("\n")]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not body:
        raise InvalidFamilyNote("Write something in the note.", field="body")
    if len(body) > MAX_NOTE_BODY_LEN:
        raise InvalidFamilyNote(
            f"A note can be at most {MAX_NOTE_BODY_LEN} characters.", field="body"
        )
    return body


def normalize_follow_up_title(raw: str | None) -> str:
    title = _WS.sub(" ", _CONTROL.sub("", raw or "")).strip()
    if not title:
        raise InvalidFollowUp("Say what needs doing.", field="title")
    if len(title) > MAX_FOLLOW_UP_TITLE_LEN:
        raise InvalidFollowUp(
            f"A follow-up title can be at most {MAX_FOLLOW_UP_TITLE_LEN} characters.",
            field="title",
        )
    return title


def parse_follow_up_status(raw: str) -> FollowUpStatus:
    if raw not in FOLLOW_UP_STATUSES:
        raise InvalidFollowUp("Status must be open or done.", field="status")
    return raw  # type: ignore[return-value]


def can_edit_note(note: FamilyNote, *, user_id: str, roles: Iterable[str]) -> bool:
    """The note's author, or an academy owner."""
    if note.author_user_id == user_id:
        return True
    return any(role in NOTE_MODERATOR_ROLES for role in roles)


def follow_up_bucket(follow_up: FamilyFollowUp, today: date) -> FollowUpBucket:
    if follow_up.status == "done":
        return "done"
    if follow_up.due_on < today:
        return "overdue"
    if follow_up.due_on == today:
        return "today"
    return "upcoming"
