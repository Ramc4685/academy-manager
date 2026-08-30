"""Caching decorator for ``AcademyLookupPort`` (issue #527).

Tenant routing (slug/domain -> academy_id) is read on every request by
``TenantResolver`` and changes only when an academy is onboarded or its
domains are edited — yet it used to cost 1-2 Mongo queries per request.

Positive results are cached for a short TTL. Misses are deliberately NOT
cached: a just-bootstrapped academy must become routable immediately, and a
genuinely unknown host is the rare error path, not the hot path.
"""

from __future__ import annotations

from backend.v2.shared.caching import TTLCache
from backend.v2.shared.tenancy.resolver import AcademyLookupPort

_DEFAULT_TTL_SECONDS = 60.0


class CachingAcademyLookup:
    """Wrap an ``AcademyLookupPort`` with a per-process TTL cache."""

    def __init__(
        self,
        inner: AcademyLookupPort,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache: TTLCache[str] = TTLCache(ttl_seconds=ttl_seconds)

    async def find_by_slug(self, slug: str) -> str | None:
        cached = self._cache.get(f"slug:{slug}")
        if cached is not None:
            return cached
        academy_id = await self._inner.find_by_slug(slug)
        if academy_id is not None:
            self._cache.set(f"slug:{slug}", academy_id)
        return academy_id

    async def find_by_domain(self, domain: str) -> str | None:
        cached = self._cache.get(f"domain:{domain}")
        if cached is not None:
            return cached
        academy_id = await self._inner.find_by_domain(domain)
        if academy_id is not None:
            self._cache.set(f"domain:{domain}", academy_id)
        return academy_id
