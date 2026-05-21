"""Interface-level tests for TenantResolver wired into a FastAPI endpoint.

These tests mount a minimal route that calls TenantResolver directly and
verifies the full HTTP → resolver → result (or error) cycle. No Mongo,
no auth middleware — only the resolver logic and HTTP plumbing.

Wiring note for future middleware integration:
  TenancyMiddleware should call TenantResolver before token verification
  once AuthClaims is extended to carry membership_id (Agent A's work).
  The resolver instance should be constructed from Settings and an
  AcademyLookupPort backed by the Mongo identity infrastructure.
"""

from __future__ import annotations

from typing import ClassVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.v2.shared.tenancy.resolver import (
    TenantResolutionError,
    TenantResolver,
    TenantSource,
)

# ---------------------------------------------------------------------------
# In-memory lookup used by all interface tests
# ---------------------------------------------------------------------------


class _FakeLookup:
    SLUGS: ClassVar[dict[str, str]] = {
        "courtmastr": "academy-court",
        "tennis": "academy-tennis",
    }
    DOMAINS: ClassVar[dict[str, str]] = {
        "badminton-club.com": "academy-badminton",
    }

    async def find_by_slug(self, slug: str) -> str | None:
        return self.SLUGS.get(slug)

    async def find_by_domain(self, domain: str) -> str | None:
        return self.DOMAINS.get(domain)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(*, allowed_internal_header: str | None = None) -> FastAPI:
    """Build a minimal FastAPI app with one test route that runs the resolver."""
    app = FastAPI()
    resolver = TenantResolver(
        lookup=_FakeLookup(),
        allowed_internal_header=allowed_internal_header,
    )

    @app.get("/resolve")
    async def resolve_endpoint(request: Request) -> JSONResponse:
        host = request.headers.get("host", "")
        headers = dict(request.headers)
        try:
            result = await resolver.resolve(host=host, headers=headers)
            return JSONResponse(
                {
                    "academy_id": result.academy_id,
                    "source": result.source.value,
                    "resolved_host": result.resolved_host,
                }
            )
        except TenantResolutionError as exc:
            return JSONResponse({"error": exc.reason}, status_code=422)

    return app


# ---------------------------------------------------------------------------
# Tests: subdomain
# ---------------------------------------------------------------------------


def test_subdomain_resolution_through_http() -> None:
    client = TestClient(_make_app(), base_url="http://courtmastr.app.example.com")
    r = client.get("/resolve")
    assert r.status_code == 200
    body = r.json()
    assert body["academy_id"] == "academy-court"
    assert body["source"] == TenantSource.SUBDOMAIN.value


def test_second_subdomain_resolves() -> None:
    client = TestClient(_make_app(), base_url="http://tennis.example.com")
    r = client.get("/resolve")
    assert r.status_code == 200
    assert r.json()["academy_id"] == "academy-tennis"


# ---------------------------------------------------------------------------
# Tests: custom domain
# ---------------------------------------------------------------------------


def test_custom_domain_resolution_through_http() -> None:
    client = TestClient(_make_app(), base_url="http://badminton-club.com")
    r = client.get("/resolve")
    assert r.status_code == 200
    body = r.json()
    assert body["academy_id"] == "academy-badminton"
    assert body["source"] == TenantSource.CUSTOM_DOMAIN.value


# ---------------------------------------------------------------------------
# Tests: internal header
# ---------------------------------------------------------------------------


