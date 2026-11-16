"""Self-booked trials over HTTP (L9 A6-1, A6-2, A6-4).

Real public routes, real composition with the recording stub send port, real
Mongo repositories on mongomock with the CRM and trial migrations, and the
real ``TenancyMiddleware``. Checks the public-route contract: the page offers
dates only while ``self_book_trials`` is on, a booking gets the SAME ack bytes
as a plain inquiry, an unknown key is treated as absent, a full date is the one
new answer (``409 Public.SlotUnavailable``), Turnstile fails closed, the
honeypot writes nothing, and nothing is mailed to the family while the switch
is off. Fictional academies and people only.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id
from backend.v2.shared.http.turnstile import TurnstileVerifier
from backend.v2.tests.fixtures.public_page import ACADEMY, RIVERSIDE_HOST, build_app, seed

URL = "/api/v2/public/trial-requests"
PAGE = "/api/v2/public/academy"
OWNER_EMAIL = "owner.riverside@example.test"
_MIGRATIONS = [
    importlib.import_module(f"backend.v2.migrations.{name}")
    for name in (
        "0192_crm_contacts",
        "0217_email_prospect_opt_outs",
        "0218_crm_inquiry_ack_throttle",
        "0236_trial_guest_bookings",
    )
]


async def _seed_all(db: Any, *, self_book: bool, guest_cap: int) -> None:
    for migration in _MIGRATIONS:
        await migration.up(db)
    await seed(db)
    await db["academies"].update_one(
        {"academy_id": ACADEMY},
        {
            "$set": {
                "public_page.self_book_trials": self_book,
                "public_page.trial_guest_cap": guest_cap,
            }
        },
    )
    await db["academy_memberships"].insert_one(
        {"academy_id": ACADEMY, "user_id": "owner-rsc-1", "roles": ["owner"], "status": "active"}
    )
    await db["users"].insert_one(
        {"user_id": "owner-rsc-1", "academy_id": ACADEMY, "email": OWNER_EMAIL}
    )
    now = datetime.now(UTC).replace(microsecond=0)
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "occurrence_id": f"occ-sat-{i}",
                "session_id": "sess-jr-sat",
                "start_at": now + timedelta(days=i),
                "end_at": now + timedelta(days=i, hours=1),
                "status": "scheduled",
                "scheduled_coach_id": "coach-rsc-1",
            }
            for i in (1, 2)
        ]
    )


def _app(*, self_book: bool = True, guest_cap: int = 2) -> tuple[Any, Any]:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["self-book"]
    asyncio.run(_seed_all(db, self_book=self_book, guest_cap=guest_cap))
    return build_app(db), db


def _client(app: Any) -> TestClient:
    return TestClient(app, headers={"host": RIVERSIDE_HOST})


def _dates(app: Any) -> list[dict[str, Any]]:
    page = _client(app).get(PAGE).json()
    for program in page["programs"]:
        for cls in program["classes"]:
            if cls["public_id"] == public_class_id(ACADEMY, "sess-jr-sat"):
                return list(cls["trial_dates"])
    return []


def _form(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Jamie Testparent",
        "email": "jamie.testparent@example.test",
        "player_age": "9",
        "contact_about_request": True,
        "utm_source": "facebook",
    }
    body.update(overrides)
    return body


def _trials(db: Any) -> list[dict[str, Any]]:
    async def _all() -> list[dict[str, Any]]:
        return [doc async for doc in db["trial_requests"].find({})]

    return asyncio.run(_all())


def _comparable(response: Any) -> tuple[int, bytes, dict[str, str]]:
    headers = {k.lower(): v for k, v in response.headers.items() if k.lower() != "date"}
    return response.status_code, response.content, headers


def test_switched_off_offers_no_dates_and_a_slot_key_is_ignored() -> None:
    app, db = _app(self_book=False)
    assert _dates(app) == []
    # A key from elsewhere is just an unknown field value: a plain inquiry.
    response = _client(app).post(URL, json=_form(slot_key="t_" + "a" * 20))
    assert response.status_code == 200
    assert _trials(db) == []
    assert not any("booked" in s["subject"] for s in app.state.sent_email.sent)


def test_booking_gets_the_plain_ack_and_seats_the_guest_and_confirms() -> None:
    app, db = _app()
    [first, second] = _dates(app)
    assert set(first) == {"slot_key", "starts_at"}
    assert first["slot_key"].startswith("t_")

    plain = _client(app).post(URL, json=_form(email="other.family@example.test"))
    booked = _client(app).post(URL, json=_form(slot_key=first["slot_key"]))

    assert _comparable(plain) == _comparable(booked)
    [row] = _trials(db)
    assert row["academy_id"] == ACADEMY
    assert row["status"] == "approved"
    assert row["assigned_occurrence_id"] == "occ-sat-1"
    assert row["guest_slot"] == 1
    assert row["guest_name"] == "Jamie Testparent" and row["guest_age"] == "9"
    assert row["parent_user_id"] is None and row["contact_id"]
    contact = asyncio.run(db["crm_contacts"].find_one({"contact_id": row["contact_id"]}))
    assert contact["pipeline_status"] == "trial"
    assert contact["attribution"]["utm_source"] == "facebook"
    assert contact.get("owner_alert_due_at") is None and contact["owner_alert_sent_at"]

    sent = app.state.sent_email.sent
    owner = [s for s in sent if s["subject"] == "New trial booking from Jamie Testparent"]
    assert len(owner) == 1 and "Booked for" in owner[0]["body"]
    family = [s for s in sent if s["user_id"] == f"crm_contact:{row['contact_id']}"]
    # The confirmation replaces the generic acknowledgement.
    assert [s["subject"] for s in family] == ["Your free trial is booked: Class jr-sat"]
    assert second["slot_key"] != first["slot_key"]


def test_an_unknown_slot_key_is_treated_as_absent() -> None:
    app, db = _app()
    response = _client(app).post(URL, json=_form(slot_key="t_not-a-real-key"))
    assert response.status_code == 200
    assert _trials(db) == []


def test_a_full_date_is_the_one_new_answer() -> None:
    app, db = _app(guest_cap=1)
    [first, _] = _dates(app)
    assert _client(app).post(URL, json=_form(slot_key=first["slot_key"])).status_code == 200
    late = _client(app).post(
        URL, json=_form(email="late.family@example.test", slot_key=first["slot_key"])
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "Public.SlotUnavailable"
    assert len(_trials(db)) == 1
    # The filled date leaves the page; the next one is still offered.
    assert [d["slot_key"] for d in _dates(app)] != [first["slot_key"]]


def test_turnstile_fails_closed_on_the_booking_branch_only() -> None:
    app, db = _app()
    [first, _] = _dates(app)

    def _down() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(503)))

    app.state.public_trial_requests = dataclasses.replace(
        app.state.public_trial_requests,
        turnstile=TurnstileVerifier("test-secret", client_factory=_down),
    )
    refused = _client(app).post(URL, json=_form(slot_key=first["slot_key"]))
    assert refused.status_code == 422
    assert "turnstile_token" in refused.json()["error"]["details"]["fields"]
    assert _trials(db) == []
    # No slot: the inquiry path never calls Turnstile.
    assert _client(app).post(URL, json=_form()).status_code == 200


def test_production_without_a_secret_refuses_bookings_but_takes_inquiries() -> None:
    app, db = _app()
    [first, _] = _dates(app)
    app.state.public_trial_requests = dataclasses.replace(
        app.state.public_trial_requests, turnstile=TurnstileVerifier(None, required=True)
    )
    refused = _client(app).post(URL, json=_form(slot_key=first["slot_key"], turnstile_token="t"))
    assert refused.status_code == 422
    assert _trials(db) == []
    assert _client(app).post(URL, json=_form()).status_code == 200


def test_the_honeypot_books_nothing() -> None:
    app, db = _app()
    [first, _] = _dates(app)
    response = _client(app).post(URL, json=_form(slot_key=first["slot_key"], website="spam"))
    assert response.status_code == 200
    assert _trials(db) == []
    assert asyncio.run(db["crm_contacts"].count_documents({})) == 0


def test_a_second_class_date_for_the_same_inbox_stays_an_inquiry() -> None:
    app, db = _app()
    [first, second] = _dates(app)
    assert _client(app).post(URL, json=_form(slot_key=first["slot_key"])).status_code == 200
    again = _client(app).post(URL, json=_form(slot_key=second["slot_key"], player_age="7"))
    assert again.status_code == 200
    assert len(_trials(db)) == 1
