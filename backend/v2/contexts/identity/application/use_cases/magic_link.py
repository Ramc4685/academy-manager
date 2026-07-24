"""Issue and consume single-use parent auto-login magic links (Option C).

The parent daily digest links provisioned-but-never-activated parents straight
into the portal. Rather than emailing a bearer that stays valid forever, we mint
a one-time token here: only its SHA-256 hash is stored, it expires in 72h, it is
bound to the issuing academy, and redemption is atomic + single-use.

Security posture (do not weaken — see the feature's SECURITY callouts):

* **Single-use / race-safe** — ``ConsumeMagicLink`` claims the token through an
  atomic ``used_at=None`` conditional update; of two concurrent consumers only
  one wins, the other gets ``MagicLinkInvalid``.
* **Short-lived** — 72h TTL, after which consume returns ``MagicLinkExpired``.
* **Tenant-bound** — a token issued for one academy is rejected against another.
* **Open-redirect-safe** — ``_safe_next`` only permits a same-site absolute
  path; ``//host`` and absolute URLs collapse to the dashboard.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.v2.contexts.identity.application.ports import (
    CustomTokenPort,
    MagicLinkRepository,
)
from backend.v2.contexts.identity.domain.errors import (
    MagicLinkExpired,
    MagicLinkInvalid,
)
from backend.v2.contexts.identity.domain.models import MagicLinkRecord
from backend.v2.shared.ids import new_ulid

# 72h active window. A consumed/expired row is retained ``_PURGE_GRACE`` longer
# before the collection's TTL index deletes it — a short debug window without
# unbounded growth.
_TTL = timedelta(hours=72)
_PURGE_GRACE = timedelta(days=7)

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


class IssueMagicLink:
    """Mint a fresh single-use token and persist only its hash.

    Returns the RAW token — the sole time it exists outside the recipient's
    inbox. The caller (the digest composition root) embeds it in the email link
    and never stores it.
    """

    def __init__(self, links: MagicLinkRepository) -> None:
        self._links = links

    async def execute(self, *, user_id: str, academy_id: str, next_path: str) -> str:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        record = MagicLinkRecord(
            magic_link_id=new_ulid(),
            token_hash=_hash_token(token),
            user_id=user_id,
            academy_id=academy_id,
            next_path=_safe_next(next_path),
            created_at=now,
            expires_at=now + _TTL,
            purge_at=now + _TTL + _PURGE_GRACE,
            used_at=None,
        )
        await self._links.insert(record)
        return token


class ConsumeMagicLink:
    """Redeem a token: verify → claim atomically → mint a Firebase custom token.

    ``academy_id`` is the tenant resolved from the request host. Ordering is
    deliberate: unknown token and tenant mismatch both surface as
    ``MagicLinkInvalid`` (401) so a caller cannot probe which tokens exist;
    expiry surfaces as ``MagicLinkExpired`` (410) so the UI can offer the
    "sign in and reset password" path.
    """

    def __init__(self, *, links: MagicLinkRepository, tokens: CustomTokenPort) -> None:
        self._links = links
        self._tokens = tokens

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
        # Atomic single-use claim: only the first caller flips used_at.
        claimed = await self._links.mark_used(token_hash, used_at=now)
        if not claimed:
            raise MagicLinkInvalid()
        custom_token = await self._tokens.create_custom_token(record.user_id)
        return ConsumedMagicLink(custom_token=custom_token, next_path=_safe_next(record.next_path))
