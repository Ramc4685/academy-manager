"""Unit tests for shared.tenancy.resolver.

Tests cover the six required scenarios (ADR-0007 / Agent B mission):
  - subdomain resolves academy
  - custom domain resolves academy
  - internal header resolves only when configured
  - unknown tenant rejects
  - user-only request does not resolve tenant
  - default_academy_id is not used in SaaS resolver
"""

from __future__ import annotations

import pytest

from backend.v2.shared.tenancy.resolver import (
    TenantResolutionError,
    TenantResolutionResult,
    TenantResolver,
    TenantSource,
)

# ---------------------------------------------------------------------------
# In-memory fake for AcademyLookupPort
# ---------------------------------------------------------------------------


class FakeAcademyLookup:
    """In-memory stand-in for the DB-backed lookup port."""

    def __init__(
        self,
        *,
        slugs: dict[str, str] | None = None,
        domains: dict[str, str] | None = None,
    ) -> None:
        self._slugs: dict[str, str] = slugs or {}
        self._domains: dict[str, str] = domains or {}

    async def find_by_slug(self, slug: str) -> str | None:
        return self._slugs.get(slug)

    async def find_by_domain(self, domain: str) -> str | None:
        return self._domains.get(domain)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolver(
    *,
    slugs: dict[str, str] | None = None,
    domains: dict[str, str] | None = None,
    allowed_internal_header: str | None = None,
) -> TenantResolver:
    return TenantResolver(
        lookup=FakeAcademyLookup(slugs=slugs, domains=domains),
        allowed_internal_header=allowed_internal_header,
    )


# ---------------------------------------------------------------------------
# Subdomain resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subdomain_resolves_academy() -> None:
    r = _resolver(slugs={"courtmastr": "academy-court"})
    result = await r.resolve(host="courtmastr.app.example.com", headers={})
    assert result.academy_id == "academy-court"
    assert result.source == TenantSource.SUBDOMAIN
    assert result.resolved_host == "courtmastr.app.example.com"


@pytest.mark.asyncio
async def test_subdomain_strips_port_before_slug_extraction() -> None:
    r = _resolver(slugs={"alpha": "academy-alpha"})
    result = await r.resolve(host="alpha.example.com:8080", headers={})
    assert result.academy_id == "academy-alpha"
    assert result.source == TenantSource.SUBDOMAIN
    assert result.resolved_host == "alpha.example.com"


@pytest.mark.asyncio
async def test_subdomain_unknown_falls_through_to_custom_domain() -> None:
    """Unknown slug tries custom domain before giving up."""
    r = _resolver(
        slugs={},  # slug not registered
        domains={"custom.academy.io": "academy-custom"},
    )
    result = await r.resolve(host="custom.academy.io", headers={})
    assert result.academy_id == "academy-custom"
    assert result.source == TenantSource.CUSTOM_DOMAIN


# ---------------------------------------------------------------------------
# Custom domain resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_domain_resolves_academy() -> None:
    r = _resolver(domains={"tennis-club.com": "academy-tennis"})
    result = await r.resolve(host="tennis-club.com", headers={})
    assert result.academy_id == "academy-tennis"
    assert result.source == TenantSource.CUSTOM_DOMAIN
    assert result.resolved_host == "tennis-club.com"


@pytest.mark.asyncio
async def test_custom_domain_preferred_over_subdomain_slug_not_registered() -> None:
    """When slug resolves nothing, custom domain wins."""
    r = _resolver(
        slugs={},
        domains={"badminton.club": "academy-badminton"},
    )
    result = await r.resolve(host="badminton.club", headers={})
    assert result.source == TenantSource.CUSTOM_DOMAIN
    assert result.academy_id == "academy-badminton"


# ---------------------------------------------------------------------------
# Internal header resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_header_resolves_when_configured() -> None:
    r = _resolver(allowed_internal_header="X-Internal-Academy-Id")
    result = await r.resolve(
        host="api.internal.example.com",
        headers={"X-Internal-Academy-Id": "academy-internal"},
    )
    assert result.academy_id == "academy-internal"
    assert result.source == TenantSource.INTERNAL_HEADER
    assert result.resolved_host is None


