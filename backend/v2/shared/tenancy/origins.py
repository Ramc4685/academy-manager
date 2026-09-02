"""Per-tenant redirect origins.

``validate_redirect_url`` (shared/security/redirect.py) guards an open-redirect
vector on the Stripe checkout/return URLs. Its allowlist was built only from the
static ``CORS_ORIGINS`` + ``FRONTEND_URL`` env vars, but tenants are *dynamic*:
``TenantResolver`` (ADR-0007) routes any registered ``<slug>.<base>`` subdomain
or verified custom domain. A newly onboarded academy could therefore browse and
register on its own host but never check out -- every checkout failed with
``redirect url origin not allowed``.

This module reconstructs, from **stored records plus server config**, the set of
origins that legitimately serve one academy.

Security contract (this is the whole point of the module):

* The request ``Host``/``X-Forwarded-Host`` header selects **which academy**, and
  nothing more. It is never allowlisted verbatim. That matters because
  ``TenantResolutionResult.resolved_host`` is the raw header value: with
  ``platform_base_domain`` unset (legacy deployments), ``TenantResolver`` matches
  only the *first label*, so ``Host: real-slug.attacker.example`` resolves the
  real academy. Trusting that host would hand an attacker a working
  ``https://attacker.example/...`` redirect out of the payment flow.
* Scheme and port likewise come from ``settings.frontend_url``, never from
  ``X-Forwarded-Proto`` (unauthenticated at the backend edge -- otherwise an
  allowlisted origin could be downgraded to ``http://``).
* Custom domains are read **only** from ``academy_domains`` rows with
  ``status == "verified"``. The tenant resolver's ``find_by_domain`` is laxer
  (it also matches an unverified ``custom_domain`` field on the academy row);
  this builder deliberately does not mirror that laxity. A host that resolves
  only through an unverified value keeps failing checkout exactly as it does
  today -- no regression, and the caller logs it.

Because the origins are keyed off the *resolved* ``academy_id``, an attacker who
forces resolution to some academy gains only that academy's own legitimate
origins -- which are already public and already trusted -- and tenant A's host
can never allowlist tenant B's origin.
"""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from backend.v2.shared.caching import TTLCache
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

log = logging.getLogger(__name__)

#: Same policy and rationale as ``lookup_cache`` (#527): tenant routing changes
#: only on onboarding/domain edits, so a short positive TTL is safe.
_DEFAULT_TTL_SECONDS = 60.0


class AcademyOriginLookupPort(Protocol):
    """Read-only lookup of one academy's routing identity."""

    async def routing_identity(self, academy_id: str) -> tuple[str | None, tuple[str, ...]]:
        """Return ``(slug, verified_domains)`` for ``academy_id``.

        ``verified_domains`` must contain only domains whose ownership the
        platform has verified. Implementations must never return a raw request
        host or an unverified domain value.
        """
        ...


def _scheme_and_port(frontend_url: str) -> tuple[str, str]:
    """Return ``(scheme, ":port" or "")`` from the deployment's frontend URL."""
    parsed = urlsplit(frontend_url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc
    port = ""
    # Rsplit rather than ``parsed.port`` so a malformed value degrades to "no
    # port" instead of raising.
    if ":" in netloc:
        host, _, maybe_port = netloc.rpartition(":")
        if host and maybe_port.isdigit():
            port = f":{maybe_port}"
    return scheme, port


class TenantOriginsResolver:
    """Build the allowlistable origins for one academy, with a short TTL cache."""

    def __init__(
        self,
        lookup: AcademyOriginLookupPort,
        *,
        frontend_url: str | None,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._lookup = lookup
        self._frontend_url = (frontend_url or "").strip().rstrip("/")
        self._cache: TTLCache[tuple[str, ...]] = TTLCache(ttl_seconds=ttl_seconds)

    async def for_academy(self, academy_id: str) -> tuple[str, ...]:
        """Return this academy's own origins, or ``()``.

        Never raises: a lookup failure degrades to the static-only allowlist
        (today's behaviour) rather than 500ing checkout.
        """
        if not academy_id or not self._frontend_url:
            return ()
        cached = self._cache.get(academy_id)
        if cached is not None:
            return cached
        try:
            slug, domains = await self._lookup.routing_identity(academy_id)
        except Exception as exc:  # defensive: never break the request path
            log.info("tenant_origins_lookup_failed academy_id=%s: %s", academy_id, exc)
            return ()
        origins = self._build(slug, domains)
        # Positive-only, like ``lookup_cache``: an academy that has just had its
        # slug or first verified domain written must become payable at once.
        if origins:
            self._cache.set(academy_id, origins)
        return origins

    def _build(self, slug: str | None, domains: tuple[str, ...]) -> tuple[str, ...]:
        scheme, port = _scheme_and_port(self._frontend_url)
        ordered: list[str] = []
        seen: set[str] = set()

        subdomain_origin = academy_frontend_url(frontend_url=self._frontend_url, academy_slug=slug)
        # ``academy_frontend_url`` returns the base unchanged when there is no
        # subdomain slot (a 2-label apex) or no slug -- that is the deployment
        # origin, which the static allowlist already covers.
        if subdomain_origin and subdomain_origin != self._frontend_url:
            ordered.append(subdomain_origin)
            seen.add(subdomain_origin)

        for domain in domains:
            host = (domain or "").strip().lower().rstrip(".")
            if not host or "/" in host or ":" in host:
                continue
            origin = urlunsplit((scheme, f"{host}{port}", "", "", ""))
            if origin not in seen:
                ordered.append(origin)
                seen.add(origin)
        return tuple(ordered)
