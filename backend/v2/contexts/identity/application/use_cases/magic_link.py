"""Consume single-use parent auto-login magic links already sent (Option C).

The issue path is deleted: an emailed link that grants a session is a
forwardable bearer credential (OWASP, NIST 800-63B), so nothing mints these any
more and the digest links to the sign-in page instead. Consume, its route and
the /auth/magic page remain only for links already in inboxes (72h TTL) and are
deleted in a cleanup once the last one has expired.

Security posture (do not weaken — see the feature's SECURITY callouts):

* **Single-use / race-safe** — ``ConsumeMagicLink`` claims the token through an
  atomic ``used_at=None`` conditional update; of two concurrent consumers only
  one wins, the other gets ``MagicLinkInvalid``.
* **Short-lived** — 72h TTL, after which consume returns ``MagicLinkExpired``.
* **Tenant-bound** — a token issued for one academy is rejected against another.
* **Parent-only, least privilege** — consume succeeds only for a user whose
  membership in the token's academy is active and whose roles are exactly
  ``{"parent"}``. Anyone holding a staff role (or removed, or cross-tenant) gets
  the same opaque ``MagicLinkInvalid`` as an unknown token and signs in normally.
* **Open-redirect-safe** — ``_safe_next`` only permits a same-site absolute
  path; ``//host`` and absolute URLs collapse to the dashboard.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.identity.application.ports import (
    CustomTokenPort,
    MagicLinkRepository,
    MembershipLookup,
    UserRepository,
)
from backend.v2.contexts.identity.domain.errors import (
    MagicLinkExpired,
    MagicLinkInvalid,
)
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases

# Where a token with no (or an unsafe) ``next_path`` lands.
_DEFAULT_NEXT = "/parent/dashboard"


def _hash_token(token: str) -> str:
    """Return the hex SHA-256 of ``token`` — the only form we ever persist."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_next(next_path: str | None) -> str:
    """Collapse anything that is not a same-site absolute path to the dashboard.

    Guards against the magic link being turned into an open redirect. Only a
    value beginning with a single ``/`` is allowed through; protocol-relative
    (``//host``) and absolute (``https://evil``) targets are rejected.
    """
    if not next_path or not isinstance(next_path, str):
        return _DEFAULT_NEXT
    if not next_path.startswith("/") or next_path.startswith("//"):
        return _DEFAULT_NEXT
    return next_path


@dataclass(frozen=True, slots=True)
class ConsumedMagicLink:
    """Result of a successful redemption."""

    custom_token: str
    next_path: str


class ConsumeMagicLink:
    """Redeem a token: verify → claim atomically → mint a Firebase custom token.

    ``academy_id`` is the tenant resolved from the request host. Ordering is
    deliberate: unknown token and tenant mismatch both surface as
    ``MagicLinkInvalid`` (401) so a caller cannot probe which tokens exist;
    expiry surfaces as ``MagicLinkExpired`` (410) so the UI can offer the
    "sign in and reset password" path.
    """

    def __init__(
        self,
        *,
        links: MagicLinkRepository,
        tokens: CustomTokenPort,
        users: UserRepository,
        memberships: MembershipLookup,
    ) -> None:
        self._links = links
        self._tokens = tokens
        self._users = users
        self._memberships = memberships

    async def execute(self, token: str, *, academy_id: str) -> ConsumedMagicLink:
        token_hash = _hash_token(token)
        record = await self._links.get_by_hash(token_hash)
        if record is None:
            raise MagicLinkInvalid()
        # Tenant binding — enforced here rather than in the repo query so a
        # cross-tenant token is indistinguishable from an unknown one.
        if record.academy_id != academy_id:
            raise MagicLinkInvalid()
        now = datetime.now(UTC)
        if record.is_expired(now=now):
            raise MagicLinkExpired()
        # The link records the roster id; the session must be the parent's real
        # Firebase account, which provisioning may have keyed differently. A
        # custom token for an unknown uid would make Firebase create an empty,
        # email-less account that the API then rejects.
        if record.used_at is not None:
            raise MagicLinkInvalid()
        user = await self._users.get_by_id(record.user_id)
        # The repo already folds a legacy auth_uid into firebase_uid.
        uid = user.firebase_uid if user is not None else None
        if user is None or not uid or user.global_status != "active":
            raise MagicLinkInvalid()
        # Least privilege: an inbox link may only ever become a parent-only
        # session. A user who also holds a staff role (or was removed) must sign
        # in normally, so a forwarded link can never open a staff session.
        membership = await self._memberships.get_for_user_in_academy(
            user_id=user.user_id,
            academy_id=record.academy_id,
            aliases=identity_aliases(user.user_id, user.firebase_uid, user.auth_uid),
        )
        if membership is None or not membership.is_active() or set(membership.roles) != {"parent"}:
            raise MagicLinkInvalid()
        # Mint before claiming: minting has no side effects, so a Firebase
        # failure here leaves the link redeemable on retry.
        custom_token = await self._tokens.create_custom_token(uid)
        # Atomic single-use claim: only the first caller flips used_at.
        claimed = await self._links.mark_used(token_hash, used_at=now)
        if not claimed:
            raise MagicLinkInvalid()
        return ConsumedMagicLink(custom_token=custom_token, next_path=_safe_next(record.next_path))