@pytest.mark.asyncio
async def test_internal_header_rejected_when_not_configured() -> None:
    """Resolver with no allowed_internal_header ignores the header."""
    r = _resolver(allowed_internal_header=None)
    with pytest.raises(TenantResolutionError):
        await r.resolve(
            host="unknown.example.com",
            headers={"X-Internal-Academy-Id": "academy-internal"},
        )


@pytest.mark.asyncio
async def test_internal_header_ignored_when_wrong_name_configured() -> None:
    """Only the exact configured header name is accepted."""
    r = _resolver(allowed_internal_header="X-My-Tenant-Header")
    with pytest.raises(TenantResolutionError):
        await r.resolve(
            host="unknown.example.com",
            headers={"X-Internal-Academy-Id": "academy-internal"},
        )


@pytest.mark.asyncio
async def test_subdomain_wins_over_internal_header() -> None:
    """Subdomain match takes priority even when internal header is present."""
    r = _resolver(
        slugs={"court": "academy-court"},
        allowed_internal_header="X-Internal-Academy-Id",
    )
    result = await r.resolve(
        host="court.example.com",
        headers={"X-Internal-Academy-Id": "academy-other"},
    )
    assert result.academy_id == "academy-court"
    assert result.source == TenantSource.SUBDOMAIN


# ---------------------------------------------------------------------------
# Unknown tenant rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_subdomain_rejects() -> None:
    r = _resolver(slugs={}, domains={})
    with pytest.raises(TenantResolutionError) as exc_info:
        await r.resolve(host="nobody.example.com", headers={})
    assert "nobody.example.com" in exc_info.value.reason


@pytest.mark.asyncio
async def test_unknown_custom_domain_rejects() -> None:
    r = _resolver(slugs={}, domains={})
    with pytest.raises(TenantResolutionError):
        await r.resolve(host="ghost-academy.com", headers={})


@pytest.mark.asyncio
async def test_empty_host_with_no_header_rejects() -> None:
    r = _resolver()
    with pytest.raises(TenantResolutionError):
        await r.resolve(host="", headers={})


# ---------------------------------------------------------------------------
# User-only request does not resolve tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_only_request_does_not_resolve_tenant() -> None:
    """Resolver does not accept user identity as a tenant source.

    Even if we pass user metadata in headers (which app code should never
    do), the resolver only looks at the Host header and the configured
    internal-tenant header. User-context headers are ignored entirely.
    """
    r = _resolver(slugs={}, domains={})
    # Simulate headers that carry user info but no valid tenant source
    user_headers = {
        "X-User-Id": "user-123",
        "X-User-Email": "coach@academy.example.com",
        "Authorization": "Bearer fake-token",
    }
    with pytest.raises(TenantResolutionError):
        await r.resolve(host="no-tenant.example.com", headers=user_headers)


# ---------------------------------------------------------------------------
# default_academy_id is not used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_academy_id_is_not_used_as_fallback() -> None:
    """TenantResolver never falls back to a default academy ID.

    The resolver raises TenantResolutionError rather than silently returning
    a default tenant — that would be the single-tenant fallback pattern
    that SaaS mode prohibits (ADR-0007 §5).
    """
    default_id = "default-academy"
    r = _resolver(
        # Even if the slug happens to match a "default-academy" slug,
        # an empty lookup means nothing is registered.
        slugs={},
        domains={},
        allowed_internal_header=None,
    )
    with pytest.raises(TenantResolutionError) as exc_info:
        await r.resolve(host="some.example.com", headers={})
    # The error must NOT contain a suggestion to fall back to default_id
    assert default_id not in exc_info.value.reason


# ---------------------------------------------------------------------------
# Result type checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_is_frozen() -> None:
    r = _resolver(slugs={"court": "academy-court"})
    result = await r.resolve(host="court.example.com", headers={})
    assert isinstance(result, TenantResolutionResult)
    with pytest.raises(Exception):  # noqa: B017
        result.academy_id = "tampered"  # type: ignore[misc]
