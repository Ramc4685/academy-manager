"""``POST /api/v2/public/trial-requests`` over HTTP (public tenant page, Lane B4).

Real route, real composition (with the recording stub send port), real Mongo
repositories on mongomock with migration 0192's indexes (so the dedupe is the
unique index, not a fake), and the real ``TenancyMiddleware`` resolving the
tenant from the Host header. Fictional academies and people only.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id
from backend.v2.tests.fixtures.public_page import (
    ACADEMY,
    OTHER,
    RIVERSIDE_HOST,
    SECRETS,
    build_app,
    seed,
)

URL = "/api/v2/public/trial-requests"
LAKESIDE_HOST = "lakeside-academy.courtmastr.test"
OWNER_EMAIL = "owner.riverside@example.test"
_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")


async def _seed_all(db: Any, *, published: bool, owner: bool) -> None:
    await _M0192.up(db)
    await seed(db, published=published)
    if owner:
        await db["academy_memberships"].insert_one(
            {
                "academy_id": ACADEMY,
                "user_id": "owner-rsc-1",
                "roles": ["owner"],
                "status": "active",
            }
        )
        await db["users"].insert_one(
            {
                "user_id": "owner-rsc-1",
                "academy_id": ACADEMY,
                "email": OWNER_EMAIL,
                "display_name": "Robin Owner",
            }
        )


def _db(*, published: bool = True, owner: bool = True) -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["public-trial"]
    asyncio.run(_seed_all(db, published=published, owner=owner))
    return db


def _form(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Jamie Testparent",
        "email": "Jamie.Testparent@Example.test",
        "phone": "(555) 010-2030",
        "player_age": "9",
        "class_id": public_class_id(ACADEMY, "sess-jr-sat"),
        "message": "First time holding a racket.",
        "contact_about_request": True,
    }
    body.update(overrides)
    return body


def _post(app: Any, body: Any, host: str = RIVERSIDE_HOST) -> Any:
    return TestClient(app).post(URL, json=body, headers={"host": host})


def _rows(db: Any) -> list[dict[str, Any]]:
    async def _all() -> list[dict[str, Any]]:
        return [doc async for doc in db["crm_contacts"].find({})]

    return asyncio.run(_all())


def _comparable(response: Any) -> tuple[int, bytes, dict[str, str]]:
    headers = {k.lower(): v for k, v in response.headers.items() if k.lower() != "date"}
    return response.status_code, response.content, headers


def test_new_and_repeated_submissions_get_byte_identical_answers_and_one_row() -> None:
    db = _db()
    app = build_app(db)
    first = _post(app, _form())
    # A double tap with a corrected name spelling is still the same inquiry.
    second = _post(app, _form(name="Jamie Test-Parent"))

    assert first.status_code == 200, first.text
    assert first.json() == {"state": "received"}
    assert first.headers["cache-control"] == "no-store"
    assert _comparable(first) == _comparable(second)

    [row] = _rows(db)
    assert row["academy_id"] == ACADEMY
    assert row["source"] == "website"
    assert row["pipeline_status"] == "trial"
    assert row["email"] == "jamie.testparent@example.test"
    assert row["phone_digits"] == "5550102030"
    assert row["child_age"] == "9"
    assert row["child_name"] is None
    assert row["created_by"] is None
    assert row["requested_session_id"] == SECRETS["published_session_id"]
    assert row["message"] == "First time holding a racket."
    assert row["consent"]["contact_about_request"] is True
    assert row["consent"]["marketing"] is False
    assert row["consent"]["captured_at"] is not None
    assert row["consent"]["privacy_notice_url"] is None


def test_owner_is_emailed_once_for_a_new_contact_only() -> None:
    db = _db()
    app = build_app(db)
    _post(app, _form())
    _post(app, _form())
    _post(app, _form())

    [sent] = app.state.sent_email.sent
    assert sent["email"] == OWNER_EMAIL
    assert sent["reply_to"] == "jamie.testparent@example.test"
    assert sent["subject"] == "New trial request from Jamie Testparent"
    assert "Riverside Shuttle Club" in sent["body"]
    assert "Class jr-sat" in sent["body"]
    assert "First time holding a racket." in sent["body"]


def test_owner_email_escapes_form_text() -> None:
    db = _db()
    app = build_app(db)
    _post(app, _form(name="<b>Jamie</b>", message="<script>alert(1)</script>"))
    [sent] = app.state.sent_email.sent
    assert "<script>" not in sent["body"]
    assert "&lt;script&gt;" in sent["body"]


def test_no_owner_address_falls_back_to_the_academy_contact_email() -> None:
    db = _db(owner=False)
    app = build_app(db)
    _post(app, _form())
    [sent] = app.state.sent_email.sent
    assert sent["email"] == SECRETS["contact_email"]


def test_a_failing_send_never_changes_the_answer() -> None:
    db = _db()
    app = build_app(db)

    async def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    app.state.public_trial_requests.notifier._sender.send = _boom  # type: ignore[method-assign]
    response = _post(app, _form())
    assert response.status_code == 200
    assert response.json() == {"state": "received"}
    assert len(_rows(db)) == 1


def test_honeypot_hit_gets_the_same_answer_and_writes_nothing() -> None:
    db = _db()
    app = build_app(db)
    real = _post(app, _form(email="someone.else@example.test"))
    bot = _post(app, _form(website="https://spam.example.test"))
    assert _comparable(bot) == _comparable(real)
    assert [r["email"] for r in _rows(db)] == ["someone.else@example.test"]
    assert len(app.state.sent_email.sent) == 1


def test_honeypot_runs_the_same_validation_and_class_read_as_a_person() -> None:
    """The honeypot is checked last so its response path matches a real one
    (same validation, same published-class read); only the write is skipped."""
    db = _db()
    app = build_app(db)
    deps = app.state.public_trial_requests
    calls: list[Any] = []
    real_execute = deps.resolve_class_choice.execute

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return await real_execute(*args, **kwargs)

    deps.resolve_class_choice.execute = _spy  # type: ignore[method-assign]
    bot = _post(app, _form(website="https://spam.example.test"))
    assert bot.status_code == 200
    assert len(calls) == 1
    invalid_bot = _post(app, _form(website="https://spam.example.test", email="not-an-email"))
    assert invalid_bot.status_code == 422
    assert _rows(db) == []
    assert app.state.sent_email.sent == []


def test_tenant_comes_from_the_host_never_the_body() -> None:
    db = _db()
    app = build_app(db)
    response = _post(
        app,
        _form(class_id=None, academy_id=ACADEMY, tenant="riverside", slug="riverside-academy"),
        host=LAKESIDE_HOST,
    )
    assert response.status_code == 200, response.text
    [row] = _rows(db)
    assert row["academy_id"] == OTHER


def test_child_name_and_staff_fields_in_the_body_are_ignored() -> None:
    db = _db()
    app = build_app(db)
    response = _post(
        app,
        _form(child_name="Should Not Store", created_by="staff-1", referrer_parent_id="par-1"),
    )
    assert response.status_code == 200, response.text
    [row] = _rows(db)
    assert row["child_name"] is None
    assert row["created_by"] is None
    assert row["referrer_parent_id"] is None
    assert "Should Not Store" not in json.dumps(row, default=str)


def test_unknown_host_is_the_plain_404() -> None:
    db = _db()
    response = _post(build_app(db), _form(), host="nobody-academy.courtmastr.test")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
    assert _rows(db) == []


def test_unpublished_page_refuses_with_the_same_404_as_an_unknown_host() -> None:
    db = _db(published=False)
    app = build_app(db)
    unpublished = _post(app, _form())
    unknown = _post(app, _form(), host="nobody-academy.courtmastr.test")
    assert (unpublished.status_code, unpublished.content) == (unknown.status_code, unknown.content)
    assert _rows(db) == []


def test_trials_closed_is_a_clear_409_and_writes_nothing() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY}, {"$set": {"public_page.trials_open": False}}
        )
    )
    response = _post(build_app(db), _form())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Public.TrialsClosed"
    assert "paused" in response.json()["error"]["message"]
    assert _rows(db) == []


def test_privacy_notice_url_and_marketing_opt_in_are_recorded() -> None:
    db = _db()
    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY},
            {"$set": {"public_page.privacy_notice_url": "https://riverside.example.test/privacy"}},
        )
    )
    _post(build_app(db), _form(marketing_opt_in=True))
    [row] = _rows(db)
    assert row["consent"]["marketing"] is True
    assert row["consent"]["privacy_notice_url"] == "https://riverside.example.test/privacy"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "  "}, "name"),
        ({"name": "x" * 121}, "name"),
        ({"email": None}, "email"),
        ({"email": "not-an-email"}, "email"),
        ({"phone": "12"}, "phone"),
        ({"player_age": ""}, "player_age"),
        ({"player_age": "x" * 21}, "player_age"),
        ({"message": "y" * 1001}, "message"),
        ({"contact_about_request": False}, "contact_about_request"),
        ({"class_id": public_class_id(ACADEMY, SECRETS["private_session_id"])}, "class_id"),
        ({"class_id": public_class_id(ACADEMY, "sess-cancelled")}, "class_id"),
        ({"class_id": public_class_id(OTHER, "sess-other")}, "class_id"),
        ({"class_id": "c_doesnotexist"}, "class_id"),
        ({"name": ["a", "list"]}, "name"),
    ],
)
def test_validation_names_the_field_and_never_echoes_input(
    overrides: dict[str, Any], field: str
) -> None:
    db = _db()
    body = _form(**overrides)
    response = _post(build_app(db), body)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "Public.InvalidTrialRequest"
    assert field in error["details"]["fields"]
    for value in overrides.values():
        if isinstance(value, str) and len(value) > 3:
            assert value not in response.text
    assert _rows(db) == []


def test_several_missing_fields_are_reported_together() -> None:
    db = _db()
    response = _post(build_app(db), {"contact_about_request": False})
    assert response.status_code == 422
    assert set(response.json()["error"]["details"]["fields"]) == {
        "name",
        "email",
        "player_age",
        "contact_about_request",
    }


def test_non_json_and_non_object_bodies_are_422() -> None:
    db = _db()
    client = TestClient(build_app(db))
    for content in (b"not json", b"[1, 2]", b""):
        response = client.post(
            URL,
            content=content,
            headers={"host": RIVERSIDE_HOST, "content-type": "application/json"},
        )
        assert response.status_code == 422
        assert "form" in response.json()["error"]["details"]["fields"]


def test_oversized_body_is_refused_before_parsing() -> None:
    db = _db()
    response = _post(build_app(db), _form(message="z" * 20_000))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "Public.RequestTooLarge"
    assert _rows(db) == []


def test_full_class_or_no_class_choice_files_the_right_stage() -> None:
    db = _db()
    app = build_app(db)
    _post(app, _form(class_id=public_class_id(ACADEMY, "sess-jr-full"), email="full@example.test"))
    _post(app, _form(class_id="", email="unsure@example.test"))
    stages = {row["email"]: row["pipeline_status"] for row in _rows(db)}
    # A full class is the waitlist variant (lead); "not sure" with open
    # classes elsewhere is a trial.
    assert stages == {"full@example.test": "lead", "unsure@example.test": "trial"}
    unsure = next(r for r in _rows(db) if r["email"] == "unsure@example.test")
    assert unsure["requested_session_id"] is None


def test_academy_with_nothing_listed_files_a_lead() -> None:
    db = _db()
    asyncio.run(db["sessions"].update_many({"academy_id": ACADEMY}, {"$set": {"published": False}}))
    response = _post(build_app(db), _form(class_id=None))
    assert response.status_code == 200
    [row] = _rows(db)
    assert row["pipeline_status"] == "lead"
