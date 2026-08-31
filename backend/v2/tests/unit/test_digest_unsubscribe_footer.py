"""Every non-transactional body carries an opt-out notice (#555).

The CAN-SPAM requirement is not "there is a preference store"; it is that the
message itself tells the recipient how to stop. These pin the footer onto both
digest renderers and onto the campaign send path, and pin the fail-closed
fallback: with no signing secret the footer must render a portal pointer, never
a dead or unsigned link.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    append_unsubscribe_footer,
)

URL = "https://app.test/unsubscribe?t=u1.abc.def"


def _parent_view() -> ParentDigestView:
    return ParentDigestView(
        parent_name="Parent",
        date_label="Saturday, June 13",
        program_name="Badminton",
        children=(
            ChildDigestView(
                child_name="Kid", session_time="6:00 - 6:45 PM", session_label="Beginner"
            ),
        ),
        on_portal=True,
    )


def _plan() -> object:
    student = SimpleNamespace(student_name="Alice", focus="Clear", next_skill=None)
    group = SimpleNamespace(level_name="Level 1", students=[student], youtube_links=[])
    session = SimpleNamespace(
        title="Juniors", location="Court A", start_at=None, end_at=None, groups=[group], unplaced=[]
    )
    return SimpleNamespace(date="2026-06-13", program_name="Badminton", sessions=[session])


def test_parent_digest_body_carries_the_unsubscribe_link() -> None:
    _subject, body = render_parent_digest(_parent_view(), unsubscribe_url=URL)
    assert URL in body
    assert "Unsubscribe" in body


def test_coach_digest_body_carries_the_unsubscribe_link() -> None:
    _subject, body = render_coach_digest(_plan(), unsubscribe_url=URL)
    assert URL in body
    assert "Unsubscribe" in body


def test_campaign_body_carries_the_unsubscribe_link() -> None:
    assert URL in append_unsubscribe_footer("<p>Summer camp</p>", URL)


def test_without_a_secret_the_footer_points_at_the_portal_and_carries_no_token() -> None:
    """Fail closed: a dead unsubscribe link is worse than none."""
    _subject, parent_body = render_parent_digest(_parent_view(), unsubscribe_url=None)
    _subject2, coach_body = render_coach_digest(_plan(), unsubscribe_url=None)
    campaign_body = append_unsubscribe_footer("<p>Summer camp</p>", None)

    for body in (parent_body, coach_body, campaign_body):
        assert "email preferences" in body
        assert "/unsubscribe?t=" not in body
        assert "<a " not in body.rsplit("border-top", 1)[-1]
