"""Carry out self-service account deletions once their grace window ends (M5, D3).

``RequestAccountDeletion`` (D1) locks the account at once; this job, run on a
schedule, erases the person's data ``GRACE_PERIOD`` later. Each other context
does its own part through an injected ``AccountErasureStep`` (identity may not
import enrollment, billing, crm or communications), then identity anonymises
the ``users`` rows and deletes the Firebase account last.

Every step is idempotent: a failure leaves the request ``scheduled`` with the
error recorded, and the next tick runs the whole chain again.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest

log = logging.getLogger(__name__)


class AccountErasureStep(Protocol):
    """One context's share of erasing a deleted account. Must be idempotent."""

    name: str

    async def erase(self, request: AccountDeletionRequest, *, now: datetime) -> None: ...


class DueDeletionStore(Protocol):
    async def due_requests(self, *, now: datetime, limit: int) -> list[AccountDeletionRequest]: ...

    async def anonymise_identity(
        self, request: AccountDeletionRequest, *, now: datetime
    ) -> None: ...

    async def claim(self, request_id: str, *, now: datetime) -> AccountDeletionRequest | None:
        """Atomically mark the request running and return it as it stands now:
        None once every academy restored it (or another run holds it), and
        without any academy that restored it. A restore cannot land after this."""
        ...

    async def mark_completed(self, request_id: str, *, now: datetime) -> None: ...

    async def record_failure(
        self, request_id: str, *, step: str, error: str, now: datetime
    ) -> None: ...


class FirebaseAccountRemover(Protocol):
    async def delete_user(self, uid: str) -> None:
        """Delete the account; an account already gone is success."""
        ...


@dataclass(frozen=True)
class ExecuteAccountDeletionsResult:
    completed: int = 0
    failed: int = 0


class ExecuteAccountDeletions:
    def __init__(
        self,
        *,
        store: DueDeletionStore,
        steps: Sequence[AccountErasureStep],
        firebase: FirebaseAccountRemover,
    ) -> None:
        self._store = store
        self._steps = tuple(steps)
        self._firebase = firebase

    async def execute(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> ExecuteAccountDeletionsResult:
        now = now or datetime.now(UTC)
        completed = failed = 0
        for due in await self._store.due_requests(now=now, limit=limit):
            request = due
            step = "start"
            try:
                # Claim per request: a restore may land after the batch was read,
                # and must not land while this run erases the academies it names.
                current = await self._store.claim(due.request_id, now=now)
                if current is None:
                    continue
                request = current
                for erasure in self._steps:
                    step = erasure.name
                    await erasure.erase(request, now=now)
                step = "identity"
                await self._store.anonymise_identity(request, now=now)
                step = "firebase"
                await self._firebase.delete_user(request.auth_uid or request.user_id)
                await self._store.mark_completed(request.request_id, now=now)
                completed += 1
            except Exception as exc:  # one bad account must not stall the rest
                failed += 1
                log.exception(
                    "account_deletion_failed",
                    extra={"request_id": request.request_id, "step": step},
                )
                try:
                    await self._store.record_failure(
                        request.request_id,
                        step=step,
                        error=f"{type(exc).__name__}: {exc}",
                        now=now,
                    )
                except Exception:  # bookkeeping must not abort the batch either
                    log.exception(
                        "account_deletion_failure_not_recorded",
                        extra={"request_id": request.request_id},
                    )
        return ExecuteAccountDeletionsResult(completed=completed, failed=failed)
