"""RequestAccountDeletion — a signed-in person deletes their own account (mobile M5, D1).

Apple 5.1.1(v) and Google Play require deletion to start inside the app. This
use case is the request half: it refuses the two cases that would strand an
academy (its last owner, a coach with upcoming classes), then locks the
account everywhere at once and schedules the anonymising executor (D3).

Order matters: the request row is written first so a crash part-way leaves a
record the executor and support can see, then memberships are removed (what
``LoadAuthClaims`` checks, so the lockout is effective from here), then
Firebase is disabled best-effort, mirroring the admin disable path (#785).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.v2.contexts.identity.domain.account_deletion import (
    COACHING_ROLES,
    GRACE_PERIOD,
    REAUTH_WINDOW,
    AccountDeletionRequest,
    DeletableAccount,
)
from backend.v2.contexts.identity.domain.errors import (
    CannotRemoveLastOwner,
    CoachHasFutureSessions,
    RecentSignInRequired,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.observability.ops_alerts import capture_message

_log = logging.getLogger(__name__)


class AccountDeletionStore(Protocol):
    async def load_account(self, *, user_id: str, email: str) -> DeletableAccount: ...

    async def find_request(self, aliases: tuple[str, ...]) -> AccountDeletionRequest | None: ...

    async def create_request(self, request: AccountDeletionRequest) -> AccountDeletionRequest:
        """Insert, or return the request already on file for this account."""
        ...

    async def other_active_owner_exists(
        self, *, academy_id: str, aliases: tuple[str, ...]
    ) -> bool: ...

    async def upcoming_coaching_count(
        self, *, academy_id: str, aliases: tuple[str, ...]
    ) -> int: ...

    async def remove_memberships(self, *, aliases: tuple[str, ...], now: datetime) -> None: ...

    async def record_audit(
        self, *, academy_id: str, request: AccountDeletionRequest, roles: tuple[str, ...]
    ) -> None: ...


class FirebaseAccountSwitch(Protocol):
    async def set_user_disabled(self, uid: str, disabled: bool) -> None: ...


@dataclass(frozen=True)
class RequestAccountDeletionCommand:
    user_id: str
    email: str
    signed_in_at: datetime | None


@dataclass
class RequestAccountDeletion:
    store: AccountDeletionStore
    firebase: FirebaseAccountSwitch

    async def execute(
        self, cmd: RequestAccountDeletionCommand, *, now: datetime | None = None
    ) -> AccountDeletionRequest:
        now = now or datetime.now(UTC)
        # Mongo keeps milliseconds; trim so this answer matches the stored row.
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        if cmd.signed_in_at is None or now - cmd.signed_in_at > REAUTH_WINDOW:
            raise RecentSignInRequired("sign in again to delete your account")

        account = await self.store.load_account(user_id=cmd.user_id, email=cmd.email)
        existing = await self.store.find_request(account.aliases)
        if existing is not None:
            return existing

        live = [m for m in account.memberships if m.status != "removed"]
        for m in live:
            if (
                "owner" in m.roles
                and m.status == "active"
                and not await self.store.other_active_owner_exists(
                    academy_id=m.academy_id, aliases=account.aliases
                )
            ):
                raise CannotRemoveLastOwner(
                    "you are the only owner of an academy; add another owner "
                    "or ask CourtMastr to close the academy first"
                )
        for m in live:
            if COACHING_ROLES & set(m.roles) and await self.store.upcoming_coaching_count(
                academy_id=m.academy_id, aliases=account.aliases
            ):
                raise CoachHasFutureSessions(
                    "upcoming classes are still assigned to you; ask the academy "
                    "to reassign them, then delete your account"
                )

        request = await self.store.create_request(
            AccountDeletionRequest(
                request_id=str(new_ulid()),
                user_id=account.user_id,
                auth_uid=account.auth_uid,
                email=account.email,
                aliases=account.aliases,
                academy_ids=tuple(dict.fromkeys(m.academy_id for m in live)),
                requested_at=now,
                execute_after=now + GRACE_PERIOD,
            )
        )
        await self.store.remove_memberships(aliases=account.aliases, now=now)
        for m in live:
            await self.store.record_audit(academy_id=m.academy_id, request=request, roles=m.roles)
        await self._disable_firebase(request.auth_uid)
        return request

    async def _disable_firebase(self, auth_uid: str | None) -> None:
        # Best-effort like the admin disable (#785): the membership removal
        # above already stops this API issuing claims; Firebase also kills
        # refresh tokens, and D3 deletes the Firebase account regardless.
        if not auth_uid:
            return
        try:
            await self.firebase.set_user_disabled(auth_uid, True)
        except Exception:
            _log.warning(
                "identity.account_deletion_firebase_disable_failed",
                extra={"auth_uid": auth_uid},
                exc_info=True,
            )
            capture_message(
                f"Firebase account {auth_uid} not disabled after a deletion request",
                level="warning",
            )
