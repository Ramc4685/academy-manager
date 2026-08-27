"""Repoint a Firebase-hosted auth action link at one tenant's own portal.

`generate_password_reset_link` returns a link on the Firebase project's
default `authDomain` -- a single, project-wide host:

    https://<project>.firebaseapp.com/__/auth/action?mode=resetPassword&oobCode=...

That host is generic and unbranded, and it is the *same* for every tenant.
The Firebase Console's "action URL" setting cannot fix this: it is one
project-wide value, so it can never point at a per-academy subdomain. The
only way to land a parent on their own academy's host (ADR-0007 resolves
the tenant from the request Host's first label) is to rewrite the link
server-side, which is what this module does.

Rewriting is safe because the `oobCode` is redeemed against the Identity
Toolkit API directly by the Firebase JS SDK -- the page that hosts the
redemption is irrelevant to Firebase. Every query parameter is preserved
verbatim so the in-app handler receives exactly what the hosted page would
have (`mode`, `oobCode`, `apiKey`, `lang`, and `continueUrl` when
ActionCodeSettings supplied one).
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

#: Path of the in-app handler; mirrors `frontend/app/(marketing)/auth/action`.
AUTH_ACTION_PATH = "/auth/action"


def tenant_auth_action_link(*, firebase_link: str, portal_url: str | None) -> str:
    """Return `firebase_link` re-hosted on `portal_url` at ``/auth/action``.

    Falls back to `firebase_link` unchanged when `portal_url` is missing or
    is not an absolute http(s) URL -- an un-rewritten Firebase link still
    works (it just lands on the generic hosted page), so a bad tenant URL
    must never cost the parent their invite.
    """
    link = (firebase_link or "").strip()
    base = (portal_url or "").strip().rstrip("/")
    if not link or not base:
        return link

    target = urlsplit(base)
    if target.scheme not in {"http", "https"} or not target.netloc:
        return link

    source = urlsplit(link)
    if not source.query:
        # No oobCode to carry over -- not a link we recognise; leave it be.
        return link

    return urlunsplit(
        (target.scheme, target.netloc, AUTH_ACTION_PATH, source.query, source.fragment)
    )
