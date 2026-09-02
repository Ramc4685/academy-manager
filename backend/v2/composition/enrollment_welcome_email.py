"""Parent welcome email for a new enrollment (issue #613, Phase 2).

One template, every section conditional on a populated field. It lives in
``composition/`` rather than inside the enrollment context because it imports
enrollment, communications and identity at once — which a context may never do
(``tests/structural/test_layering.py::test_no_cross_context_imports``). It is
the sibling of ``email_adapters.py`` and reuses that module's brand shell and
button so all outbound mail reads as one product.

Two rules this module exists to keep true:

* **Session timezone, never UTC and never the reader's clock.** A recurring
  session already stores local wall-clock ``start_time``/``end_time``, so the
  common case needs no conversion at all; a one-off dated session is converted
  into the session's own zone. This repo has a live class of bugs here
  (#541/#604) and the parent "Review & pay" screen still renders in the
  browser's zone — the welcome email must not repeat that.
* **The etiquette line is verbatim whenever a link is present.** A WhatsApp
  invite link is convenience, not access control; that sentence is the only
  thing in the message that limits a forwarded link's blast radius.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.v2.composition.email_adapters import (
    _BRAND_HEADING,
    _BRAND_MUTED,
    _branded_button,
    _branded_shell,
)
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "America/Chicago"

#: Required verbatim by #613 whenever a group link is present. `{session}` is
#: the only substitution, and it is HTML-escaped before it lands here.
_ETIQUETTE_TEMPLATE = (
    "This group is only for families enrolled in {session}. "
    "If you are no longer part of this session, please exit the group."
)

_DAY_LABELS = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class UserLookup(Protocol):
    async def get_by_id(self, user_id: str) -> Any: ...


class AcademyLookup(Protocol):
    """The academy document, not just its name.

    The timezone lives on the same doc, and reading only the name is how the
    academy tier of ``format_session_when``'s fallback chain became dead code
    — a session with no ``timezone`` then rendered in the hard-coded product
    default instead of the academy's zone. ``RosterAlertAdapter`` reads the
    doc for exactly this reason; the two adapters share a renderer and must
    not disagree about what time a class starts.
    """

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


def _para(text: str) -> str:
    return f"<p style='margin: 0 0 12px;'>{text}</p>"


def _multiline(text: str) -> str:
    """Escape first, *then* turn newlines into breaks.

    The other order would let a pasted ``<br>`` survive as markup.
    """
    return html.escape(text.strip()).replace("\n", "<br />")


def _block(heading: str, body_html: str) -> str:
    return (
        f"<h3 style='color: {_BRAND_HEADING}; font-size: 15px; margin: 24px 0 8px;'>"
        f"{html.escape(heading)}</h3>{body_html}"
    )


def _format_time_12h(value: str) -> str:
    """`18:30` -> `6:30 PM`; anything unparseable is passed through as typed."""
    try:
        hour_str, _, minute_str = value.strip().partition(":")
        hour = int(hour_str)
        minute = int(minute_str or 0)
    except ValueError:
        return value.strip()
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return value.strip()
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def format_session_when(session: Session, *, academy_timezone: str | None = None) -> str:
    """The "When" line, in the SESSION's clock.

    Recurring sessions carry local wall-clock strings, so they are rendered
    as-is — there is nothing to convert and therefore nothing to get wrong.
    A one-off session is converted from its stored UTC instant into the
    session's own zone (falling back to the academy's, then the product
    default) — never the server's, never the reader's.
    """
    days = [_DAY_LABELS.get(day, str(day)) for day in session.days_of_week if str(day).strip()]
    if days and session.start_time:
        day_text = ", ".join(days)
        time_text = _format_time_12h(session.start_time)
        if session.end_time:
            time_text = f"{time_text} to {_format_time_12h(session.end_time)}"
        return f"{day_text}, {time_text}"

    tz_name = session.timezone or academy_timezone or _DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(_DEFAULT_TIMEZONE)
    start: datetime = session.start_at
    local = start.astimezone(tz)
    return local.strftime("%A, %B %-d at %-I:%M %p")


def render_welcome_email(
    *,
    session: Session,
    academy_name: str,
    student_name: str,
    coach_name: str | None = None,
    academy_timezone: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, html_body)``.

    Every block below is emitted only when its field is populated: an academy
    that has configured nothing still gets a correct, short welcome rather
    than a message full of empty headings.
    """
    safe_session_title = html.escape(session.title)
    safe_student = html.escape(student_name)

    parts: list[str] = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
        f"{safe_student} is enrolled in {safe_session_title}</h2>",
        _para(
            f"Here is everything you need for {safe_student}'s first day with "
            f"{html.escape(academy_name)}."
        ),
    ]

    parts.append(
        _block(
            "When",
            _para(html.escape(format_session_when(session, academy_timezone=academy_timezone))),
        )
    )

    where_lines = [html.escape(session.location)] if session.location else []
    if session.venue_address:
        where_lines.append(_multiline(session.venue_address))
    if where_lines:
        parts.append(_block("Where", _para("<br />".join(where_lines))))
    if session.whatsapp_group_link:
        # The href is escaped here; the *scheme* was allowlisted on the way in
        # (shared/security/external_url.py). Those are different controls —
        # escaping stops attribute breakout, it does not stop `javascript:`.
        parts.append(
            _block(
                "Group chat",
                _branded_button(label="Open WhatsApp group", url=session.whatsapp_group_link)
                + f"<p style='color: {_BRAND_MUTED}; font-size: 13px; margin: 0;'>"
                + _ETIQUETTE_TEMPLATE.format(session=safe_session_title)
                + "</p>",
            )
        )

    if session.parking_notes:
        parts.append(_block("Parking", _para(_multiline(session.parking_notes))))
    if session.arrival_minutes_before is not None:
        parts.append(
            _block(
                "Arrival",
                _para(
                    f"Please arrive {session.arrival_minutes_before} minutes before "
                    f"the class starts."
                ),
            )
        )
    if session.what_to_bring:
        parts.append(_block("What to bring", _para(_multiline(session.what_to_bring))))

    coach_lines = []
    if coach_name:
        coach_lines.append(f"Your coach is {html.escape(coach_name)}.")
    if session.coach_contact_policy:
        coach_lines.append(_multiline(session.coach_contact_policy))
    if coach_lines:
        parts.append(_block("Your coach", _para("<br />".join(coach_lines))))

    if session.absence_policy:
        parts.append(_block("Absences and make-ups", _para(_multiline(session.absence_policy))))

    body = _branded_shell(academy_name=academy_name, inner_html="".join(parts))
    return f"Welcome to {session.title}", body


