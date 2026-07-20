"""Renderer behaviour for the parent daily digest — both variants."""

from __future__ import annotations

from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    DuesView,
    ParentDigestView,
)


def _child(name: str = "Maithri", **overrides: object) -> ChildDigestView:
    base = {
        "child_name": name,
        "session_time": "6:00 - 6:45 PM",
        "session_label": "Beginner @ YWCA",
        "focus_skill": "Thumb grip",
        "focus_status": "practicing",
        "level_name": "Level 1",
        "skills_completed": 7,
        "skills_total": 10,
        "skills_left": 3,
        "levels_to_go": 3,
        "cant_make_it_url": "https://portal.test/parent/attendance?session=s1",
    }
    base.update(overrides)
    return ChildDigestView(**base)  # type: ignore[arg-type]


def test_variant_a_has_focus_progress_cant_make_it_and_portal_footer() -> None:
    view = ParentDigestView(
        parent_name="Parent One",
        date_label="Thursday, July 16",
        program_name="Badminton Skill Pathway",
        children=(_child(),),
        on_portal=True,
        dues=DuesView(amount="$60.00", due_date="July 10", pay_url="https://portal.test/pay"),
        autopay_enabled=False,
        portal_url="https://portal.test/parent/dashboard",
    )

    subject, body = render_parent_digest(view)

    assert subject == "Practice today for Maithri — Badminton Skill Pathway"
    assert "Good morning! Maithri has practice today" in body
    assert "Thumb grip" in body
    assert "practicing" in body
    # Progress + counts (Variant A only).
    assert "7 of 10 skills" in body
    assert "3 skills left in Level 1" in body
    assert "3 more levels to go" in body
    # Can't-make-it deep link.
    assert "https://portal.test/parent/attendance?session=s1" in body
    assert "Can't make it" in body
    # Dues + autopay rows.
    assert "$60.00" in body
    assert "Pay now" in body
    assert "Set up autopay" in body
    # Portal footer, not the Variant B activation CTA.
    assert "parent portal" in body
    assert "Set up account &amp; pay" not in body


def test_variant_a_hides_dues_and_autopay_when_not_applicable() -> None:
    view = ParentDigestView(
        parent_name="Parent One",
        date_label="Thursday, July 16",
        program_name="Badminton",
        children=(_child(),),
        on_portal=True,
        dues=None,
        autopay_enabled=True,
        portal_url="https://portal.test/parent/dashboard",
    )

    _subject, body = render_parent_digest(view)

    assert "Pay now" not in body
    assert "Set up autopay" not in body


def test_variant_b_is_dues_forward_with_single_activation_cta() -> None:
    child = _child(cant_make_it_url=None)
    view = ParentDigestView(
        parent_name="Parent Two",
        date_label="Thursday, July 16",
        program_name="Badminton",
        children=(child,),
        on_portal=False,
        dues=DuesView(amount="$60.00", due_date="July 10", pay_url="https://portal.test/pay"),
        activate_url="https://portal.test/set-password?continue=/parent/payments",
        reply_to="academy@example.test",
    )

    _subject, body = render_parent_digest(view)

    # Dues-forward hero + single CTA.
    assert "Your balance of $60.00 was due July 10" in body
    assert "Set up account &amp; pay" in body
    assert "https://portal.test/set-password?continue=/parent/payments" in body
    # No progress bar, no portal deep links, no can't-make-it button in Variant B.
    assert "of 10 skills" not in body
    assert ">Can't make it</a>" not in body  # the button, not the reply-to footer phrase
    assert "parent portal" not in body
    # Absence degrades to reply-to.
    assert "Reply to this email" in body


def test_variant_b_without_dues_is_a_soft_signup_nudge() -> None:
    child = _child(cant_make_it_url=None)
    view = ParentDigestView(
        parent_name="Parent Three",
        date_label="Thursday, July 16",
        program_name="Badminton",
        children=(child,),
        on_portal=False,
        dues=None,
        activate_url="https://portal.test/set-password",
    )

    _subject, body = render_parent_digest(view)

    assert "Create my account" in body
    assert "Set up account &amp; pay" not in body
    assert "Your balance" not in body


def test_subject_lists_multiple_children() -> None:
    view = ParentDigestView(
        parent_name="Parent One",
        date_label="Thursday, July 16",
        program_name="",
        children=(_child("Maithri"), _child("Riaan")),
        on_portal=True,
    )

    subject, body = render_parent_digest(view)

    assert subject == "Practice today for Maithri & Riaan"
    assert "your kids have practice today" in body


def test_html_is_escaped() -> None:
    view = ParentDigestView(
        parent_name="Parent One",
        date_label="Thursday, July 16",
        program_name="",
        children=(_child(child_name="<script>alert(1)</script>"),),
        on_portal=True,
    )

    _subject, body = render_parent_digest(view)

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
