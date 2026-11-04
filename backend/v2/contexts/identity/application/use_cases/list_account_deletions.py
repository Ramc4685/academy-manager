"""Admin view of self-service account deletions in one academy (mobile M5, D4).

Lets the academy see who deleted their account, when the data is erased, and
whether the erasure is stuck. Ids only beyond the display name: the request's
email is never shown (it is dropped once the deletion completes anyway).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AccountDeletionSummary:
    request_id: str
    user_id: str
    aliases: tuple[str, ...]
    display_name: str
    status: str
    requested_at: datetime
    execute_after: datetime
    completed_at: datetime | None
    attempts: int
    failing_step: str | None


class AccountDeletionReader(Protocol):
    async def list_for_academy(self, academy_id: str) -> list[AccountDeletionSummary]: ...


class ListAccountDeletions:
    def __init__(self, *, store: AccountDeletionReader) -> None:
        self._store = store

    async def execute(self, *, academy_id: str) -> list[AccountDeletionSummary]:
        return await self._store.list_for_academy(academy_id)