class EnrollmentWelcomeEmailAdapter:
    """Implements enrollment's ``EnrollmentWelcomeNotifier`` port.

    Tenancy: the academy is read at *execution* time via
    ``current_academy_id()``. Capturing it at composition time is a known
    prod-bug class in this repo.

    The recipient is resolved through the tenant-scoped ``AudienceResolver``,
    never through a global user lookup: ``EditRosterAdd`` takes the
    ``parent_id`` straight off an admin request, and this message carries the
    venue address, the coach's name and the private group-chat invite. A
    mistyped or pasted id from another academy must resolve to nobody, not to
    that academy's parent.
    """

    def __init__(
        self,
        *,
        sessions: SessionLookup,
        users: UserLookup,
        academies: AcademyLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
    ) -> None:
        self._sessions = sessions
        self._users = users
        self._academies = academies
        self._audiences = audiences
        self._sender = sender

    async def send_welcome(
        self,
        *,
        session_id: str,
        student_name: str,
        parent_user_id: str,
        parent_email: str | None = None,
    ) -> None:
        session = await self._sessions.get(session_id)
        if session is None:
            logger.warning(
                "enrollment.welcome_email_session_missing",
                extra={"session_id": session_id},
            )
            return

        # Tenant-scoped resolution: `resolve_selected_audience` filters on
        # `academy_id: current_academy_id()`, so a parent id belonging to
        # another academy resolves to nothing and nothing is sent. The
        # registration-approval caller passes `parent_email` off its own
        # tenant-scoped application and is trusted for the address; the
        # display name is still best-effort from the in-tenant row.
        parent = await self._resolve_parent(parent_user_id)
        email = (parent_email or (parent.email if parent else "") or "").strip()
        if not email:
            logger.warning(
                "enrollment.welcome_email_no_recipient",
                extra={"session_id": session_id, "parent_user_id": parent_user_id},
            )
            return
        display_name = (parent.display_name if parent else None) or None

        academy_id = current_academy_id()
        academy_doc = await self._academies.find_by_id(academy_id) or {}
        academy_name = str(academy_doc.get("display_name") or academy_doc.get("name") or "") or (
            "Your academy"
        )
        academy_timezone = str(academy_doc.get("timezone") or "") or None
        coach_name = await self._coach_name(session.coach_id)

        subject, body = render_welcome_email(
            session=session,
            academy_name=academy_name,
            student_name=student_name,
            coach_name=coach_name,
            academy_timezone=academy_timezone,
        )
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_user_id,
                email=email,
                display_name=display_name,
            ),
            subject=subject,
            body=body,
            # TRANSACTIONAL: this is the onboarding record of an enrollment the
            # family just paid for or was placed into. It still passes the
            # #556 bounce/complaint suppression gate (a dead mailbox stops
            # everything) but is deliberately outside the #555 unsubscribable
            # categories, and therefore carries no CAN-SPAM footer.
            category=EmailCategory.TRANSACTIONAL,
        )
        if not outcome.ok and not outcome.suppressed:
            logger.warning(
                "enrollment.welcome_email_failed",
                extra={
                    "session_id": session_id,
                    "parent_user_id": parent_user_id,
                    "reason": outcome.failed_reason,
                },
            )

    async def _resolve_parent(self, parent_user_id: str) -> ResolvedRecipient | None:
        """The parent, only if they belong to the academy running this request."""
        if not parent_user_id:
            return None
        try:
            resolved = await self._audiences.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=(parent_user_id,))
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "enrollment.welcome_email_audience_failed",
                extra={"parent_user_id": parent_user_id},
            )
            return None
        return resolved[0] if resolved else None

    async def _coach_name(self, coach_id: str) -> str | None:
        if not coach_id:
            return None
        try:
            coach = await self._users.get_by_id(coach_id)
        except Exception:  # pragma: no cover - defensive
            return None
        if coach is None:
            return None
        name = str(getattr(coach, "display_name", "") or "").strip()
        return name or None
