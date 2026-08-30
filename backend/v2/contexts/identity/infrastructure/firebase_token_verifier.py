"""Firebase ID token verifier backed by the v2 Firebase Admin adapter.

Issue #527: ``verify_id_token(..., check_revoked=True)`` performs a
synchronous HTTPS call to Firebase Auth, and it used to run on EVERY
authenticated request — adding an external round trip to every BFF call and
making Firebase a hard availability dependency for already-verified users.

We now memoize successful verifications in a short-TTL in-process cache
keyed by the SHA-256 of the raw token. Consequences, considered:

* Revocation (``auth.revoke_refresh_tokens``) and Firebase-side user
  disablement can lag by up to ``_CACHE_TTL_SECONDS`` for a token that was
  verified within the window. Immediate lockout is still enforced per
  request by ``LoadAuthClaims`` via ``users.is_active`` and membership
  status, which are the levers this codebase actually uses to cut access.
* Entries never outlive the token's own ``exp`` claim.
* Failures are never cached — a bad token re-verifies every time.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)
from backend.v2.shared.caching import TTLCache

#: How long a successful verification is trusted before Firebase is asked
#: again. Short enough that revocation lag stays in "seconds", long enough
#: to collapse the per-request round trip for an active user session.
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_SIZE = 2048


class FirebaseTokenVerifier:
    """Real verifier backed by v2 Firebase Admin infrastructure."""

    def __init__(self) -> None:
        self._cache: TTLCache[dict[str, object]] = TTLCache(
            ttl_seconds=_CACHE_TTL_SECONDS, max_size=_CACHE_MAX_SIZE
        )

    async def verify(self, id_token: str) -> dict[str, object]:
        key = hashlib.sha256(id_token.encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            # Copy so a caller mutating its claims dict cannot poison the
            # cached entry for later requests.
            return dict(cached)
        # Firebase verification is sync; offload to a thread.
        claims = await asyncio.to_thread(get_firebase_admin_adapter().verify_id_token, id_token)
        self._cache.set(key, dict(claims), ttl_seconds=_ttl_until_token_expiry(claims))
        return claims


def _ttl_until_token_expiry(claims: dict[str, object]) -> float | None:
    """Cap the cache TTL at the token's own ``exp`` (epoch seconds).

    Returns None (use the default TTL) when ``exp`` is absent or malformed —
    the token already passed full verification, so a missing claim here is a
    fake-adapter artifact in tests, not a security signal.
    """
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return float(exp) - time.time()
