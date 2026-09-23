"""Resolve the public trial form's optional class choice (public tenant page, Lane B4).

The public page never carries a ``session_id``: every class is addressed by
the opaque :func:`public_class_id` digest. The trial form sends that digest
back; this use case recomputes it over the academy's **published, listable**
classes (the same :meth:`available_for_public_catalog` read the page is built
from) and matches. A private, cancelled or finished class, or another
academy's class, can therefore never be addressed through the form: its
digest is simply not in the set.

It also reports whether the academy lists any class and whether any of them
has a free seat, so the endpoint can file the inquiry as a ``trial`` or as a
``lead`` (the "tell me when classes open" and waitlist variants, brief
section 7) without a second read.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    MAX_PUBLIC_CLASSES,
    PublicCatalogSessionQuery,
)
from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id, seats_left


@dataclass(frozen=True)
class PublicClassChoice:
    """The chosen class, internal: never serialised to the anonymous caller."""

    session_id: str
    title: str
    full: bool


@dataclass(frozen=True)
class PublicClassChoiceResult:
    has_classes: bool
    any_open: bool
    #: The matched class, or None when no id was sent or it matched nothing.
    chosen: PublicClassChoice | None
    #: An id was sent and matched no published class of this academy.
    unknown_id: bool


class ResolvePublicClassChoice:
    def __init__(self, sessions: PublicCatalogSessionQuery) -> None:
        self._sessions = sessions

    async def execute(self, academy_id: str, public_id: str | None) -> PublicClassChoiceResult:
        rows = [
            row
            for row in await self._sessions.available_for_public_catalog()
            if row.profile.published is True
        ][:MAX_PUBLIC_CLASSES]
        wanted = (public_id or "").strip()
        chosen: PublicClassChoice | None = None
        any_open = False
        for row in rows:
            full = seats_left(row.capacity, row.occupied_seats) <= 0
            any_open = any_open or not full
            if wanted and chosen is None:
                if public_class_id(academy_id, row.profile.session_id) == wanted:
                    chosen = PublicClassChoice(
                        session_id=row.profile.session_id, title=row.title, full=full
                    )
        return PublicClassChoiceResult(
            has_classes=bool(rows),
            any_open=any_open,
            chosen=chosen,
            unknown_id=bool(wanted) and chosen is None,
        )
