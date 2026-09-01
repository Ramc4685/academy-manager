"""Stateless HMAC unsubscribe tokens (#555).

Requirements this scheme has to meet, and why the obvious alternative fails:

* **Re-derivable.** The same link must appear in tomorrow's digest and the one
  after. ``IssueMagicLink`` stores only a SHA-256 of a one-time token and hands
  back the raw value once — it cannot regenerate a link for the next send, so
  a magic-link-style stored token is the wrong tool here.
* **Long-lived.** A six-month-old email must still unsubscribe. There is
  therefore no expiry in the payload; the token is revoked by rotating the
  secret.
* **Unguessable and non-transferable.** The MAC covers ``academy_id`` *and*
  ``user_id``, and verification is always checked against the academy the
  request resolved to, so a token minted for one family can never flip another
  family's preferences — nor the same user's under a different tenant.
* **Prefetch-safe.** The token carries no authority on its own: the emailed
  link points at a page, and the mutation is a POST. See
  ``interfaces/unsubscribe_routes.py``.

The payload is two opaque ids — no address, no name — so nothing personal
lands in a URL, an access log, or a ``Referer`` header.

Fail-closed, not fail-open: with no secret configured, ``mint`` returns
``None`` and ``verify`` rejects everything. (Contrast ``composition/admin.py``'s
``stripe_connect_state_secret or stripe_webhook_secret or ""``, which signs
with an empty key when unconfigured — do not copy that tail.)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import quote

from backend.v2.shared.tenancy.academy_url import academy_frontend_url

_VERSION = "u1"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def mint_unsubscribe_token(*, academy_id: str, user_id: str, secret: str | None) -> str | None:
    """Return a re-derivable unsubscribe token, or ``None`` with no secret."""
    if not secret:
        return None
    payload = f"{academy_id}:{user_id}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{_VERSION}.{_b64(payload.encode())}.{_b64(mac)}"


def verify_unsubscribe_token(token: str, *, secret: str | None) -> tuple[str, str] | None:
    """Return ``(academy_id, user_id)``, or ``None`` when the token is not ours.

    Never raises and never distinguishes *why* a token failed: the caller maps
    every failure to one opaque 401, so the endpoint cannot be used to probe
    which ids exist.
    """
    if not secret or not token:
        return None
    try:
        version, payload_b64, mac_b64 = token.split(".")
        if version != _VERSION:
            return None
        payload = _unb64(payload_b64)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac_b64)):
            return None
        academy_id, _, user_id = payload.decode().partition(":")
    except Exception:
        return None
    if not academy_id or not user_id:
        return None
    return academy_id, user_id


@dataclass(frozen=True, slots=True)
class UnsubscribeLinkBuilder:
    """Builds the one-click unsubscribe URL put in a digest/campaign footer.

    Returns ``None`` when either the secret or the frontend base URL is
    missing — the footer then renders a plain "manage your email preferences"
    portal pointer instead of a dead link.

    The URL is built on the recipient academy's own subdomain, exactly like
    the portal and magic links in the very same digest
    (``shared/tenancy/academy_url``): ``TenantResolver`` reads the tenant from
    the host's first label, so a link on the deployment's generic
    ``frontend_url`` resolves to no tenant at all. ``interfaces/unsubscribe_routes``
    refuses an unresolved tenant in SaaS mode, so getting this host wrong does
    not silently weaken the tenant check — it breaks the link loudly.
    """

    frontend_url: str | None = None
    secret: str | None = None

    def build(
        self, *, academy_id: str, user_id: str, academy_slug: str | None = None
    ) -> str | None:
        base = academy_frontend_url(frontend_url=self.frontend_url, academy_slug=academy_slug)
        if not base:
            return None
        token = mint_unsubscribe_token(academy_id=academy_id, user_id=user_id, secret=self.secret)
        if token is None:
            return None
        return f"{base.rstrip('/')}/unsubscribe?t={quote(token, safe='')}"
