"""Rewrite a deployment's frontend URL to one academy's own subdomain.

TenantResolver (ADR-0007) resolves the academy tenant from the first label
of the request Host -- that label is the academy's `slug`. Any outbound link
(email, digest, reminder) must point at that same per-academy host, not the
deployment's raw ``frontend_url`` (which may be a generic default), or a
parent clicking through can land on the wrong tenant subdomain -- or one that
does not resolve to any tenant at all.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def academy_frontend_url(*, frontend_url: str | None, academy_slug: str | None) -> str:
    """Return ``frontend_url`` with its host's first label replaced by
    ``academy_slug``. Falls back to ``frontend_url`` unchanged (rstripped)
    when either input is missing or the host has no room for a subdomain."""
    base = (frontend_url or "").rstrip("/")
    if not base or not academy_slug:
        return base
    parsed = urlsplit(base)
    host_parts = parsed.netloc.split(".")
    if len(host_parts) < 3:
        # A bare 2-label host (e.g. "courtmastr.com") has no subdomain slot
        # to replace -- rewriting label 0 would corrupt the apex domain
        # itself rather than swap in a per-academy subdomain.
        return base
    new_netloc = ".".join([academy_slug, *host_parts[1:]])
    return urlunsplit((parsed.scheme, new_netloc, "", "", ""))
