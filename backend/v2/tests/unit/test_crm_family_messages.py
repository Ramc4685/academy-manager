"""Family Messages tab (People CRM Phase 6, L4c): domain rules and use cases.

The in-memory log repository mirrors the Mongo one: ``add`` refuses a reused
id, reads filter ``parent_id``, and ``mark_logged`` only changes a
``not_logged`` row (the conditional update), returning ``None`` otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.application.family_messages import (
    CompleteFamilyContactLog,
    FamilyMessagesScope,
    GetFamilyMessages,
    LogFamilyContact,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.contexts.crm.domain.errors import (
    ContactLogEditForbidden,
    ContactLogNotFound,
    DuplicateCrmRecordId,
    FamilyNotFound,
    InvalidContactLog,
)
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyRecord
from backend.v2.contexts.crm.domain.family_messages import (
    MAX_CONTACT_LOG_NOTE_LEN,
    FamilyContactLog,
    MessageEntry,
    contact_log_entry,
    merge_messages,
    normalize_contact_log_note,
)

A = "acad-a"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _entry(entry_id: str, minutes: int, **kw: Any) -> MessageEntry:
    return MessageEntry(
        entry_id=entry_id,
        at=T0 + timedelta(minutes=minutes),
        channel=kw.pop("channel", "email"),
        source=kw.pop("source", "campaign"),
        status=kw.pop("status", "sent"),
        summary=kw.pop("summary", "x"),
        **kw,
    )


# ------------------------------------------------------------------ domain


def test_merge_is_newest_first_deduped_and_capped() -> None:
    naive = MessageEntry(
        entry_id="naive",
        at=datetime(2026, 9, 1, 15, 30),  # naive from Mongo: read as UTC (#706)
        channel="email",
        source="digest",
        status="sent",
        summary="d",
    )
    merged = merge_messages(
        [[_entry("b", 10), _entry("a", 10)], [_entry("b", 99), naive, _entry("c", 0)]], cap=3
    )
    assert [e.entry_id for e in merged] == ["naive", "a", "b"]


def test_note_is_normalized_and_capped() -> None:
    assert normalize_contact_log_note("  hi\x00  there \r\n\n\n\nbye ") == "hi there\n\nbye"
    assert normalize_contact_log_note("   ") is None
    assert normalize_contact_log_note(None) is None
    with pytest.raises(InvalidContactLog):
        normalize_contact_log_note("x" * (MAX_CONTACT_LOG_NOTE_LEN + 1))


def _log(**kw: Any) -> FamilyContactLog:
    base: dict[str, Any] = {
        "log_id": "l-1",
        "academy_id": A,
        "parent_id": "p-1",
        "channel": "whatsapp",
        "status": "logged",
        "note": "See you Saturday",
        "author_user_id": "u-1",
        "created_at": T0,
        "updated_at": T0,
        "logged_at": T0,
    }
    base.update(kw)
    return FamilyContactLog(**base)


def test_contact_log_entry_summaries() -> None:
    assert contact_log_entry(_log()).summary == "WhatsApp sent from staff's own app"
    pending = contact_log_entry(_log(channel="sms", status="not_logged", logged_at=None))
    assert pending.summary == "SMS opened, not confirmed as sent"
    assert pending.status == "not_logged" and pending.log_id == "l-1"
    assert pending.at == T0
    assert contact_log_entry(_log(channel="call")).summary == "Phone call"
    assert contact_log_entry(_log(channel="in_person")).summary == "Spoke in person"


# ------------------------------------------------------------------ fakes


class FakeLogs:
    def __init__(self) -> None:
        self.rows: dict[str, FamilyContactLog] = {}

    async def add(self, entry: FamilyContactLog) -> FamilyContactLog:
        if entry.log_id in self.rows:
            raise DuplicateCrmRecordId("dup", log_id=entry.log_id)
        self.rows[entry.log_id] = entry
        return entry

    async def get(self, parent_id: str, log_id: str) -> FamilyContactLog | None:
        row = self.rows.get(log_id)
        return row if row is not None and row.parent_id == parent_id else None

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyContactLog]:
        rows = [r for r in self.rows.values() if r.parent_id == parent_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def mark_logged(
        self, parent_id: str, log_id: str, *, note: str | None, logged_at: datetime
    ) -> FamilyContactLog | None:
        row = await self.get(parent_id, log_id)
        if row is None or row.status != "not_logged":
            return None
        changes: dict[str, Any] = {
            "status": "logged",
            "logged_at": logged_at,
            "updated_at": logged_at,
        }
        if note is not None:
            changes["note"] = note
        updated = row.model_copy(update=changes)
        self.rows[log_id] = updated
        return updated


class FamilyRef:
    def __init__(self, family_id: str) -> None:
        self.family_id = family_id
        self.parent_name = "Testparent One"


class Directory:
    """``p-1`` and its alias ``fb-p-1`` are the one family of academy A."""

    async def find(self, academy_id: str, family_id: str) -> FamilyRef | None:
        if academy_id == A and family_id in ("p-1", "fb-p-1"):
            return FamilyRef("p-1")
        return None

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        return {}

    async def find_record(self, academy_id: str, family_id: str) -> FamilyRecord | None:
        if academy_id != A or family_id not in ("p-1", "fb-p-1"):
            return None
        return FamilyRecord(
            family_id="p-1",
            parent_name="Testparent One",
            email=None,
            phone=None,
            has_account=True,
            children=(FamilyChild(student_id="s-1", name="Kid Alpha", lifecycle="active"),),
            stage="active",
        )


class Resolved:
    canonical_id = "p-1"
    aliases = frozenset({"p-1", "fb-p-1"})
    display_name = None
    email = None
    phone = None


class Aliases:
    async def resolve_parent_aliases(self, raw_ids: Sequence[str]) -> Mapping[str, Any]:
        return {"p-1": Resolved()}


class Fixed:
    def __init__(self, name: str, entries: Sequence[MessageEntry]) -> None:
        self.name = name
        self._entries = entries
        self.scopes: list[FamilyMessagesScope] = []

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        self.scopes.append(scope)
        return self._entries


class Broken:
    name = "digest"

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        raise RuntimeError("boom")


ADMIN = Actor(user_id="u-1", roles=("admin",))
OTHER = Actor(user_id="u-2", roles=("admin",))
OWNER = Actor(user_id="u-3", roles=("owner",))


def _clock() -> datetime:
    return T0


# ------------------------------------------------------------------ read


async def test_thread_merges_sources_and_reports_a_failed_one() -> None:
    campaigns = Fixed("campaigns", [_entry("campaign:1", 5), _entry("campaign:2", 1)])
    logs = Fixed("contact_log", [_entry("log:1", 3, source="staff_log", channel="call")])
    use_case = GetFamilyMessages(Directory(), Aliases(), [campaigns, Broken(), logs])
    page = await use_case.execute(academy_id=A, parent_id="fb-p-1")
    assert page.family_id == "p-1"
    assert [e.entry_id for e in page.entries] == ["campaign:1", "log:1", "campaign:2"]
    assert page.warnings == ["digest_unavailable"]
    scope = campaigns.scopes[0]
    assert scope.parent_aliases == ("p-1", "fb-p-1")
    assert scope.student_ids == ("s-1",)
    assert scope.student_names == {"s-1": "Kid Alpha"}


async def test_thread_of_another_academys_family_is_not_found() -> None:
    use_case = GetFamilyMessages(Directory(), Aliases(), [])
    with pytest.raises(FamilyNotFound):
        await use_case.execute(academy_id="acad-b", parent_id="p-1")


# ------------------------------------------------------------------ log


async def test_log_lands_on_the_canonical_family() -> None:
    logs = FakeLogs()
    use_case = LogFamilyContact(logs, Directory(), clock=_clock, new_id=lambda: "l-1")
    row = await use_case.execute(
        academy_id=A,
        parent_id="fb-p-1",
        channel="whatsapp",
        status="logged",
        note="  Reminder about Saturday ",
        actor=ADMIN,
    )
    assert row.parent_id == "p-1"
    assert row.note == "Reminder about Saturday"
    assert row.logged_at == T0 and row.author_user_id == "u-1"


async def test_not_logged_handoff_has_no_logged_at() -> None:
    logs = FakeLogs()
    use_case = LogFamilyContact(logs, Directory(), clock=_clock, new_id=lambda: "l-1")
    row = await use_case.execute(
        academy_id=A, parent_id="p-1", channel="sms", status="not_logged", note=None, actor=ADMIN
    )
    assert row.status == "not_logged" and row.logged_at is None


@pytest.mark.parametrize(
    ("channel", "status", "field"),
    [
        ("pigeon", "logged", "channel"),
        ("sms", "maybe", "status"),
        ("call", "not_logged", "status"),
        ("in_person", "not_logged", "status"),
    ],
)
async def test_log_rejects_bad_input(channel: str, status: str, field: str) -> None:
    use_case = LogFamilyContact(FakeLogs(), Directory(), clock=_clock)
    with pytest.raises(InvalidContactLog) as err:
        await use_case.execute(
            academy_id=A, parent_id="p-1", channel=channel, status=status, note=None, actor=ADMIN
        )
    assert err.value.details["field"] == field


async def test_log_on_another_academys_family_is_not_found() -> None:
    use_case = LogFamilyContact(FakeLogs(), Directory(), clock=_clock)
    with pytest.raises(FamilyNotFound):
        await use_case.execute(
            academy_id="acad-b",
            parent_id="p-1",
            channel="call",
            status="logged",
            note=None,
            actor=ADMIN,
        )


# ------------------------------------------------------------------ complete


async def _pending(logs: FakeLogs) -> None:
    await LogFamilyContact(logs, Directory(), clock=_clock, new_id=lambda: "l-1").execute(
        academy_id=A, parent_id="p-1", channel="sms", status="not_logged", note="hi", actor=ADMIN
    )


async def test_author_completes_a_pending_handoff() -> None:
    logs = FakeLogs()
    await _pending(logs)
    later = T0 + timedelta(hours=1)
    use_case = CompleteFamilyContactLog(logs, Directory(), clock=lambda: later)
    row = await use_case.execute(
        academy_id=A, parent_id="fb-p-1", log_id="l-1", note=None, actor=ADMIN
    )
    assert row.status == "logged" and row.logged_at == later
    assert row.note == "hi"  # no note given: the pre-filled text stays
    # Completing again is a no-op that returns the logged row.
    again = await use_case.execute(
        academy_id=A, parent_id="p-1", log_id="l-1", note="x", actor=ADMIN
    )
    assert again.note == "hi" and again.logged_at == later


async def test_owner_may_complete_another_admin_may_not() -> None:
    logs = FakeLogs()
    await _pending(logs)
    use_case = CompleteFamilyContactLog(logs, Directory(), clock=_clock)
    with pytest.raises(ContactLogEditForbidden):
        await use_case.execute(academy_id=A, parent_id="p-1", log_id="l-1", note=None, actor=OTHER)
    row = await use_case.execute(
        academy_id=A, parent_id="p-1", log_id="l-1", note="sent", actor=OWNER
    )
    assert row.status == "logged" and row.note == "sent"


async def test_complete_unknown_log_is_not_found() -> None:
    use_case = CompleteFamilyContactLog(FakeLogs(), Directory(), clock=_clock)
    with pytest.raises(ContactLogNotFound):
        await use_case.execute(academy_id=A, parent_id="p-1", log_id="nope", note=None, actor=ADMIN)
