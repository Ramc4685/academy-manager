"""Lead nurture sequence (AI strategy Phase 3, C1): rules only, no I/O.

One sequence per academy. Day 0 is the inquiry acknowledgement the public
form already sends (``composition/public_trial_requests.py``); this module
owns the owner-written steps on days 2, 7 and 21 and the rules that decide
whether a lead gets one today:

* **Audience.** ``consent.marketing`` true and pipeline status ``lead`` or
  ``trial``, created after the sequence was switched on.
* **Stops** (re-checked on every run; each one is permanent once true): the
  lead is ``enrolled``, staff moved its card (``pipeline_override``), a
  conversation was logged on it (the app has no inbound mailbox, so a reply
  is recorded by staff replying from the pipeline or logging the contact),
  or the address unsubscribed.
* **One step at a time.** On a given day only the latest due step is a
  candidate, and only within ``LATE_GRACE_DAYS`` of its day, so a job that was
  down never sends a backlog and never sends day 2 after day 7.

The per-step state lives on the send claim, keyed ``nurture:day_<n>`` per
contact with a ``channel`` field (``email`` today), so a later SMS channel
(C2) is a new value of that field, not a new key shape.

Templates are plain text with ``{{merge_field}}`` placeholders, rendered to
escaped HTML paragraphs. Only the four merge fields below exist; nothing a
lead typed is ever merged in.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal

from backend.v2.contexts.crm.domain.errors import InvalidNurtureSequence
from backend.v2.contexts.crm.domain.models import CrmContact

#: The owner-written steps. Day 0 (the acknowledgement) is not one of them.
NURTURE_STEP_DAYS: Final = (2, 7, 21)
#: A step is still sent this many days after its day (a missed tick), never later.
LATE_GRACE_DAYS: Final = 3
#: How far back a candidate can have been created and still have a step due.
CANDIDATE_LOOKBACK: Final = timedelta(days=max(NURTURE_STEP_DAYS) + LATE_GRACE_DAYS + 1)
MAX_SUBJECT_LENGTH: Final = 150
MAX_BODY_LENGTH: Final = 4000

MERGE_FIELDS: Final = ("academy_name", "class", "seat_band", "booking_link")
_MERGE_RE: Final = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")

NurtureChannel = Literal["email"]
StopReason = Literal["not_eligible", "moved", "conversation", "unsubscribed"]


@dataclass(frozen=True)
class NurtureStep:
    day: int
    subject: str
    body: str

    @property
    def key(self) -> str:
        """The send-claim key: one send per (inbox, step)."""
        return f"nurture:day_{self.day}"

    @property
    def is_written(self) -> bool:
        return bool(self.subject.strip() and self.body.strip())


@dataclass(frozen=True)
class NurtureSequence:
    enabled: bool = False
    enabled_at: datetime | None = None
    steps: tuple[NurtureStep, ...] = ()

    def written_steps(self) -> tuple[NurtureStep, ...]:
        return tuple(sorted((s for s in self.steps if s.is_written), key=lambda s: s.day))


def validate_steps(steps: list[NurtureStep]) -> tuple[NurtureStep, ...]:
    """Normalise and check owner input. A blank step (no subject and no body)
    is kept as blank: it is simply never sent."""
    seen: set[int] = set()
    out: list[NurtureStep] = []
    for step in steps:
        if step.day not in NURTURE_STEP_DAYS:
            raise InvalidNurtureSequence("Steps are on days 2, 7 and 21.", field="day")
        if step.day in seen:
            raise InvalidNurtureSequence("Each day has one step.", field="day")
        seen.add(step.day)
        subject = " ".join(step.subject.split())
        body = step.body.strip()
        if bool(subject) != bool(body):
            raise InvalidNurtureSequence(
                f"Day {step.day} needs both a subject and a message, or neither.",
                field="subject" if not subject else "body",
            )
        if len(subject) > MAX_SUBJECT_LENGTH or len(body) > MAX_BODY_LENGTH:
            raise InvalidNurtureSequence(f"Day {step.day} is too long.", field="body")
        for text, field in ((subject, "subject"), (body, "body")):
            unknown = sorted({m for m in _MERGE_RE.findall(text) if m not in MERGE_FIELDS})
            if unknown:
                raise InvalidNurtureSequence(
                    f"Unknown merge field {{{{{unknown[0]}}}}} on day {step.day}.", field=field
                )
        out.append(NurtureStep(day=step.day, subject=subject, body=body))
    return tuple(sorted(out, key=lambda s: s.day))


def stop_reason(contact: CrmContact) -> StopReason | None:
    """The stop that needs no other read (the conversation and unsubscribe
    checks are ports, asked by the use case after this)."""
    if contact.pipeline_status not in ("lead", "trial") or not contact.consent.marketing:
        return "not_eligible"
    if contact.pipeline_override is not None:
        return "moved"
    return None


def due_step(
    steps: tuple[NurtureStep, ...], *, created_on: date, today: date
) -> NurtureStep | None:
    """The latest written step whose day has come, if still inside its grace."""
    age = (today - created_on).days
    due = [s for s in steps if s.day <= age]
    if not due:
        return None
    step = due[-1]
    return step if age - step.day <= LATE_GRACE_DAYS else None


def created_on(contact: CrmContact, local_now: datetime) -> date:
    return contact.created_at.astimezone(local_now.tzinfo).date()


def render_subject(template: str, values: dict[str, str]) -> str:
    text = _MERGE_RE.sub(lambda m: values.get(m.group(1), ""), template)
    return " ".join(text.split())


def render_text(template: str, values: dict[str, str]) -> str:
    """The body with merge fields filled, as plain text (the admin preview)."""
    return _MERGE_RE.sub(lambda m: values.get(m.group(1), ""), template).strip()


def render_html(template: str, values: dict[str, str]) -> str:
    """The body as escaped HTML paragraphs; the booking link is clickable."""

    def piece(text: str) -> str:
        parts: list[str] = []
        last = 0
        for match in _MERGE_RE.finditer(text):
            parts.append(html.escape(text[last : match.start()]))
            name, value = match.group(1), values.get(match.group(1), "")
            if name == "booking_link" and value:
                safe = html.escape(value)
                parts.append(f'<a href="{safe}">{safe}</a>')
            else:
                parts.append(html.escape(value))
            last = match.end()
        parts.append(html.escape(text[last:]))
        return "".join(parts).replace("\n", "<br>")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", template.strip()) if p.strip()]
    return "".join(f'<p style="margin:0 0 12px;">{piece(p)}</p>' for p in paragraphs)


def seat_band_text(band: str | None, seats_left: int | None = None) -> str:
    """The ``{{seat_band}}`` sentence. ``band`` is the public page's seat band
    (``open`` / ``few`` / ``waitlist``) of the class the lead asked about;
    ``None`` when they picked none or it is no longer listed."""
    if band == "open":
        return "There are seats available."
    if band == "few":
        return f"Only {seats_left} seats are left." if seats_left else "Only a few seats are left."
    if band == "waitlist":
        return "The class is full right now; reply and we will keep your place on the waitlist."
    return "Reply and we will find you a class with a seat."
