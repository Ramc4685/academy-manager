"""Issue #527: per-request auth caching.

Covers the three caches added to take Firebase + Mongo off the per-request
hot path:

* ``FirebaseTokenVerifier`` memoizes successful verifications (keyed by
  token hash, capped by the token's own ``exp``); failures are never cached.
* ``CachingAcademyLookup`` caches positive slug/domain -> academy_id hits
  and never caches misses.
* The tenant-servability checker built in ``main.py`` caches
  ``get_tenant_health`` per academy.
* ``TTLCache`` primitive: expiry and bounded size.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.v2.contexts.identity.infrastructure import firebase_token_verifier as ftv_module
from backend.v2.contexts.identity.infrastructure.firebase_token_verifier import (
    FirebaseTokenVerifier,
)
from backend.v2.main import _build_tenant_servability_checker
from backend.v2.shared.caching import TTLCache
from backend.v2.shared.tenancy.lookup_cache import CachingAcademyLookup

# ---------------------------------------------------------------------------
# TTLCache primitive
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_ttl_cache_expires_entries() -> None:
    clock = _FakeClock()
    cache: TTLCache[str] = TTLCache(ttl_seconds=30.0, clock=clock)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    clock.now += 29.9
    assert cache.get("k") == "v"
    clock.now += 0.2
    assert cache.get("k") is None


def test_ttl_cache_per_entry_ttl_is_capped_at_default() -> None:
    clock = _FakeClock()
    cache: TTLCache[str] = TTLCache(ttl_seconds=30.0, clock=clock)
    cache.set("short", "v", ttl_seconds=5.0)
    cache.set("long", "v", ttl_seconds=500.0)  # capped to 30s
    cache.set("stale", "v", ttl_seconds=-1.0)  # never stored
    assert cache.get("stale") is None
    clock.now += 6.0
    assert cache.get("short") is None
    clock.now += 25.0  # t+31 total
    assert cache.get("long") is None


def test_ttl_cache_bounds_size_by_evicting_oldest() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60.0, max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert len(cache) == 2
    assert cache.get("a") is None  # oldest evicted
    assert cache.get("b") == 2
    assert cache.get("c") == 3


# ---------------------------------------------------------------------------
# FirebaseTokenVerifier caching
# ---------------------------------------------------------------------------


class _CountingAdapter:
    def __init__(self, claims: dict[str, object] | None = None, error: Exception | None = None):
        self.calls = 0
        self._claims = claims or {"email": "a@b.c", "exp": time.time() + 3600}
        self._error = error

    def verify_id_token(self, token: str) -> dict[str, object]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self._claims)


@pytest.mark.asyncio
async def test_verifier_caches_successful_verification(monkeypatch) -> None:
    adapter = _CountingAdapter()
    monkeypatch.setattr(ftv_module, "get_firebase_admin_adapter", lambda: adapter)
    verifier = FirebaseTokenVerifier()

    first = await verifier.verify("token-1")
    second = await verifier.verify("token-1")

    assert adapter.calls == 1
    assert first == second

    # A different token is verified independently.
    await verifier.verify("token-2")
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_verifier_cache_hit_returns_a_copy(monkeypatch) -> None:
    adapter = _CountingAdapter()
    monkeypatch.setattr(ftv_module, "get_firebase_admin_adapter", lambda: adapter)
    verifier = FirebaseTokenVerifier()

    first = await verifier.verify("token-1")
    first["email"] = "mutated@evil.example"
    second = await verifier.verify("token-1")
    assert second["email"] == "a@b.c"


@pytest.mark.asyncio
async def test_verifier_never_caches_failures(monkeypatch) -> None:
    adapter = _CountingAdapter(error=HTTPException(status_code=401, detail="Invalid"))
    monkeypatch.setattr(ftv_module, "get_firebase_admin_adapter", lambda: adapter)
    verifier = FirebaseTokenVerifier()

    for _ in range(2):
        with pytest.raises(HTTPException):
            await verifier.verify("bad-token")
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_verifier_cache_never_outlives_token_exp(monkeypatch) -> None:
    # Token expires in 1s: entry TTL is capped there, so after ~1s the
    # verifier must go back to Firebase (which would then reject it).
    adapter = _CountingAdapter(claims={"email": "a@b.c", "exp": time.time() - 0.1})
    monkeypatch.setattr(ftv_module, "get_firebase_admin_adapter", lambda: adapter)
    verifier = FirebaseTokenVerifier()

    await verifier.verify("expiring")  # adapter accepted it (fake), but exp is past
    await verifier.verify("expiring")
    assert adapter.calls == 2  # nothing was cached


# ---------------------------------------------------------------------------
# CachingAcademyLookup
# ---------------------------------------------------------------------------


class _CountingLookup:
    def __init__(self, slugs: dict[str, str], domains: dict[str, str]):
        self.slug_calls = 0
        self.domain_calls = 0
        self._slugs = slugs
        self._domains = domains

    async def find_by_slug(self, slug: str) -> str | None:
        self.slug_calls += 1
        return self._slugs.get(slug)

    async def find_by_domain(self, domain: str) -> str | None:
        self.domain_calls += 1
        return self._domains.get(domain)


@pytest.mark.asyncio
async def test_lookup_caches_positive_slug_and_domain_hits() -> None:
    inner = _CountingLookup({"acme": "AC-1"}, {"play.example.com": "AC-2"})
    lookup = CachingAcademyLookup(inner)

    assert await lookup.find_by_slug("acme") == "AC-1"
    assert await lookup.find_by_slug("acme") == "AC-1"
    assert inner.slug_calls == 1

    assert await lookup.find_by_domain("play.example.com") == "AC-2"
    assert await lookup.find_by_domain("play.example.com") == "AC-2"
    assert inner.domain_calls == 1


@pytest.mark.asyncio
async def test_lookup_never_caches_misses() -> None:
    inner = _CountingLookup({}, {})
    lookup = CachingAcademyLookup(inner)

    assert await lookup.find_by_slug("ghost") is None
    assert await lookup.find_by_slug("ghost") is None
    assert inner.slug_calls == 2  # a just-onboarded academy must route immediately

    # And once the academy appears, it is found without waiting for a TTL.
    inner._slugs["ghost"] = "AC-9"
    assert await lookup.find_by_slug("ghost") == "AC-9"


# ---------------------------------------------------------------------------
# Tenant servability checker caching (main.py wiring)
# ---------------------------------------------------------------------------


class _CountingLifecycle:
    def __init__(self) -> None:
        self.calls = 0

    async def get_tenant_health(self, academy_id: str):
        self.calls += 1
        return SimpleNamespace(servable=True, reason=None)


@pytest.mark.asyncio
async def test_servability_checker_caches_health_per_academy() -> None:
    lifecycle = _CountingLifecycle()
    app = SimpleNamespace(state=SimpleNamespace(saas_mode=True, tenant_lifecycle=lifecycle))

    check = _build_tenant_servability_checker(app)
    assert await check("AC-1") == (True, None)
    assert await check("AC-1") == (True, None)
    assert lifecycle.calls == 1

    assert await check("AC-2") == (True, None)
    assert lifecycle.calls == 2


@pytest.mark.asyncio
async def test_servability_checker_bypasses_cache_outside_saas_mode() -> None:
    lifecycle = _CountingLifecycle()
    app = SimpleNamespace(state=SimpleNamespace(saas_mode=False, tenant_lifecycle=lifecycle))

    check = _build_tenant_servability_checker(app)
    assert await check("AC-1") == (True, None)
    assert lifecycle.calls == 0
