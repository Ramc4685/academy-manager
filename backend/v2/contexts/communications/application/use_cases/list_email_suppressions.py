"""Admin read/release over the suppression list (issue #556).

The list is global by design (see ``MongoSuppressionRepository``), so this is
deliberately a small, read-mostly surface: an admin can see which addresses the
provider has told us are dead and release one they believe was a mistake. A
release is not permanent — the next bounce for that address re-suppresses it.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import SuppressionRepository
from backend.v2.contexts.communications.domain.email_suppression import EmailSuppression


@dataclass
class ListEmailSuppressions:
    suppressions: SuppressionRepository

    async def execute(self, *, limit: int = 100) -> list[EmailSuppression]:
        return await self.suppressions.list_active(limit=max(1, min(limit, 500)))


@dataclass
class ReleaseEmailSuppression:
    suppressions: SuppressionRepository

    async def execute(self, *, email: str, released_by: str) -> bool:
        return await self.suppressions.release(email=email, released_by=released_by)
