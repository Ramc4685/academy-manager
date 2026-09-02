"""Render every outbound email template with sample data to HTML files.

Usage (from repo root):
    backend/.venv/bin/python -m backend.v2.tests.fixtures.email_previews.render_previews OUT_DIR
Then screenshot with:
    cd frontend && node scripts/email-previews.mjs OUT_DIR

Not collected by pytest (module name does not start with ``test_``). Kept
next to the tests so it can borrow their fixtures and stays in step with the
renderer signatures.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime

from backend.v2.composition.email_adapters import _branded_button, _branded_shell
from backend.v2.composition.enrollment_welcome_email import render_welcome_email
from backend.v2.contexts.billing.application.use_cases.send_add_card_reminder import (
    _reminder_body,
)
from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    DuesView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.identity.application.use_cases.send_login_invite import _invite_body
from backend.v2.shared.comms.email_theme import INK, EmailBrand, format_money
from backend.v2.tests.application.test_send_coach_daily_digest import _populated_plan

BRAND = EmailBrand(
    academy_name="BLNO Badminton",
    contact_email="hello@blno.test",
    contact_phone="(312) 555-0100",
)
UNSUB = "https://portal.test/unsubscribe?t=abc"
G1 = WhatsAppGroupLink(
    label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",)
)
G2 = WhatsAppGroupLink(
    label="Intermediate @ YWCA", url="https://chat.whatsapp.com/BBB", child_names=("Arjun",)
)


def _child(name: str, **overrides: object) -> ChildDigestView:
    base: dict[str, object] = {
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
        "cant_make_it_url": "https://portal.test/parent/requests",
    }
    base.update(overrides)
    return ChildDigestView(**base)  # type: ignore[arg-type]


def render_all(out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def write(name: str, subject: str, body: str) -> None:
        (out / f"{name}.html").write_text(f"<!--{subject}-->\n{body}")

    variant_a = ParentDigestView(
        parent_name="Priya",
        date_label="Thursday, September 3",
        program_name="Badminton Skill Pathway",
        children=(
            _child("Maithri"),
            _child(
                "Arjun",
                session_time="7:00 - 7:45 PM",
                session_label="Intermediate @ YWCA",
                focus_skill="Backhand lift",
                focus_status="learning",
                level_name="Level 2",
                skills_completed=2,
                skills_total=12,
                skills_left=10,
                levels_to_go=2,
            ),
        ),
        on_portal=True,
        dues=DuesView(amount="$60.00", due_date="September 10", pay_url="https://portal.test/pay"),
        autopay_enabled=False,
        portal_url="https://portal.test/parent/dashboard",
        whatsapp_groups=(G1, G2),
    )
    write("parent_digest_A", *render_parent_digest(variant_a, brand=BRAND, unsubscribe_url=UNSUB))

    variant_b = ParentDigestView(
        parent_name="Priya",
        date_label="Thursday, September 3",
        program_name="Badminton Skill Pathway",
        children=(_child("Maithri", cant_make_it_url=None),),
        on_portal=False,
        dues=DuesView(
            amount="$60.00",
            due_date="August 10",
            pay_url="https://portal.test/pay",
            is_overdue=True,
        ),
        activate_url="https://portal.test/activate",
        reply_to="coach@blno.test",
        whatsapp_groups=(G1,),
    )
    write("parent_digest_B", *render_parent_digest(variant_b, brand=BRAND, unsubscribe_url=UNSUB))

    write(
        "coach_digest",
        *render_coach_digest(
            _populated_plan(),
            brand=BRAND,
            whatsapp_groups=[G1, G2],
            playlist_url="https://youtube.com/playlist",
            unsubscribe_url=UNSUB,
        ),
    )

    total = format_money(12000, "usd")
    inner = (
        f"<h2 style='color: {INK}; font-size: 20px; margin: 0 0 12px;'>"
        "Your September 2026 invoice</h2>"
        "<p>Invoice <strong>INV-2026-09-0042</strong> is ready.</p>"
        f"<p>Balance due: <strong>{total}</strong> (invoice total {total}).</p>"
        + _branded_button(label="Pay invoice", url="https://portal.test/pay")
    )
    write(
        "invoice",
        "Invoice INV-2026-09-0042 for September 2026",
        _branded_shell(academy_name="BLNO Badminton", inner_html=inner),
    )

    write(
        "login_invite",
        "Set your password for BLNO Badminton",
        _invite_body(
            display_name="Priya",
            academy_name="BLNO Badminton",
            reset_link="https://portal.test/set",
        ),
    )
    write(
        "add_card",
        "Add a payment method for BLNO Badminton",
        _reminder_body(
            display_name="Priya",
            academy_name="BLNO Badminton",
            setup_link="https://portal.test/card",
        ),
    )

    session = Session(
        session_id="s1",
        academy_id="a",
        coach_id="c",
        title="Beginner Badminton",
        location="YWCA Court 1",
        start_at=datetime(2026, 9, 8, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 8, 23, 45, tzinfo=UTC),
        capacity=12,
        timezone="America/Chicago",
        days_of_week=["Tue", "Thu"],
        start_time="18:00",
        end_time="18:45",
        whatsapp_group_link="https://chat.whatsapp.com/AAA",
        venue_address="123 Main St, Chicago IL",
        parking_notes="Lot behind the building",
        what_to_bring="Racket, water bottle, indoor shoes",
        arrival_minutes_before=10,
        coach_contact_policy="Message the coach via the WhatsApp group.",
        absence_policy="Tell us by noon on the day.",
    )
    write(
        "welcome",
        *render_welcome_email(
            session=session,
            academy_name="BLNO Badminton",
            student_name="Maithri",
            coach_name="Coach Ravi",
        ),
    )
    print("rendered", sorted(p.name for p in out.glob("*.html")))


if __name__ == "__main__":
    render_all(pathlib.Path(sys.argv[1]))
