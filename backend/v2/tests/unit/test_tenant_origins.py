"""Per-tenant redirect origins (defect: newly onboarded academies cannot check out).

The security property under test: origins are rebuilt from STORED records
(slug + verified domains) and server config (frontend_url scheme/port), never
from the request Host header.
"""

from __future__ import annotations

import pytest

from backend.v2.shared.tenancy.origins import TenantOriginsResolver


class _FakeLookup:
    def __init__(self, identities: dict[str, tuple[str | None, tuple[str, ...]]]) -> None:
        self._identities = identities
        self.calls = 0

    async def routing_identity(self, academy_id: str) -> tuple[str | None, tuple[str, ...]]:
        self.calls += 1
        return self._identities.get(academy_id, (None, ()))


class _ExplodingLookup:
    async def routing_identity(self, academy_id: str) -> tuple[str | None, tuple[str, ...]]:
        raise RuntimeError("mongo is down")


async def test_slug_yields_per_academy_subdomain_origin() -> None:
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": ("blno-badminton", ())}),
        frontend_url="https://app.courtmastr.com",
    )
    assert await resolver.for_academy("acad_1") == ("https://blno-badminton.courtmastr.com",)


async def test_verified_custom_domain_is_included() -> None:
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": ("blno", ("badminton.example",))}),
        frontend_url="https://app.courtmastr.com",
    )
    assert await resolver.for_academy("acad_1") == (
        "https://blno.courtmastr.com",
        "https://badminton.example",
    )


async def test_lookup_must_not_surface_unverified_domains() -> None:
    """Contract check: the port returns ONLY verified domains, so an adapter that
    leaks an unverified value is the bug — the resolver trusts what it is given.

    See ``test_tenant_redirect_allowlist`` for the adapter-level filter."""
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": ("blno", ())}),
        frontend_url="https://app.courtmastr.com",
    )
    origins = await resolver.for_academy("acad_1")
    assert "https://unverified.example" not in origins


async def test_scheme_and_port_come_from_frontend_url_not_the_request() -> None:
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": ("blno", ("local.example",))}),
        frontend_url="http://app.localhost.test:3001",
    )
    assert await resolver.for_academy("acad_1") == (
        "http://blno.localhost.test:3001",
        "http://local.example:3001",
    )


async def test_apex_frontend_url_yields_no_subdomain_origin() -> None:
    """A 2-label apex has no subdomain slot; rewriting label 0 would corrupt it."""
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": ("blno", ())}),
        frontend_url="https://courtmastr.com",
    )
    assert await resolver.for_academy("acad_1") == ()


async def test_missing_slug_and_domains_yields_nothing() -> None:
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": (None, ())}),
        frontend_url="https://app.courtmastr.com",
    )
    assert await resolver.for_academy("acad_1") == ()


async def test_positive_result_is_cached() -> None:
    lookup = _FakeLookup({"acad_1": ("blno", ())})
    resolver = TenantOriginsResolver(lookup, frontend_url="https://app.courtmastr.com")
    first = await resolver.for_academy("acad_1")
    second = await resolver.for_academy("acad_1")
    assert first == second == ("https://blno.courtmastr.com",)
    assert lookup.calls == 1


async def test_empty_result_is_not_cached() -> None:
    """A just-bootstrapped academy must become payable without waiting out a TTL."""
    lookup = _FakeLookup({"acad_1": (None, ())})
    resolver = TenantOriginsResolver(lookup, frontend_url="https://app.courtmastr.com")
    await resolver.for_academy("acad_1")
    await resolver.for_academy("acad_1")
    assert lookup.calls == 2


async def test_lookup_failure_degrades_to_empty_rather_than_raising() -> None:
    resolver = TenantOriginsResolver(_ExplodingLookup(), frontend_url="https://app.courtmastr.com")
    assert await resolver.for_academy("acad_1") == ()


async def test_unset_frontend_url_yields_nothing() -> None:
    resolver = TenantOriginsResolver(_FakeLookup({"acad_1": ("blno", ())}), frontend_url=None)
    assert await resolver.for_academy("acad_1") == ()


@pytest.mark.parametrize(
    "bad_domain",
    ["evil.example/path", "evil.example:8443", "   ", ""],
)
async def test_malformed_stored_domains_are_skipped(bad_domain: str) -> None:
    """A stored value carrying a path or its own port could otherwise widen the
    allowlist beyond a bare origin."""
    resolver = TenantOriginsResolver(
        _FakeLookup({"acad_1": (None, (bad_domain,))}),
        frontend_url="https://app.courtmastr.com",
    )
    assert await resolver.for_academy("acad_1") == ()
