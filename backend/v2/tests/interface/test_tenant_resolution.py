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

    async def exists(self, academy_id: str) -> bool:
        registered = set(self.SLUGS.values()) | set(self.DOMAINS.values())
        registered.add("academy-internal-job")
        return academy_id in registered


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(
    *,
    allowed_internal_header: str | None = None,
    internal_header_secret: str | None = None,
) -> FastAPI:
    """Build a minimal FastAPI app with one test route that runs the resolver."""
    app = FastAPI()
    resolver = TenantResolver(
        lookup=_FakeLookup(),
        allowed_internal_header=allowed_internal_header,
        internal_header_secret=internal_header_secret,
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
        _make_app(
            allowed_internal_header="X-Internal-Academy-Id",
            internal_header_secret="proxy-secret",
        ),
        base_url="http://unknown.internal.example.com",
    )
    r = client.get(
        "/resolve",
        headers={
            "X-Internal-Academy-Id": "academy-internal-job",
            "x-cm-proxy-auth": "proxy-secret",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["academy_id"] == "academy-internal-job"
    assert body["source"] == TenantSource.INTERNAL_HEADER.value


def test_internal_header_rejected_without_proxy_secret_through_http() -> None:
    """SECURITY (#519): the bare header (no x-cm-proxy-auth) must not resolve."""
    client = TestClient(
        _make_app(
            allowed_internal_header="X-Internal-Academy-Id",
            internal_header_secret="proxy-secret",
        ),
        base_url="http://unknown.internal.example.com",
    )
    r = client.get(
        "/resolve",
        headers={"X-Internal-Academy-Id": "academy-internal-job"},
    )
    assert r.status_code == 422


def test_internal_header_rejected_for_unregistered_academy_through_http() -> None:
    """SECURITY (#519): a fabricated academy_id must not resolve."""
    client = TestClient(
        _make_app(
            allowed_internal_header="X-Internal-Academy-Id",
            internal_header_secret="proxy-secret",
        ),
        base_url="http://unknown.internal.example.com",
    )
    r = client.get(
        "/resolve",
        headers={
            "X-Internal-Academy-Id": "academy-fabricated",
            "x-cm-proxy-auth": "proxy-secret",
        },
    )
    assert r.status_code == 422


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
from backend.v2.main import _build_request_tenant_resolver
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.config.settings import get_settings
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


def _make_resolver_callable(
    allowed_internal_header: str | None = None,
    internal_header_secret: str | None = None,
):
    """Return an async callable that resolves tenant from a Starlette request.

    Mirrors what TenancyMiddleware will use in production.
    """
    resolver = TenantResolver(
        lookup=_FakeLookup(),
        allowed_internal_header=allowed_internal_header,
        internal_header_secret=internal_header_secret,
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
    internal_header_secret: str | None = None,
    status_checker=None,
) -> FastAPI:
    """Build a tiny app with TenancyMiddleware + one auth-required route."""
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(
        TenancyMiddleware,
        load_auth_claims=loader,
        resolve_tenant=_make_resolver_callable(allowed_internal_header, internal_header_secret),
        check_tenant_servable=status_checker,
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

    @app.get("/api/v2/platform/public")
    async def platform_public() -> dict:
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


def test_middleware_accepts_bff_auth_bridge_header() -> None:
    """The Cloudflare BFF may forward Firebase tokens outside Authorization."""
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
    r = client.get("/whoami", headers={"X-CourtMastr-Auth": "Bearer u-coach"})

    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "u-coach"
    assert loader.calls == [{"id_token": "u-coach", "resolved_academy_id": "academy-court"}]


def test_middleware_accepts_bff_identity_bridge_header() -> None:
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
    r = client.get("/whoami", headers={"X-CourtMastr-Identity": "Bearer u-coach"})

    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "u-coach"
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


def test_401_carries_the_swallowed_auth_failure_reason() -> None:
    """The middleware's swallowed DomainError code reaches the 401 body (#425).

    Without this the login surface cannot tell a missing membership from a
    bad token, and the parent just bounces to a blank form.
    """
    loader = _RecordingLoader(memberships={})  # every user hits MembershipNotFound
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})

    assert r.status_code == 401
    error = r.json()["error"]
    assert error["code"] == "Auth.NotAuthenticated"
    assert error["details"] == {"reason": "Identity.MembershipNotFound"}


def test_401_reason_marks_an_unresolvable_tenant() -> None:
    """A token with no resolvable tenant is distinguishable from a bad token."""
    loader = _RecordingLoader(memberships={})
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://ghost.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})

    assert r.status_code == 401
    assert r.json()["error"]["details"] == {"reason": "Auth.TenantUnresolved"}
    assert loader.calls == []


def test_401_has_no_reason_when_no_token_was_sent() -> None:
    """A plain unauthenticated request carries no diagnostic reason."""
    loader = _RecordingLoader(memberships={})
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami")

    assert r.status_code == 401
    error = r.json()["error"]
    assert error["code"] == "Auth.NotAuthenticated"
    assert error["details"] == {}


def test_401_reason_never_leaks_the_underlying_message() -> None:
    """Only the machine-readable code crosses the boundary — the raised
    message embeds a user id and must not reach the client."""
    loader = _RecordingLoader(memberships={})
    app = _make_middleware_app(loader=loader)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})

    assert "u-coach" not in r.text


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
    app = _make_middleware_app(
        loader=loader,
        allowed_internal_header="X-Internal-Academy-Id",
        internal_header_secret="proxy-secret",
    )
    client = TestClient(app, base_url="http://unknown.internal.example.com")
    r = client.get(
        "/whoami",
        headers={
            "Authorization": "Bearer u-coach",
            "X-Internal-Academy-Id": "academy-internal-job",
            "x-cm-proxy-auth": "proxy-secret",
        },
    )
    assert r.status_code == 200
    assert r.json()["academy_id"] == "academy-internal-job"
    assert loader.calls[-1]["resolved_academy_id"] == "academy-internal-job"


