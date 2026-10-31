"""Pure rules for family notes and follow-ups (People CRM Phase 4a)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.crm.domain.errors import InvalidFamilyNote, InvalidFollowUp
from backend.v2.contexts.crm.domain.family_notes import (
    MAX_FOLLOW_UP_TITLE_LEN,
    MAX_NOTE_BODY_LEN,
    FamilyFollowUp,
    FamilyNote,
    can_edit_note,
    follow_up_bucket,
    normalize_follow_up_title,
    normalize_note_body,
    parse_follow_up_status,
)

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _note(author: str = "u-author") -> FamilyNote:
    return FamilyNote(
        note_id="n-1",
        academy_id="acad",
        parent_id="p-1",
        body="Called about the Saturday class.",
        author_user_id=author,
        created_at=NOW,
        updated_at=NOW,
    )


def _follow_up(due_on: date, status: str = "open") -> FamilyFollowUp:
    return FamilyFollowUp(
        follow_up_id="f-1",
        academy_id="acad",
        parent_id="p-1",
        title="Call back",
        due_on=due_on,
        assignee_user_id="u-1",
        status=status,  # type: ignore[arg-type]
        created_by="u-1",
        created_at=NOW,
        updated_at=NOW,
    )


def test_note_body_keeps_line_breaks_and_trims_noise() -> None:
    raw = "  First line   with  spaces \r\n\r\n\r\n\r\nSecond\x07 line\t\t \n"
    assert normalize_note_body(raw) == "First line with spaces\n\nSecond line"


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", None])
def test_empty_note_body_is_rejected(raw: str | None) -> None:
    with pytest.raises(InvalidFamilyNote) as exc:
        normalize_note_body(raw)
    assert exc.value.details["field"] == "body"


def test_note_body_cap_is_4000_characters() -> None:
    assert len(normalize_note_body("a" * MAX_NOTE_BODY_LEN)) == MAX_NOTE_BODY_LEN
    with pytest.raises(InvalidFamilyNote):
        normalize_note_body("a" * (MAX_NOTE_BODY_LEN + 1))


def test_follow_up_title_is_collapsed_and_capped() -> None:
    assert normalize_follow_up_title("  Call   back\nabout  trial ") == "Call back about trial"
    with pytest.raises(InvalidFollowUp):
        normalize_follow_up_title("   ")
    with pytest.raises(InvalidFollowUp):
        normalize_follow_up_title("x" * (MAX_FOLLOW_UP_TITLE_LEN + 1))


def test_status_vocabulary() -> None:
    assert parse_follow_up_status("done") == "done"
    with pytest.raises(InvalidFollowUp):
        parse_follow_up_status("snoozed")


def test_only_the_author_or_an_owner_may_edit_a_note() -> None:
    note = _note()
    assert can_edit_note(note, user_id="u-author", roles=("admin",))
    assert can_edit_note(note, user_id="u-owner", roles=("admin", "owner"))
    assert not can_edit_note(note, user_id="u-other", roles=("admin",))


def test_buckets_split_open_follow_ups_by_the_academy_today() -> None:
    today = date(2026, 9, 23)
    assert follow_up_bucket(_follow_up(date(2026, 9, 22)), today) == "overdue"
    assert follow_up_bucket(_follow_up(today), today) == "today"
    assert follow_up_bucket(_follow_up(date(2026, 9, 24)), today) == "upcoming"
    assert follow_up_bucket(_follow_up(date(2026, 9, 1), "done"), today) == "done"
