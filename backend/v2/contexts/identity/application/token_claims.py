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

# Providers whose tokens this backend mints for itself. ``ConsumeMagicLink``
# calls ``create_custom_token`` with a ``user_id`` it has already resolved from
# a single-use link, so the identity is ours, not the caller's — there is no
# attacker-supplied email claim to verify. Firebase provisions those accounts
# with ``email_verified=False`` (see ``FirebaseAdminAdapter.create_user``), so
# demanding the claim here would lock out every magic-link parent.
_SERVER_MINTED_PROVIDERS = frozenset({"custom"})


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
    if provider in _SERVER_MINTED_PROVIDERS:
        return
    if token_claims.get("email_verified") is not True:
        raise InvalidToken("email must be verified")
