"""L9 A6-2 decision emails (dark until ``self_book_trials``) and the A6-11
owner-alert sweep, over the real composition on mongomock."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.tests.fixtures.public_page import ACADEMY, build_app, seed

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
_M0219 = importlib.import_module("backend.v2.migrations.0219_trial_nudge_sends")
OWNER_EMAIL = "owner.riverside@example.test"


async def _seed(db: Any) -> None:
    await _M0192.up(db)
    await _M0219.up(db)
    await seed(db)
    await db["academy_memberships"].insert_one(
        {"academy_id": ACADEMY, "user_id": "owner-rsc-1", "roles": ["owner"], "status": "active"}
    )
    await db["users"].insert_one(
        {"user_id": "owner-rsc-1", "academy_id": ACADEMY, "email": OWNER_EMAIL}
    )


def _app() -> tuple[Any, Any]:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["trial-emails"]
    asyncio.run(_seed(db))
    return build_app(db), db


def _contact_doc(**fields: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "academy_id": ACADEMY,
        "contact_id": "contact-1",
        "name": "Jamie Testparent",
        "email": "jamie.testparent@example.test",
        "source": "website",
        "pipeline_status": "trial",
        "dedupe_key": "website:jamie",
        "consent": {"contact_about_request": True, "marketing": False},
        "created_at": now,
        "updated_at": now,
    }
    doc.update(fields)
    return doc


def test_the_sweep_resends_a_due_owner_alert_once() -> None:
    app, db = _app()
    notifier = app.state.public_trial_requests.notifier
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    asyncio.run(db["crm_contacts"].insert_one(_contact_doc(owner_alert_due_at=hour_ago)))
    # Too fresh: the background task still has its chance.
    asyncio.run(
        db["crm_contacts"].insert_one(
            _contact_doc(
                contact_id="contact-2",
                dedupe_key="website:fresh",
                owner_alert_due_at=datetime.now(UTC),
            )
        )
    )

    assert asyncio.run(notifier.send_due_alerts(academy_id=ACADEMY)) == 1
    assert asyncio.run(notifier.send_due_alerts(academy_id=ACADEMY)) == 0
    owner = [s for s in app.state.sent_email.sent if s["subject"].startswith("New trial request")]
    assert len(owner) == 1
    row = asyncio.run(db["crm_contacts"].find_one({"contact_id": "contact-1"}))
    assert "owner_alert_due_at" not in row and row["owner_alert_sent_at"]


def _denied_guest() -> TrialRequest:
    now = datetime.now(UTC)
    return TrialRequest(
        request_id="tr-1",
        academy_id=ACADEMY,
        contact_id="contact-1",
        student_ref="prospective",
        requested_session_id="sess-jr-sat",
        preferred_start="2026-12-01",
        preferred_end="2026-12-01",
        status="denied",
        denial_reason="That class is for older players.",
        decided_by="owner-rsc-1",
        decided_at=now,
        created_at=now,
    )


def test_decision_emails_stay_dark_until_self_booking_is_on() -> None:
    app, db = _app()
    emails = app.state.public_trial_requests.notifier._bookings
    asyncio.run(db["crm_contacts"].insert_one(_contact_doc()))
    trial = _denied_guest()

    asyncio.run(emails.trial_decided(trial))
    assert app.state.sent_email.sent == []

    asyncio.run(
        db["academies"].update_one(
            {"academy_id": ACADEMY}, {"$set": {"public_page.self_book_trials": True}}
        )
    )
    asyncio.run(emails.trial_decided(trial))
    asyncio.run(emails.trial_decided(trial))  # claimed once: no second email
    [sent] = app.state.sent_email.sent
    assert sent["user_id"] == "crm_contact:contact-1"
    assert sent["subject"] == "About your free trial request: Class jr-sat"
    assert "older players" in sent["body"]
