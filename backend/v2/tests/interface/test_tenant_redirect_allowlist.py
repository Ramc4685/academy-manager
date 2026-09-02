"""Security test for the tenant-aware Stripe redirect allowlist.

Prod defect: a parent on ``https://blno-badminton.courtmastr.com`` reached
"Review & pay" and checkout died with ``redirect url origin not allowed`` —
the allowlist was built only from the static ``CORS_ORIGINS``/``FRONTEND_URL``
env vars, while tenants are resolved dynamically. Every newly onboarded academy
hit the same wall.

The fix widens the allowlist with the request's resolved tenant origins. The
tests that matter most here are the NEGATIVE ones: the raw Host header must
never be allowlisted, because with ``platform_base_domain`` unset the resolver
matches only the first Host label — so ``real-slug.attacker.example`` resolves
the real academy. Allowlisting that host verbatim would turn checkout into an
open-redirect / phishing primitive.
"""

from __future__ import annotations

from typing import ClassVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.security.redirect import InvalidRedirectUrl, validate_redirect_url
from backend.v2.shared.tenancy import current_tenant_origins
from backend.v2.shared.tenancy.origins import TenantOriginsResolver
from backend.v2.shared.tenancy.resolver import TenantResolutionError, TenantResolver

STATIC_ORIGINS = ("https://app.courtmastr.com",)
FRONTEND_URL = "https://app.courtmastr.com"


class _FakeLookup:
    """Mirrors the production resolver, INCLUDING its laxity: ``find_by_domain``
    matches an unverified ``custom_domain`` on the academy row."""

    SLUGS: ClassVar[dict[str, str]] = {
        "blno-badminton": "acad_blno",
        "tennis": "acad_tennis",
    }
    # Resolvable but NOT ownership-verified.
    UNVERIFIED_DOMAINS: ClassVar[dict[str, str]] = {"pending.example": "acad_blno"}

    async def find_by_slug(self, slug: str) -> str | None:
        return self.SLUGS.get(slug)

    async def find_by_domain(self, domain: str) -> str | None:
        return self.UNVERIFIED_DOMAINS.get(domain)

    async def exists(self, academy_id: str) -> bool:
        return academy_id in set(self.SLUGS.values())


class _FakeOriginLookup:
    """Adapter contract: only the stored slug and VERIFIED domains."""

    IDENTITIES: ClassVar[dict[str, tuple[str | None, tuple[str, ...]]]] = {
        "acad_blno": ("blno-badminton", ("badminton.example",)),
        "acad_tennis": ("tennis", ()),
    }

    async def routing_identity(self, academy_id: str) -> tuple[str | None, tuple[str, ...]]:
        return self.IDENTITIES.get(academy_id, (None, ()))


def _make_app(*, platform_base_domain: str | None = None, saas: bool = True) -> FastAPI:
    app = FastAPI()
    resolver = TenantResolver(
        lookup=_FakeLookup(),
        platform_base_domain=platform_base_domain,
    )
    origins_resolver = TenantOriginsResolver(_FakeOriginLookup(), frontend_url=FRONTEND_URL)

    async def _resolve_tenant(request: Request) -> str | None:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        try:
            result = await resolver.resolve(host=host, headers=dict(request.headers))
        except TenantResolutionError:
            return None
        return result.academy_id

    async def _load_origins(academy_id: str) -> tuple[str, ...]:
        return await origins_resolver.for_academy(academy_id)

    app.add_middleware(
        TenancyMiddleware,
        resolve_tenant=_resolve_tenant if saas else None,
        load_tenant_origins=_load_origins if saas else None,
    )

    @app.get("/checkout")
    async def checkout(request: Request, url: str) -> JSONResponse:
        """Stands in for the parent checkout composition closure."""
        allowed = (*STATIC_ORIGINS, *current_tenant_origins())
        try:
            validate_redirect_url(url, allowed_origins=allowed)
        except InvalidRedirectUrl as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "ok": True,
                "academy_id": request.state.resolved_academy_id,
                "tenant_origins": list(request.state.tenant_origins),
            }
        )

    return app


# ---------------------------------------------------------------------------
# The prod defect: the tenant's own host is now accepted
# ---------------------------------------------------------------------------