def test_main_resolver_prefers_forwarded_host_for_frontend_proxy() -> None:
    class _RecordingTenantResolver:
        def __init__(self) -> None:
            self.hosts: list[str] = []

        async def resolve(self, *, host: str, headers: dict[str, str]):
            self.hosts.append(host)

            class _Result:
                academy_id = "academy-court"

            return _Result()

    tenant_resolver = _RecordingTenantResolver()
    app = FastAPI()
    app.state.saas_mode = True
    app.state.default_academy_id = None
    app.state.tenant_resolver = tenant_resolver
    resolve_tenant = _build_request_tenant_resolver(app)

    @app.get("/resolve")
    async def resolve(request: Request) -> dict[str, str | None]:
        return {"academy_id": await resolve_tenant(request)}

    client = TestClient(app, base_url="http://backend:8001")
    response = client.get(
        "/resolve",
        headers={"X-Forwarded-Host": "courtmastr.app.example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"academy_id": "academy-court"}
    assert tenant_resolver.hosts == ["courtmastr.app.example.com"]


def test_main_resolver_uses_primary_academy_in_single_academy_launch_mode() -> None:
    app = FastAPI()
    app.state.saas_mode = False
    app.state.tenancy_mode = "single_academy"
    app.state.primary_academy_id = "acad_blno_badminton"
    app.state.default_academy_id = "default-academy"
    app.state.tenant_resolver = None
    resolve_tenant = _build_request_tenant_resolver(app)

    @app.get("/resolve")
    async def resolve(request: Request) -> dict[str, str | None]:
        return {"academy_id": await resolve_tenant(request)}

    client = TestClient(app, base_url="http://api.academy.courtmastr.com")
    response = client.get("/resolve")

    assert response.status_code == 200
    assert response.json() == {"academy_id": "acad_blno_badminton"}


def test_main_resolver_keeps_default_only_for_legacy_multi_academy_mode() -> None:
    app = FastAPI()
    app.state.saas_mode = False
    app.state.tenancy_mode = "multi_academy"
    app.state.primary_academy_id = None
    app.state.default_academy_id = "default-academy"
    app.state.tenant_resolver = None
    resolve_tenant = _build_request_tenant_resolver(app)

    @app.get("/resolve")
    async def resolve(request: Request) -> dict[str, str | None]:
        return {"academy_id": await resolve_tenant(request)}

    client = TestClient(app, base_url="http://api.local")
    response = client.get("/resolve")

    assert response.status_code == 200
    assert response.json() == {"academy_id": "default-academy"}


def test_middleware_blocks_inactive_tenant_before_auth_loader() -> None:
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-court"): {
                "membership_id": "m-coach-court",
                "roles": ("coach",),
            }
        },
    )

    async def _inactive_status(_: str) -> tuple[bool, str | None]:
        return False, "tenant_status_suspended"

    app = _make_middleware_app(loader=loader, status_checker=_inactive_status)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})

    assert r.status_code == 423
    assert r.json()["error"]["code"] == "Platform.TenantNotServable"
    assert r.json()["error"]["details"] == {
        "academy_id": "academy-court",
        "reason": "tenant_status_suspended",
    }
    assert loader.calls == []