def test_internal_header_resolves_when_configured_through_http() -> None:
    client = TestClient(
        _make_app(allowed_internal_header="X-Internal-Academy-Id"),
        base_url="http://unknown.internal.example.com",
    )
    r = client.get(
        "/resolve",
        headers={"X-Internal-Academy-Id": "academy-internal-job"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["academy_id"] == "academy-internal-job"
    assert body["source"] == TenantSource.INTERNAL_HEADER.value


def test_internal_header_not_accepted_when_header_not_configured() -> None:
    client = TestClient(
        _make_app(allowed_internal_header=None),
        base_url="http://unknown.example.com",
    )
    r = client.get(
        "/resolve",
        headers={"X-Internal-Academy-Id": "academy-attempt"},
    )
    assert r.status_code == 422
    assert "error" in r.json()


# ---------------------------------------------------------------------------
# Tests: unknown tenant rejection
# ---------------------------------------------------------------------------


def test_unknown_tenant_returns_422_through_http() -> None:
    client = TestClient(_make_app(), base_url="http://ghost.example.com")
    r = client.get("/resolve")
    assert r.status_code == 422
    body = r.json()
    assert "error" in body


# ---------------------------------------------------------------------------
# Tests: user-only request has no tenant
# ---------------------------------------------------------------------------


def test_user_only_headers_do_not_resolve_tenant() -> None:
    """Authorization/user headers alone must not produce a tenant."""
    client = TestClient(_make_app(), base_url="http://unknown.example.com")
    r = client.get(
        "/resolve",
        headers={
            "Authorization": "Bearer fake-token",
            "X-User-Id": "user-999",
        },
    )
    assert r.status_code == 422


# ===========================================================================
# Middleware integration tests
#
# These tests mount TenancyMiddleware with a fake TenantResolver and a fake
# LoadAuthClaims to prove the middleware:
#   * resolves tenant from the request BEFORE building claims
#   * passes resolved_academy_id into the load-claims call
#   * sets request.state.auth_claims (incl. membership_id)
#   * sets and resets the tenant ContextVar
#   * rejects when the user has no membership for the resolved tenant
#   * never falls back to default_academy_id
# ===========================================================================


from backend.v2.contexts.identity.domain.errors import MembershipNotFound
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant_var


class _RecordingLoader:
    """Fake LoadAuthClaims used by the middleware.

    Records the resolved_academy_id passed by the middleware so tests can
    assert the middleware resolved tenant BEFORE calling the loader.
    """

    def __init__(
        self,
        *,
        memberships: dict[tuple[str, str], dict] | None = None,
        platform_roles: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        # key = (user_id_from_token, academy_id)
        self._memberships = memberships or {}
        self._platform_roles = platform_roles or {}
        self.calls: list[dict[str, str]] = []

    async def __call__(self, id_token: str, *, resolved_academy_id: str) -> AuthClaims:
        # Pretend the token decodes to user "u-coach" (single test user)
        user_id = id_token  # tests pass the user_id as the token string
        self.calls.append({"id_token": id_token, "resolved_academy_id": resolved_academy_id})
        key = (user_id, resolved_academy_id)
        membership = self._memberships.get(key)
        if membership is None:
            raise MembershipNotFound(
                f"user {user_id} has no active membership in {resolved_academy_id}"
            )
        return AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.com",
            academy_id=resolved_academy_id,
            membership_id=membership["membership_id"],
            roles=tuple(membership.get("roles", ())),
            platform_roles=tuple(self._platform_roles.get(user_id, ())),
        )


def _make_resolver_callable(allowed_internal_header: str | None = None):
    """Return an async callable that resolves tenant from a Starlette request.

    Mirrors what TenancyMiddleware will use in production.
    """
    resolver = TenantResolver(
        lookup=_FakeLookup(),
        allowed_internal_header=allowed_internal_header,
    )

    async def _resolve(request) -> str | None:
        host = request.headers.get("host", "")
        headers = dict(request.headers)
        try:
            result = await resolver.resolve(host=host, headers=headers)
            return result.academy_id
        except TenantResolutionError:
            return None

    return _resolve


def _make_middleware_app(
    *,
    loader: _RecordingLoader,
    allowed_internal_header: str | None = None,
) -> FastAPI:
    """Build a tiny app with TenancyMiddleware + one auth-required route."""
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(
        TenancyMiddleware,
        load_auth_claims=loader,
        resolve_tenant=_make_resolver_callable(allowed_internal_header),
    )

    @app.get("/whoami")
    async def whoami(claims: AuthClaims = Depends(get_auth_claims)) -> dict:
        return {
            "user_id": claims.user_id,
            "academy_id": claims.academy_id,
            "membership_id": claims.membership_id,
            "roles": list(claims.roles),
            "platform_roles": list(claims.platform_roles),
            # Echo the ContextVar so we can assert it was set during the request.
            "tenant_context": _tenant_var.get(),
        }

    @app.get("/public")
    async def public() -> dict:
        return {"ok": True, "tenant_context": _tenant_var.get()}

    return app


# Late import so the symbol is available when _make_middleware_app runs.
from fastapi import Depends


def test_middleware_resolves_tenant_then_builds_claims() -> None:
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-court"): {
                "membership_id": "m-coach-court",
                "roles": ("coach",),
            }
        },
    )
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "u-coach"
    assert body["academy_id"] == "academy-court"
    assert body["membership_id"] == "m-coach-court"
    assert body["roles"] == ["coach"]
    assert body["tenant_context"] == "academy-court"

    # And the middleware MUST have passed the resolved academy_id into the
    # loader — proving tenant resolution happened before claims construction.
    assert loader.calls == [{"id_token": "u-coach", "resolved_academy_id": "academy-court"}]


