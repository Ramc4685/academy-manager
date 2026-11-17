"""The push event catalogue (L11 item 5).

``ALWAYS_ON`` are the four events that pushed before the catalogue existed;
they still push whenever ``PUSH_DELIVERY_ENABLED`` (the global switch) is on.
``OPT_IN`` events push only when named in ``V2_PUSH_EXTRA_EVENTS``, so the
default deploy pushes exactly what it did before.
"""

from __future__ import annotations

from enum import StrEnum


class PushEvent(StrEnum):
    CLASS_CANCELLED = "class_cancelled"
    WAITLIST_OFFER = "waitlist_offer"
    URGENT_ANNOUNCEMENT = "urgent_announcement"
    DUES_REMINDER = "dues_reminder"
    DIRECT_MESSAGE = "direct_message"
    ACADEMY_BROADCAST = "academy_broadcast"
    CLASS_ANNOUNCEMENT = "class_announcement"


ALWAYS_ON: frozenset[PushEvent] = frozenset(
    {
        PushEvent.CLASS_CANCELLED,
        PushEvent.WAITLIST_OFFER,
        PushEvent.URGENT_ANNOUNCEMENT,
        PushEvent.DUES_REMINDER,
    }
)
OPT_IN: frozenset[PushEvent] = frozenset(set(PushEvent) - ALWAYS_ON)


def enabled_push_events(extra: str | None) -> frozenset[PushEvent]:
    """``ALWAYS_ON`` plus the known opt-in names in a comma-separated list;
    unknown names are ignored rather than failing boot."""
    names = {part.strip().lower() for part in (extra or "").split(",")}
    return ALWAYS_ON | {event for event in OPT_IN if event.value in names}
