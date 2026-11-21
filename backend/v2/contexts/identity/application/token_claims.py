"""Shared policy for Firebase ID-token claims.

One module, one rule: a token only identifies an account if the identity
provider vouched for the email address on it. Both entry points that resolve a
token to a user — ``LoadAuthClaims`` (sign-in) and ``RegisterPublicParent``
(parent self-registration) — call ``require_verified_email`` so the invariant
cannot drift between them (#538: the two copies of this check were identically
wrong).
"""

from __future__ import annotations

from backend.v2.contexts.identity.domain.errors import InvalidToken

# Server-minted Firebase custom tokens. Only the deleted parent magic-link flow
# ever minted them; nothing does now. A session still carrying this provider is
# a leftover of a (possibly forwarded) inbox link, and its refresh token stays
# valid until revoked, so it is refused whatever its email claim says: the
# parent signs in again.
_REFUSED_PROVIDERS = frozenset({"custom"})


def require_verified_email(token_claims: dict[str, object]) -> None:
    """Reject a token whose email the provider has not verified.

    #538: this check used to fire only when ``sign_in_provider == "password"``,
    so any *other* provider issuing ``email_verified: false`` resolved straight
    to whichever account owns that address — an account-takeover surface the
    moment such a provider (email-link, a new social IdP, a misissued token) is
    enabled. Verification is a property of the claim, not of the provider.

    Google — the only external provider enabled today — always sets
    ``email_verified: true``, and the password path already verifies via the
    reset link, so this rejects nothing that works today.

    A missing claim counts as unverified: every real Firebase ID token carries
    it, so its absence is a malformed or hand-rolled token, not a pass.
    """
    firebase_claims = token_claims.get("firebase")
    provider = None
    if isinstance(firebase_claims, dict):
        provider = firebase_claims.get("sign_in_provider")
    if provider in _REFUSED_PROVIDERS:
        raise InvalidToken("server-minted sessions are no longer accepted")
    if token_claims.get("email_verified") is not True:
        raise InvalidToken("email must be verified")
