"""CancelAccountDeletion — platform support restores a self-deleted account (mobile M5).

Owner decision on PR #1115: restore is support-only. The request is the
person's and covers every academy, so no academy admin may undo it; support
cancels it after confirming with the person, and that cancels all of it:
every academy's memberships come back to what they were, and the Firebase
login is re-enabled when at least one of them is live again.

Refused once the erasure job claimed the request or any attempt started:
an erasure that failed partway stays non-restorable and is simply retried.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.contexts.identity.domain.errors import (
    AccountDeletionInProgress,
    AccountDeletionRequestNotFound,
)
from backend.v2.contexts.identity.domain.models import SUSPENDED_MEMBERSHIP_STATUSES
from backend.v2.shared.observability.ops_alerts import capture_message

_log = logging.getLogger(__name__)


class CancellableDeletionStore(Protocol):
    async def begin_cancel(
        self, request_id: str, *, now: datetime
    ) -> AccountDeletionRequest | None:
        """Atomically mark a request no erasure has claimed or attempted (or one
        already marked by an earlier, failed cancel) so the erasure skips it."""
        ...

    async def finish_cancel(self, request_id: str) -> None: ...

    async def request_exists(self, request_id: str) -> bool: ...

    async def restore_memberships(
        self, *, aliases: tuple[str, ...], now: datetime
    ) -> frozenset[str]: ...


class FirebaseAccountSwitch(Protocol):
    async def set_user_disabled(self, uid: str, disabled: bool) -> None: ...


@dataclass(frozen=True)
class CancelAccountDeletionResult:
    request: AccountDeletionRequest
    firebase_enabled: bool


@dataclass
class CancelAccountDeletion:
    store: CancellableDeletionStore
    firebase: FirebaseAccountSwitch

    async def execute(
        self, request_id: str, *, now: datetime | None = None
    ) -> CancelAccountDeletionResult:
        now = now or datetime.now(UTC)
        # Marked first: from here the erasure job cannot claim it. The row is
        # deleted only after the restore, so a failed restore can be retried.
        request = await self.store.begin_cancel(request_id, now=now)
        if request is None:
            if await self.store.request_exists(request_id):
                raise AccountDeletionInProgress(
                    "the erasure has already started for this account; it cannot be "
                    "restored and will be retried until it finishes"
                )
            raise AccountDeletionRequestNotFound("no deletion request with this id")
        statuses = await self.store.restore_memberships(aliases=request.aliases, now=now)
        await self.store.finish_cancel(request_id)
        # Same rule as the admin status cascade: the login is shared by every
        # academy, so it comes back only if one of them grants something. A
        # person every academy had suspended had it off before the request too.
        live = bool(statuses - SUSPENDED_MEMBERSHIP_STATUSES)
        return CancelAccountDeletionResult(
            request=request,
            firebase_enabled=live and await self._enable_firebase(request.auth_uid),
        )

    async def _enable_firebase(self, auth_uid: str | None) -> bool:
        # Reported, not raised: the request is already gone, so a retry of this
        # call would find nothing. Support re-enables the login by hand instead.
        if not auth_uid:
            return False
        try:
            await self.firebase.set_user_disabled(auth_uid, False)
        except Exception:
            _log.warning(
                "identity.account_deletion_cancel_firebase_enable_failed",
                extra={"auth_uid": auth_uid},
                exc_info=True,
            )
            capture_message(
                f"Firebase account {auth_uid} not re-enabled after a deletion was cancelled",
                level="warning",
            )
            return False
        return True
