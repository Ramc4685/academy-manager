"""``GET /api/v2/public/academy`` over HTTP (public tenant page, Lane B2).

Real route, real composition, real Mongo repositories on mongomock, and the
real ``TenancyMiddleware`` resolving the tenant from the Host header, as in
production. The caller never names an academy.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id
from backend.v2.main import _build_request_tenant_resolver
from backend.v2.tests.fixtures.public_page import (
    ACADEMY,
    RIVERSIDE_HOST,
    SECRETS,
    build_app,
    seed,
)

URL = "/api/v2/public/academy"


def _db(*, published: bool = True) -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["public-page"]
    asyncio.run(seed(db, published=published))
    return db


def _get(app: Any, host: str = RIVERSIDE_HOST, **params: Any) -> Any:
    return TestClient(app).get(URL, headers={"host": host}, params=params)


def test_published_page_lists_only_published_listable_classes() -> None:
    response = _get(build_app(_db()))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["vary"] == "Host"
    body = response.json()
    assert body["state"] == "published"

    academy = body["academy"]
    assert academy["name"] == "Riverside Shuttle Club"
    assert academy["brand_color"] == "#0f766e"
    assert academy["brand_fill"] == "#0f766e"
    assert academy["brand_on_color"] == "#ffffff"
    assert academy["venue"] == {
        "address": "1 River Road, Riverside",
        "hours_text": "Sat 9am to 1pm",
    }
    assert academy["currency"] == "USD"
    assert body["page"] == {
        "trials_open": True,
        "show_price": True,
        "show_availability": True,
        "price_period_default": "month",
        "privacy_notice_url": None,
        "theme": "floodlit",
        "seats_left_threshold": 3,
        "terms_url": None,
        "refund_policy_url": None,
    }

    [juniors] = body["programs"]
    assert juniors["name"] == "Juniors"
    assert [c["title"] for c in juniors["classes"]] == ["Class jr-sat", "Class jr-full"]
    saturday, full = juniors["classes"]
    assert saturday["public_id"] == public_class_id(ACADEMY, "sess-jr-sat")
    assert saturday["coach_name"] == "Alex Morgan"
    assert saturday["price"] == {"amount_cents": 9000, "period": "month"}
    assert saturday["seats"] == {"band": "open", "seats_left": None}
    assert saturday["level"] == "Beginner"
    assert saturday["age_band"] == {"min_age": 6, "max_age": 9}
    assert saturday["days_of_week"] == ["Sat"]
    assert (saturday["start_time"], saturday["end_time"]) == ("09:00", "10:00")
    # S46: the class's own what-to-bring line is public; a class without one is null.
    assert saturday["what_to_bring"] == "Racket, non-marking shoes, water"
    assert full["what_to_bring"] is None
    # Full class (active + held fill both seats; withdrawn does not) is
    # listed as waitlist, not dropped; coach shown by first name only.
    assert full["seats"] == {"band": "waitlist", "seats_left": None}
    assert full["coach_name"] == "Alex"

    ungrouped = {c["title"]: c for c in body["ungrouped_classes"]}
    # Archived program's class reads as ungrouped; the future one-off camp is
    # listed with its date and hidden coach; cancelled, past, private and the
    # other academy's classes are not listed at all.
    assert set(ungrouped) == {"Class orphaned", "October Camp"}
    camp = ungrouped["October Camp"]
    assert camp["coach_name"] is None
    assert camp["starts_on"] is not None and camp["start_time"] is not None
    assert camp["days_of_week"] == []


def test_unpublished_page_returns_the_branding_only_shape() -> None:
    response = _get(build_app(_db(published=False)))
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "state": "not_published",
        "academy": {
            "name": "Riverside Shuttle Club",
            "logo_url": "https://cdn.example.test/riverside.png",
            "brand_color": "#0f766e",
            "brand_fill": "#0f766e",
            "brand_on_color": "#ffffff",
        },
    }


def test_hidden_price_and_availability_are_absent_not_just_unrendered() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY},
            {"$set": {"public_page.show_price": False, "public_page.show_availability": False}},
        )
    )
    body = _get(build_app(db)).json()
    classes = [c for p in body["programs"] for c in p["classes"]] + body["ungrouped_classes"]
    assert classes
    assert all(c["price"] is None and c["seats"] is None for c in classes)
    assert "9000" not in _get(build_app(db)).text


def test_unknown_host_is_a_plain_404() -> None:
    response = _get(build_app(_db()), host="nobody-academy.courtmastr.test")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_host_resolved_to_an_academy_without_a_record_is_the_same_404() -> None:
    async def _ghost(_request: Any) -> str:
        return "acad-ghost"

    response = _get(build_app(_db(), resolve_tenant=_ghost))
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_suspended_tenant_gets_the_identical_404_not_423_with_its_id() -> None:
    async def _suspended(_academy_id: str) -> tuple[bool, str | None]:
        return False, "suspended"

    response = _get(build_app(_db(), check_tenant_servable=_suspended))
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
    assert ACADEMY not in response.text


def test_caller_cannot_choose_the_tenant_by_query_or_header() -> None:
    lakeside = _get(
        build_app(_db()),
        academy_id=ACADEMY,
        slug="riverside-academy",
        host="lakeside-academy.courtmastr.test",
    ).json()
    assert lakeside["academy"]["name"] == "Lakeside Racquets"
    titles = [c["title"] for c in lakeside["ungrouped_classes"]]
    assert titles == [SECRETS["other_academy_title"]]


def test_single_academy_mode_serves_the_primary_academy_on_its_own_host() -> None:
    """Production today: APP_TENANCY_MODE stays single_academy (backend/fly.toml);
    the real resolver maps every host to PRIMARY_ACADEMY_ID and the page works."""
    state = SimpleNamespace(
        saas_mode=False,
        tenancy_mode="single_academy",
        primary_academy_id=ACADEMY,
        default_academy_id="acad-default-unused",
        tenant_resolver=None,
    )
    resolve = _build_request_tenant_resolver(SimpleNamespace(state=state))  # type: ignore[arg-type]
    app = build_app(
        _db(),
        resolve_tenant=resolve,
        tenancy_mode="single_academy",
        primary_academy_id=ACADEMY,
    )
    response = _get(app, host="academy.courtmastr.test")
    assert response.status_code == 200
    assert response.json()["academy"]["name"] == "Riverside Shuttle Club"


def test_single_academy_mode_foreign_tenant_is_404_without_its_id() -> None:
    async def _foreign(_request: Any) -> str:
        return "acad-lakeside"

    app = build_app(
        _db(),
        resolve_tenant=_foreign,
        tenancy_mode="single_academy",
        primary_academy_id=ACADEMY,
    )
    response = _get(app)
    assert response.status_code == 404
    assert "acad-lakeside" not in response.text


def test_footer_uses_support_email_and_legal_links_when_set() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY},
            {
                "$set": {
                    "support_email": "help@riverside.example.test",
                    "terms_url": "https://riverside.example.test/terms",
                    "refund_policy_url": "https://riverside.example.test/refunds",
                    "public_page.privacy_notice_url": "https://riverside.example.test/privacy",
                }
            },
        )
    )
    body = _get(build_app(db)).json()
    assert body["academy"]["support_email"] == "help@riverside.example.test"
    assert body["page"]["terms_url"] == "https://riverside.example.test/terms"
    assert body["page"]["refund_policy_url"] == "https://riverside.example.test/refunds"
    assert body["page"]["privacy_notice_url"] == "https://riverside.example.test/privacy"


def test_footer_falls_back_to_the_contact_email_when_no_support_email() -> None:
    """BLNO has no support_email: its footer must not change."""
    body = _get(build_app(_db())).json()
    assert body["academy"]["support_email"] == SECRETS["contact_email"]
    assert body["page"]["terms_url"] is None
    assert body["page"]["refund_policy_url"] is None


def test_footer_never_renders_a_hostile_stored_legal_link() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY},
            {
                "$set": {
                    "terms_url": "javascript:alert(1)",
                    "refund_policy_url": "http://riverside.example.test/refunds",
                }
            },
        )
    )
    page = _get(build_app(db)).json()["page"]
    assert page["terms_url"] is None
    assert page["refund_policy_url"] is None


def _threshold_body(value: int | None, theme: str | None = None) -> dict[str, Any]:
    db = _db()
    fields: dict[str, Any] = {}
    if value is not None:
        fields["public_page.seats_left_threshold"] = value
    if theme is not None:
        fields["public_page.theme"] = theme
    asyncio.run(db["academies"].update_one({"academy_id": ACADEMY}, {"$set": fields}))
    body: dict[str, Any] = _get(build_app(db)).json()
    return body


def test_theme_and_threshold_are_exposed_and_the_threshold_drives_the_seat_band() -> None:
    body = _threshold_body(0, "daylight")
    assert body["page"]["theme"] == "daylight"
    assert body["page"]["seats_left_threshold"] == 0
    classes = [c for p in body["programs"] for c in p["classes"]] + body["ungrouped_classes"]
    assert all(c["seats"]["band"] != "few" for c in classes)

    wide = _threshold_body(20)
    wide_classes = [c for p in wide["programs"] for c in p["classes"]] + wide["ungrouped_classes"]
    few = [c for c in wide_classes if c["seats"]["band"] == "few"]
    assert few and all(c["seats"]["seats_left"] for c in few)
    # A full class stays a waitlist whatever the threshold.
    assert any(c["seats"]["band"] == "waitlist" for c in wide_classes)


def _venues(body: dict[str, Any]) -> dict[str, str | None]:
    classes = [c for p in body["programs"] for c in p["classes"]] + body["ungrouped_classes"]
    return {c["title"]: c["venue_address"] for c in classes}


def test_class_without_its_own_venue_shows_the_academy_default_venue() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY}, {"$set": {"default_venue_address": "9 Default Way"}}
        )
    )
    venues = _venues(_get(build_app(db)).json())
    # `sess-jr-sat` has its own address; every other class picks up the default.
    assert venues["Class jr-sat"] == "1 River Road, Riverside"
    assert venues["Class jr-full"] == "9 Default Way"


def test_no_academy_default_venue_leaves_a_bare_class_without_one() -> None:
    venues = _venues(_get(build_app(_db())).json())
    assert venues["Class jr-sat"] == "1 River Road, Riverside"
    assert venues["Class jr-full"] is None


# --- S55: publishing a class from its class page --------------------------------


def _admin_client(db: Any) -> TestClient:
    """The admin per-class public-fields route on the same database, tenant
    from a middleware (never the body), as Settings and the class page call it."""
    from fastapi import FastAPI, Request

    from backend.v2.composition.public_page_admin import compose_admin_public_page
    from backend.v2.interfaces.admin.router import router as admin_router
    from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
    from backend.v2.shared.http import register_exception_handlers
    from backend.v2.shared.tenancy.context import _current as _tenant_var
    from backend.v2.shared.tenancy.context import set_academy_id

    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(ACADEMY)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)  # type: ignore[arg-type]

    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin",
        email="admin@example.test",
        academy_id=ACADEMY,
        roles=("admin",),  # type: ignore[arg-type]
    )
    app.state.admin_public_page = compose_admin_public_page(db)
    return TestClient(app)


def _listed_titles(body: dict[str, Any]) -> set[str]:
    classes = [c for p in body["programs"] for c in p["classes"]] + body["ungrouped_classes"]
    return {c["title"] for c in classes}


def test_a_class_switched_on_from_its_page_is_public_and_switched_off_is_gone() -> None:
    db = _db()
    public = build_app(db)
    admin = _admin_client(db)
    new_class = "sess-new-from-class-page"
    asyncio.run(
        db["sessions"].insert_one(
            {
                "academy_id": ACADEMY,
                "session_id": new_class,
                "title": "Brand New Class",
                "capacity": 8,
                "status": "scheduled",
                "days_of_week": ["Sun"],
                "start_time": "10:00",
                "end_time": "11:00",
            }
        )
    )
    # Created with no switch sent: private, the default the backend keeps.
    assert "Brand New Class" not in _get(public).text

    on = admin.patch(f"/api/v2/admin/sessions/{new_class}/public-fields", json={"published": True})
    assert on.status_code == 200, on.text
    assert on.json()["published"] is True
    assert "Brand New Class" in _listed_titles(_get(public).json())

    off = admin.patch(
        f"/api/v2/admin/sessions/{new_class}/public-fields", json={"published": False}
    )
    assert off.status_code == 200, off.text
    response = _get(public)
    assert "Brand New Class" not in response.text
    # The other private classes stay out throughout.
    assert SECRETS["private_title"] not in response.text
