"""MarkLeadEnrolled: close the lead loop on registration approval.

Until now nothing wrote ``crm_contacts.pipeline_status = "enrolled"``, so the
"Inquiry conversion by source" report (``people_reports.py``) read 0% for
every source. ``AdminRegistrationReview.approve`` now calls this after the
approval is durable, the same way it calls enrollment's
``LinkTrialConversion``:

* match by the approved application's parent email, lower-cased, against
  this academy's contacts (the tenant-scoped repository; another academy's
  contact with the same email is never touched);
* every matching contact not already ``enrolled`` becomes ``enrolled`` with
  ``converted_parent_id`` and ``linked_family_id`` set to the parent's user id
  (the family index is keyed by that id, see ``domain/family_index.py``);
* no email or no match is a silent no-op: not every registration follows an
  inquiry, and an enrolled card is left as the conversion flow wrote it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from backend.v2.contexts.crm.domain.models import normalize_email


class EnrollableContactRepository(Protocol):
    async def mark_enrolled_by_email(
        self, email: str, *, parent_user_id: str, updated_at: datetime
    ) -> int:
        """Set ``enrolled`` plus the conversion ids on every contact of the
        current academy with this (normalised) email that is not yet
        ``enrolled``. Returns how many rows changed."""
        ...


class MarkLeadEnrolled:
    def __init__(
        self,
        contacts: EnrollableContactRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._contacts = contacts
        self._now = clock

    async def execute(
        self, *, parent_user_id: str, parent_email: str | None, application_id: str
    ) -> int:
        email = normalize_email(parent_email)
        if email is None:
            return 0
        return await self._contacts.mark_enrolled_by_email(
            email, parent_user_id=parent_user_id, updated_at=self._now()
        )
