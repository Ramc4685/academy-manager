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

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.v2.shared.tenancy.resolver import (
    AcademyLookupPort,
    TenantResolutionError,
    TenantResolver,
    TenantSource,
)


# ---------------------------------------------------------------------------
# In-memory lookup used by all interface tests
# ---------------------------------------------------------------------------


class _FakeLookup:
    SLUGS = {
        "courtmastr": "academy-court",
        "tennis": "academy-tennis",
    }
    DOMAINS = {
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
