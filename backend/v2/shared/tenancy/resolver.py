"""SaaS tenant resolver.

Resolution order (per ADR-0007):
  1. Subdomain   — first segment of Host maps to an academy slug
  2. Custom domain — full Host value looked up in academy_domains
  3. Approved internal header — named header, only when configured

Tenant is NEVER inferred from the authenticated user alone.
default_academy_id is NEVER used here.

Security invariants (issue #519):
  - The internal tenant header is only honoured when the request also
    presents the proxy shared secret via ``x-cm-proxy-auth`` (mirroring
    shared/http/rate_limit.py). No secret configured ⇒ header disabled.
  - The header value must name a registered academy (existence check via
    the lookup port) — it is never returned verbatim.
  - When ``platform_base_domain`` is configured, subdomain resolution only
    applies to hosts of the form ``<slug>.<platform_base_domain>`` so an
    attacker-controlled Host like ``victim-slug.attacker.example`` cannot
    resolve the victim tenant.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

#: Header carrying the proxy shared secret (same gate as the rate limiter).
PROXY_AUTH_HEADER = "x-cm-proxy-auth"

# ---------------------------------------------------------------------------
# Port (Protocol) for academy / domain lookup
# ---------------------------------------------------------------------------


class AcademyLookupPort(Protocol):
    """Read-only interface used by TenantResolver to find academies.

    Implementations may call Mongo, a cache, or an in-memory fake.
    The resolver never talks to the database directly.
    """

    async def find_by_slug(self, slug: str) -> str | None:
        """Return academy_id whose slug matches, or None."""
        ...

    async def find_by_domain(self, domain: str) -> str | None:
        """Return academy_id for a verified custom domain, or None."""
        ...

    async def exists(self, academy_id: str) -> bool:
        """Return True when academy_id names a registered academy."""
        ...


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class TenantSource(StrEnum):
    SUBDOMAIN = "subdomain"
    CUSTOM_DOMAIN = "custom_domain"
    INTERNAL_HEADER = "internal_header"


@dataclass(frozen=True)
class TenantResolutionResult:
    """Successful resolution of the academy tenant for this request."""

    academy_id: str
    source: TenantSource
    resolved_host: str | None = None  # host/domain that triggered resolution


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class TenantResolutionError(Exception):
    """Raised when no tenant source yields a known academy.

    Callers (middleware) should translate this to 400 or 422 for public
    routes, or 401 for authenticated routes where the academy is mandatory.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TenantResolver:
    """Resolves the academy tenant from a request's Host header and headers.

    Resolution order:
      1. Subdomain slug (first Host segment)
      2. Custom domain (full Host value)
      3. Internal header (only when allowed_internal_header is configured)

    Pass host and headers extracted from the HTTP request. This class does
    not depend on any web framework so it stays pure and trivially testable.
    """

    def __init__(
        self,
        *,
        lookup: AcademyLookupPort,
        allowed_internal_header: str | None = None,
        internal_header_secret: str | None = None,
        platform_base_domain: str | None = None,
    ) -> None:
        self._lookup = lookup
        # Normalize to lowercase — HTTP headers are case-insensitive.
        # Callers (e.g. Starlette) may lowercase keys; we match either way.
        self._allowed_internal_header = (
            allowed_internal_header.lower() if allowed_internal_header else None
        )
        # Shared secret required alongside the internal header. When None,
        # the internal header source is disabled entirely (fail closed):
        # a client-supplied header name alone must never select a tenant.
        self._internal_header_secret = internal_header_secret or None
        # When configured, subdomain resolution only applies to hosts under
        # this base domain (``<slug>.<platform_base_domain>``).
        self._platform_base_domain = (
            platform_base_domain.lower().strip(".") if platform_base_domain else None
        )

    async def resolve(
        self,
        *,
        host: str,
        headers: dict[str, str],
    ) -> TenantResolutionResult:
        """Resolve tenant from the request host and headers.

        Raises TenantResolutionError when no source resolves to a known academy.
        Never falls back to a default academy ID.
        """
        bare_host = _strip_port(host)

        # --- 1. Subdomain ---
        slug = self._extract_subdomain_slug(bare_host)
        if slug is not None:
            academy_id = await self._lookup.find_by_slug(slug)
            if academy_id is not None:
                return TenantResolutionResult(
                    academy_id=academy_id,
                    source=TenantSource.SUBDOMAIN,
                    resolved_host=bare_host,
                )

        # --- 2. Custom domain ---
        if bare_host:
            academy_id = await self._lookup.find_by_domain(bare_host)
            if academy_id is not None:
                return TenantResolutionResult(
                    academy_id=academy_id,
                    source=TenantSource.CUSTOM_DOMAIN,
                    resolved_host=bare_host,
                )

        # --- 3. Internal header (only when configured AND secret-gated) ---
        if self._allowed_internal_header is not None and self._internal_header_secret is not None:
            # Case-insensitive: lowercase both sides since HTTP headers are
            # case-insensitive and Starlette normalizes them to lowercase.
            lowered = {k.lower(): v for k, v in headers.items()}
            header_val = lowered.get(self._allowed_internal_header)
            presented_secret = lowered.get(PROXY_AUTH_HEADER)
            if (
                header_val
                and presented_secret is not None
                and hmac.compare_digest(presented_secret, self._internal_header_secret)
                and await self._lookup.exists(header_val)
            ):
                return TenantResolutionResult(
                    academy_id=header_val,
                    source=TenantSource.INTERNAL_HEADER,
                    resolved_host=None,
                )

        raise TenantResolutionError(
            f"Could not resolve tenant from host={bare_host!r}. "
            "Provide a registered subdomain, verified custom domain, "
            "or (if configured) the approved internal tenant header."
        )

    def _extract_subdomain_slug(self, bare_host: str) -> str | None:
        """Return the slug candidate for subdomain resolution, or None.

        With ``platform_base_domain`` configured, only ``<slug>.<base>``
        hosts qualify — the parent domain must equal the platform base
        domain exactly, so ``victim-slug.attacker.example`` never reaches
        the slug lookup. Without it (legacy deployments), fall back to the
        historical first-label behaviour.
        """
        parts = bare_host.split(".")
        if len(parts) < 2:
            return None
        if self._platform_base_domain is not None:
            slug, _, parent = bare_host.partition(".")
            if parent.lower() != self._platform_base_domain or not slug:
                return None
            return slug
        return parts[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_port(host: str) -> str:
    """Remove :port from a Host header value."""
    if ":" in host:
        return host.rsplit(":", 1)[0]
    return host