def test_middleware_blocks_suspended_tenant_resolved_via_internal_header() -> None:
    """SECURITY parity (#519): resolver.exists() deliberately does not check
    academy lifecycle — the servable check downstream must still 423 a
    suspended academy even when the tenant came from the internal header."""
    loader = _RecordingLoader(
        memberships={
            ("u-coach", "academy-internal-job"): {
                "membership_id": "m-internal",
                "roles": ("admin",),
            }
        },
    )

    async def _inactive_status(_: str) -> tuple[bool, str | None]:
        return False, "tenant_status_suspended"

    app = _make_middleware_app(
        loader=loader,
        allowed_internal_header="X-Internal-Academy-Id",
        internal_header_secret="proxy-secret",
        status_checker=_inactive_status,
    )
    client = TestClient(app, base_url="http://unknown.internal.example.com")
    r = client.get(
        "/whoami",
        headers={
            "Authorization": "Bearer u-coach",
            "X-Internal-Academy-Id": "academy-internal-job",
            "x-cm-proxy-auth": "proxy-secret",
        },
    )

    assert r.status_code == 423
    assert r.json()["error"]["code"] == "Platform.TenantNotServable"
    assert r.json()["error"]["details"] == {
        "academy_id": "academy-internal-job",
        "reason": "tenant_status_suspended",
    }
    assert loader.calls == []


def test_middleware_allows_platform_routes_to_inspect_inactive_tenant() -> None:
    loader = _RecordingLoader(memberships={})

    async def _inactive_status(_: str) -> tuple[bool, str | None]:
        return False, "tenant_status_suspended"

    app = _make_middleware_app(loader=loader, status_checker=_inactive_status)
    client = TestClient(app, base_url="http://courtmastr.app.example.com")
    r = client.get("/api/v2/platform/public")

    assert r.status_code == 200
    assert r.json() == {"ok": True, "tenant_context": None}


def test_middleware_single_academy_mode_rejects_other_resolved_tenant(monkeypatch) -> None:
    monkeypatch.setenv("APP_TENANCY_MODE", "single_academy")
    monkeypatch.setenv("PRIMARY_ACADEMY_ID", "academy-court")
    get_settings.cache_clear()
    try:
        loader = _RecordingLoader(
            memberships={
                ("u-coach", "academy-tennis"): {
                    "membership_id": "m-coach-tennis",
                    "roles": ("coach",),
                }
            },
        )
        app = _make_middleware_app(loader=loader)
        client = TestClient(app, base_url="http://tennis.example.com")

        r = client.get("/whoami", headers={"Authorization": "Bearer u-coach"})

        assert r.status_code == 403
        assert r.json()["error"]["code"] == "Platform.TenantForbidden"
        assert loader.calls == []
    finally:
        get_settings.cache_clear()


def test_middleware_single_academy_non_saas_launch_env_uses_primary_tenant(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb://prod")
    monkeypatch.setenv("DB_NAME", "academy_prod")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("V2_STRIPE_USE_FAKE_GATEWAY", "false")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("APP_TENANCY_MODE", "single_academy")
    monkeypatch.setenv("PRIMARY_ACADEMY_ID", "acad_blno_badminton")
    monkeypatch.setenv("ENABLE_PLATFORM_ROUTES", "false")
    monkeypatch.delenv("V2_SAAS_MODE", raising=False)
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        loader = _RecordingLoader(
            memberships={
                ("u-admin", "acad_blno_badminton"): {
                    "membership_id": "m-admin-blno",
                    "roles": ("admin",),
                }
            },
        )
        app = FastAPI()
        register_exception_handlers(app)
        app.state.saas_mode = False
        app.state.tenancy_mode = "single_academy"
        app.state.primary_academy_id = "acad_blno_badminton"
        app.state.default_academy_id = "default-academy"
        app.state.tenant_resolver = None
        app.add_middleware(
            TenancyMiddleware,
            load_auth_claims=loader,
            resolve_tenant=_build_request_tenant_resolver(app),
        )

        @app.get("/whoami")
        async def whoami(claims: AuthClaims = Depends(get_auth_claims)) -> dict[str, str]:
            return {"academy_id": claims.academy_id}

        client = TestClient(app, base_url="http://api.academy.courtmastr.com")
        response = client.get("/whoami", headers={"Authorization": "Bearer u-admin"})

        assert response.status_code == 200, response.text
        assert response.json() == {"academy_id": "acad_blno_badminton"}
        assert loader.calls == [
            {"id_token": "u-admin", "resolved_academy_id": "acad_blno_badminton"}
        ]
    finally:
        get_settings.cache_clear()
