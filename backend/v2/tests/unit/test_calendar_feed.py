"""Parent class-calendar subscription: signed link + .ics body + feed window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from backend.v2.composition.calendar_feed import feed_window
from backend.v2.contexts.enrollment.application.calendar_feed import (
    FeedEvent,
    feed_signature_matches,
    mint_feed_token,
    parse_feed_token,
    render_feed,
)

SECRET = "s3cret"


def _verify(token: str, *, academy_id: str = "acad-1", version: int = 0) -> bool:
    parsed = parse_feed_token(token)
    if parsed is None:
        return False
    parent_id, sig = parsed
    return feed_signature_matches(
        secret=SECRET, academy_id=academy_id, parent_id=parent_id, version=version, signature=sig
    )


def test_token_round_trips_and_is_bound_to_academy_and_version() -> None:
    token = mint_feed_token(secret=SECRET, academy_id="acad-1", parent_id="P1", version=0)
    assert token.startswith("P1.")
    assert _verify(token)
    assert not _verify(token, academy_id="acad-2")  # another academy's host
    assert not _verify(token, version=1)  # after "Reset link"


def test_token_for_other_parent_does_not_verify() -> None:
    token = mint_feed_token(secret=SECRET, academy_id="acad-1", parent_id="P1", version=0)
    forged = "P2." + token.split(".", 1)[1]
    assert not _verify(forged)


def test_malformed_tokens_are_rejected() -> None:
    for bad in ("", "P1", "P1.short", "../x.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "P 1." + "a" * 32):
        assert parse_feed_token(bad) is None


def test_render_marks_cancelled_class_and_escapes_text() -> None:
    start = datetime(2026, 12, 24, 23, 0, tzinfo=UTC)
    body = render_feed(
        calendar_name="BLNO classes",
        events=[
            FeedEvent(
                uid="occ-1-stu-1@academy-manager",
                title="No class — Maithri — Beginner",
                start_at=start,
                end_at=start + timedelta(hours=1),
                cancelled=True,
                location="YWCA, Gym 2",
                description="Gym not available; sorry",
            ),
            FeedEvent(
                uid="occ-2-stu-1@academy-manager",
                title="Maithri — Beginner",
                # naive datetimes are stored UTC
                start_at=datetime(2026, 12, 22, 23, 0),
                end_at=datetime(2026, 12, 23, 0, 0),
                cancelled=False,
            ),
        ],
        now=datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "STATUS:CANCELLED\r\nSEQUENCE:1" in body
    assert "STATUS:CONFIRMED\r\nSEQUENCE:0" in body
    assert "LOCATION:YWCA\\, Gym 2" in body
    assert "DESCRIPTION:Gym not available\\; sorry" in body
    assert "DTSTART:20261224T230000Z" in body
    assert "DTSTART:20261222T230000Z" in body
    assert "X-WR-CALNAME:BLNO classes" in body


def test_long_lines_fold_at_75_octets_without_splitting_characters() -> None:
    title = "Class — " * 30
    body = render_feed(
        calendar_name="x",
        events=[
            FeedEvent(
                uid="u",
                title=title,
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                end_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
                cancelled=False,
            )
        ],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    for line in body.split("\r\n"):
        assert len(line.encode()) <= 75
    unfolded = body.replace("\r\n ", "")
    assert f"SUMMARY:{title}" in unfolded


def test_feed_window_unpublished_reaches_ahead_published_stops_at_month_end() -> None:
    today = date(2026, 11, 17)
    start, end = feed_window(today=today, published_through=None)  # type: ignore[misc]
    assert start == date(2026, 10, 17) and end > date(2027, 5, 1)
    assert feed_window(today=today, published_through="2026-12") == (
        date(2026, 10, 17),
        date(2026, 12, 31),
    )
    # Published only long ago: nothing current to show.
    assert feed_window(today=today, published_through="2026-08") is None
