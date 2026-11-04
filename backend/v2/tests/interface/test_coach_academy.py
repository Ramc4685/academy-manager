"""Interface tests for GET /api/v2/coach/academy (row 14).

Covers happy path, wrong-persona 404 (security matrix), unauthenticated
401 (via the normal `require_coach_surface` gate), and tenant scoping — the
route must resolve from `AuthClaims.academy_id` (the request academy), never
a value baked in at composition time.
"""

from __future__ import annotations

from dataclasses import replace

from backend.v2.tests.interface.conftest import _build_use_cases, _coach_claims, _make_app


def _client_with_academy_info(seed, academies: dict[str, dict[str, object]]):
    use_cases = _build_use_cases(seed)

    async def get_academy_info(*, academy_id: str):
        return academies.get(academy_id, {"name": "Academy", "logo_url": None, "brand_color": None})

    use_cases = replace(use_cases, get_academy_info=get_academy_info)
    app = _make_app(_coach_claims(), use_cases)
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_coach_academy_happy_path(seed):
    client = _client_with_academy_info(
        seed,
        {
            "test-academy": {
                "name": "Riverside Shuttle Club",
                "logo_url": "https://cdn.example.com/logo.png",
                "brand_color": "#2563eb",
            }
        },
    )
    r = client.get("/api/v2/coach/academy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "name": "Riverside Shuttle Club",
        "logo_url": "https://cdn.example.com/logo.png",
        "brand_color": "#2563eb",
    }


def test_coach_academy_is_scoped_to_the_request_academy(seed):
    """A coach in "test-academy" must never see another tenant's brand, even
    if the composed lookup were somehow handed the wrong id."""
    client = _client_with_academy_info(
        seed,
        {
            "test-academy": {"name": "Test Academy", "logo_url": None, "brand_color": None},
            "other-academy": {
                "name": "Other Academy",
                "logo_url": "https://cdn.example.com/other.png",
                "brand_color": "#ff0000",
            },
        },
    )
    r = client.get("/api/v2/coach/academy")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Test Academy"


def test_coach_academy_wrong_persona_is_gated(parent_client):
    """Security matrix: a parent token must not reach the coach BFF."""
    r = parent_client.get("/api/v2/coach/academy")
    assert r.status_code == 404, r.text


def test_coach_academy_unauthenticated(seed):
    """No claims dependency override at all -> the gate must still refuse."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.v2.interfaces.coach.router import router as coach_router
    from backend.v2.shared.http import register_exception_handlers

    use_cases = _build_use_cases(seed)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    from backend.v2.interfaces.coach.deps import get_coach_use_cases

    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/academy")
        assert r.status_code in (401, 403), r.text