def test_tenant_subdomain_host_can_check_out_on_its_own_origin() -> None:
    client = TestClient(_make_app(), base_url="https://blno-badminton.courtmastr.com")
    r = client.get("/checkout", params={"url": "https://blno-badminton.courtmastr.com/pay/done"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["academy_id"] == "acad_blno"
    assert body["tenant_origins"] == [
        "https://blno-badminton.courtmastr.com",
        "https://badminton.example",
    ]


def test_verified_custom_domain_origin_is_accepted() -> None:
    client = TestClient(_make_app(), base_url="https://blno-badminton.courtmastr.com")
    r = client.get("/checkout", params={"url": "https://badminton.example/pay/done"})
    assert r.status_code == 200, r.text


def test_static_configured_origin_still_works() -> None:
    client = TestClient(_make_app(), base_url="https://blno-badminton.courtmastr.com")
    r = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay/done"})
    assert r.status_code == 200, r.text


def test_static_origin_still_works_when_no_tenant_resolves() -> None:
    client = TestClient(_make_app(), base_url="https://unknown-host.example")
    r = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay/done"})
    assert r.status_code == 200, r.text
    assert r.json()["academy_id"] is None


# ---------------------------------------------------------------------------
# Security: the raw Host is never allowlisted
# ---------------------------------------------------------------------------


def test_attacker_host_resolves_tenant_but_is_not_allowlisted() -> None:
    """With ``platform_base_domain`` unset the resolver matches the first label
    only, so this Host DOES resolve acad_blno. The allowlist must still refuse
    the attacker's origin — resolved_host is not a trusted value."""
    client = TestClient(_make_app(), base_url="https://blno-badminton.attacker.example")
    ok = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay/done"})
    assert ok.status_code == 200
    assert ok.json()["academy_id"] == "acad_blno"  # tenant did resolve

    r = client.get("/checkout", params={"url": "https://blno-badminton.attacker.example/pay"})
    assert r.status_code == 400
    assert "origin not allowed" in r.json()["error"]


def test_attacker_apex_origin_is_rejected() -> None:
    client = TestClient(_make_app(), base_url="https://blno-badminton.attacker.example")
    r = client.get("/checkout", params={"url": "https://attacker.example/pay"})
    assert r.status_code == 400


def test_x_forwarded_host_cannot_smuggle_an_origin() -> None:
    client = TestClient(_make_app(), base_url="https://app.courtmastr.com")
    r = client.get(
        "/checkout",
        params={"url": "https://blno-badminton.evil.example/pay"},
        headers={"x-forwarded-host": "blno-badminton.evil.example"},
    )
    assert r.status_code == 400


def test_unverified_custom_domain_resolves_but_is_not_allowlisted() -> None:
    """Deliberately accepted residual: ``find_by_domain`` matches an unverified
    ``custom_domain``, but the origin builder reads verified rows only, so this
    host keeps failing checkout exactly as it does today (no regression)."""
    client = TestClient(_make_app(), base_url="https://pending.example")
    ok = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay"})
    assert ok.json()["academy_id"] == "acad_blno"
    r = client.get("/checkout", params={"url": "https://pending.example/pay"})
    assert r.status_code == 400


def test_tenant_a_host_never_allowlists_tenant_b_origin() -> None:
    client = TestClient(_make_app(), base_url="https://tennis.courtmastr.com")
    ok = client.get("/checkout", params={"url": "https://tennis.courtmastr.com/pay"})
    assert ok.status_code == 200
    assert ok.json()["academy_id"] == "acad_tennis"

    r = client.get("/checkout", params={"url": "https://blno-badminton.courtmastr.com/pay"})
    assert r.status_code == 400


def test_scheme_downgrade_is_rejected() -> None:
    """``x-forwarded-proto`` is unauthenticated at the backend edge; scheme comes
    from frontend_url, so the http:// variant of the tenant host is not allowed."""
    client = TestClient(_make_app(), base_url="https://blno-badminton.courtmastr.com")
    r = client.get(
        "/checkout",
        params={"url": "http://blno-badminton.courtmastr.com/pay"},
        headers={"x-forwarded-proto": "http"},
    )
    assert r.status_code == 400


def test_platform_base_domain_configured_blocks_the_lookalike_entirely() -> None:
    app = _make_app(platform_base_domain="courtmastr.com")
    client = TestClient(app, base_url="https://blno-badminton.attacker.example")
    r = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay"})
    assert r.json()["academy_id"] is None
    assert r.json()["tenant_origins"] == []


# ---------------------------------------------------------------------------
# Non-SaaS deployments are untouched
# ---------------------------------------------------------------------------


def test_non_saas_mode_has_no_tenant_origins() -> None:
    client = TestClient(_make_app(saas=False), base_url="https://blno-badminton.courtmastr.com")
    r = client.get("/checkout", params={"url": "https://app.courtmastr.com/pay"})
    assert r.status_code == 200
    assert r.json()["tenant_origins"] == []
    denied = client.get("/checkout", params={"url": "https://blno-badminton.courtmastr.com/pay"})
    assert denied.status_code == 400