def test_middleware_includes_platform_roles_separately() -> None:
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-court"): {
                "membership_id": "m-coach-court",
                "roles": ("coach",),
            }
        },
        platform_roles={"u-coach": ("platform_admin",)},
    )
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    assert r.status_code == 200
    body = r.json()
    assert body["roles"] == ["coach"]
    assert body["platform_roles"] == ["platform_admin"]


def test_middleware_rejects_when_membership_missing_on_protected_route() -> None:
    """Authenticated user without a membership for the resolved tenant → 401."""
    loader = _RecordingLoader(memberships={})  # no membership for anyone
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    # No claims attached → Depends(get_auth_claims) raises 401.
    assert r.status_code == 401


def test_middleware_does_not_set_claims_when_tenant_unresolved() -> None:
    """Unknown host → no tenant → no claims attached and no fallback used."""
    loader = _RecordingLoader(
        memberships={
            # Even if a default academy *did* have a membership, the middleware
            # must never reach this row because the host did not resolve.
            ("u-coach", "default-academy"): {
                "membership_id": "m-default",
                "roles": ("admin",),
            }
        },
    )
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://ghost.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    assert r.status_code == 401
    # Loader must NOT have been called — tenant resolution failed first.
    assert loader.calls == []


def test_middleware_lets_public_routes_pass_without_tenant() -> None:
    """Unauthenticated public routes still flow even when tenant is unknown."""
    loader = _RecordingLoader(memberships={})
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://ghost.example.com")
    r = client.get("/public")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "tenant_context": None}


def test_tenant_context_resets_after_request() -> None:
    """ContextVar must be cleared once the request finishes."""
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-court"): {
                "membership_id": "m-coach-court",
                "roles": ("coach",),
            }
        },
    )
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")

    # ContextVar should start unset.
    assert _tenant_var.get() is None
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    assert r.status_code == 200
    # And remain unset between requests.
    assert _tenant_var.get() is None


def test_middleware_never_uses_default_academy_id() -> None:
    """Even if a default-academy membership exists, an unresolved tenant
    must not be substituted with a default. The loader proves the middleware
    never invented an academy_id."""
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "default-academy"): {
                "membership_id": "m-fallback",
                "roles": ("admin",),
            }
        },
    )
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://ghost.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})
    assert r.status_code == 401
    # The middleware must NOT have asked the loader to load claims at all.
    assert loader.calls == []


def test_middleware_uses_internal_header_when_configured() -> None:
    """Internal-header resolution still flows through TenancyMiddleware."""
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-internal-job"): {
                "membership_id": "m-internal",
                "roles": ("admin",),
            }
        },
    )
    app = _make_middleware_app(loader=loader, allowed_internal_header="X-Internal-Academy-Id")
    client = TestClient(app, base_url="http://unknown.internal.example.com")
    r = client.get(
        "/whoami",
        headers={
            "Authorization": "Bearer u-coach",
            "X-Internal-Academy-Id": "academy-internal-job",
        },
    )
    assert r.status_code == 200
    assert r.json()["academy_id"] == "academy-internal-job"
    assert loader.calls[-1]["resolved_academy_id"] == "academy-internal-job"
