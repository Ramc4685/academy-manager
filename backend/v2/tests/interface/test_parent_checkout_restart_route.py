"""POST /parent/checkout/start against an application already CHECKOUT_PENDING.

The other checkout route tests stub the composition out, so they say nothing
about what the real use case does when the SAME application starts checkout a
second time (two tabs, or a retried request). These drive the real parent
composition over an in-memory Mongo so the HTTP contract for that case is
pinned: a restart succeeds and re-points the application at the new payment,
while an application past checkout is refused with a 409 before Stripe is
touched at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.config import get_settings
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope

ORIGIN = "https://app.example.com"
SUCCESS_URL = f"{ORIGIN}/parent/checkout/return?application_id=app-1"
CANCEL_URL = f"{ORIGIN}/parent/onboarding"


class _TenantScopeMiddleware:
    """Pure-ASGI so the tenant contextvar is set in the SAME task that runs the
    endpoint. In the real app the auth middleware does this."""

    def __init__(self, app: Any, academy_id: str) -> None:
        self.app = app
        self.academy_id = academy_id

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        with tenant_scope(self.academy_id):
            await self.app(scope, receive, send)


class _RecordingStripe:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.expired: list[str] = []

    async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
        self.created.append(kwargs)
        checkout_id = f"cs_new_{len(self.created)}"
        return checkout_id, f"https://checkout.stripe.test/{checkout_id}"

    async def expire_checkout_session(self, checkout_session_id: str) -> None:
        self.expired.append(checkout_session_id)


def _pinned_quote_clock() -> datetime:
    """First instant of the real current month, in the SESSION's timezone.

    The quote is "what is left of this month", so pricing against the wall
    clock makes the fixture's amount depend on when the suite runs — late
    enough and the quote drops to $0 and checkout skips Stripe entirely.

    The month has to be the session-local one (#541): quotes are periodised in
    the session timezone, so the first UTC instant of the month is the evening
    of the 31st in Chicago and would quote the PREVIOUS local month, in which
    this fixture's session has no classes at all.
    """
    tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    return datetime(now.year, now.month, 1, tzinfo=tz)


def _application_doc(status: str, **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc: dict[str, Any] = {
        "application_id": "app-1",
        "academy_id": "acad",
        "parent_user_id": "parent-1",
        "parent_email": "parent@example.com",
        "status": status,
        "selected_session_id": "sess-1",
        "expires_at": now + timedelta(days=7),
        "created_at": now,
        "updated_at": now,
        "parent_profile": {
            "first_name": "Meera",
            "last_name": "Raghavan",
            "phone": "+1 555 0100",
        },
        "child_profile": {
            "first_name": "Aanya",
            "last_name": "Raghavan",
            "date_of_birth": "2015-04-02",
            "emergency_contact_name": "Vikram Raghavan",
            "emergency_contact_phone": "+1 555 0111",
        },
    }
    doc.update(extra)
    return doc


def _session_doc(quote_now: datetime) -> dict[str, Any]:
    month_start = quote_now.date().replace(day=1)
    end_of_next_month = (month_start + timedelta(days=62)).replace(day=1) - timedelta(days=1)
    return {
        "session_id": "sess-1",
        "academy_id": "acad",
        "status": "scheduled",
        "title": "Beginner",
        "start_at": datetime.now(UTC) + timedelta(hours=3),
        "end_at": datetime.now(UTC) + timedelta(hours=4),
        "start_date": month_start.isoformat(),
        "end_date": end_of_next_month.isoformat(),
        "days_of_week": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "start_time": "17:00",
        "end_time": "18:00",
        "capacity": 8,
        "amount_cents": 6_000,
    }


@contextmanager
def _client(db: Any, stripe: Any, quote_now: datetime) -> Iterator[TestClient]:
    parent = compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,
        academy_id="acad",
        clock=lambda: quote_now,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.add_middleware(_TenantScopeMiddleware, academy_id="acad")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1",
        email="parent@example.com",
        academy_id="acad",
        roles=("parent",),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_parent_use_cases] = lambda: parent
    with TestClient(app) as client:
        yield client


@pytest.fixture
def allow_app_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V2_CORS_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_db(allow_app_origin):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["parent-checkout-restart-route"]


async def _seed(db: Any, quote_now: datetime, *, status: str, **app_extra: Any) -> None:
    await db["onboarding_applications"].insert_one(_application_doc(status, **app_extra))
    await db["sessions"].insert_one(_session_doc(quote_now))
    account = ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_ready").with_status(
        status="active", charges_enabled=True
    )
    await db["academy_connected_accounts"].insert_one(account.model_dump(mode="python"))


@pytest.mark.asyncio
async def test_restarting_checkout_over_http_repoints_the_application(seeded_db) -> None:
    """Second POST for an application already parked on a live session."""
    db = seeded_db
    quote_now = _pinned_quote_clock()
    await _seed(
        db,
        quote_now,
        status="CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_first",
        payment_id="pay-first",
    )
    now = datetime.now(UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "acad",
            "payment_id": "pay-first",
            "parent_id": "parent-1",
            "session_id": "sess-1",
            "stripe_checkout_session_id": "cs_first",
            "amount_cents": 6_000,
            "currency": "usd",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    stripe = _RecordingStripe()

    with _client(db, stripe, quote_now) as client:
        response = client.post(
            "/api/v2/parent/checkout/start",
            json={
                "application_id": "app-1",
                "success_url": SUCCESS_URL,
                "cancel_url": CANCEL_URL,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payment_id"] != "pay-first"

    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    # The webhook resolves the application through payment_id alone, so the
    # live payment has to be the one stamped here.
    assert app_doc["payment_id"] == body["payment_id"]
    assert app_doc["stripe_checkout_session_id"] == "cs_new_1"
    # ...and only one payable session may remain.
    assert stripe.expired == ["cs_first"]
    first_payment = await db["ledger_payments"].find_one({"payment_id": "pay-first"})
    assert first_payment["status"] == "expired"


@pytest.mark.asyncio
async def test_checkout_start_over_http_refuses_a_past_checkout_application(seeded_db) -> None:
    """A status with no outbound CHECKOUT_PENDING edge is a 409, and the
    refusal lands before Stripe or any payment write."""
    db = seeded_db
    quote_now = _pinned_quote_clock()
    await _seed(db, quote_now, status="CHECKOUT_EXPIRED")
    stripe = _RecordingStripe()

    with _client(db, stripe, quote_now) as client:
        response = client.post(
            "/api/v2/parent/checkout/start",
            json={
                "application_id": "app-1",
                "success_url": SUCCESS_URL,
                "cancel_url": CANCEL_URL,
            },
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Onboarding.ApplicationNotEditable"
    assert stripe.created == []
    assert await db["ledger_payments"].count_documents({}) == 0
    assert await db["billing_calculation_snapshots"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_wizard_start_resumes_the_abandoned_checkout_over_http(seeded_db) -> None:
    """Option A end to end.

    Stripe's cancel_url is the wizard, and the wizard POSTs /onboarding/start
    on mount. That must hand back THIS application, editable, with the old
    Stripe session killed — not a second application whose sibling is still
    payable."""
    db = seeded_db
    quote_now = _pinned_quote_clock()
    await _seed(
        db,
        quote_now,
        status="CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_first",
        payment_id="pay-first",
    )
    now = datetime.now(UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "acad",
            "payment_id": "pay-first",
            "parent_id": "parent-1",
            "session_id": "sess-1",
            "stripe_checkout_session_id": "cs_first",
            "amount_cents": 6_000,
            "currency": "usd",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    stripe = _RecordingStripe()

    with _client(db, stripe, quote_now) as client:
        response = client.post("/api/v2/parent/onboarding/start")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application_id"] == "app-1"
    assert body["status"] == "DRAFT"
    # The parent's details survive the resume — they are not made to retype.
    assert body["parent_profile"]["phone"] == "+1 555 0100"
    assert body["selected_session_id"] == "sess-1"
    assert stripe.expired == ["cs_first"]
    first_payment = await db["ledger_payments"].find_one({"payment_id": "pay-first"})
    assert first_payment["status"] == "expired"
    assert await db["onboarding_applications"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_wizard_start_does_not_resurrect_a_paid_application(seeded_db) -> None:
    """The parent paid in the other tab before the wizard mounted. Dragging a
    PENDING_APPROVAL application back to DRAFT would unpick a real charge."""
    db = seeded_db
    quote_now = _pinned_quote_clock()
    await _seed(
        db,
        quote_now,
        status="PENDING_APPROVAL",
        stripe_checkout_session_id="cs_first",
        payment_id="pay-first",
    )
    stripe = _RecordingStripe()

    with _client(db, stripe, quote_now) as client:
        response = client.post("/api/v2/parent/onboarding/start")

    assert response.status_code == 200, response.text
    assert response.json()["application_id"] != "app-1"
    paid = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert paid["status"] == "PENDING_APPROVAL"
    assert stripe.expired == []
