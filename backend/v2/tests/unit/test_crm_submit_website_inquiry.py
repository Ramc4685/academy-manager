"""SubmitWebsiteInquiry: the public form's write through CreateContact (Lane B4)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import mongomock_motor

from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    SubmitWebsiteInquiry,
    WebsiteInquiryForm,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
ACADEMY = "acad-website-inquiry"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


async def _use_case() -> SubmitWebsiteInquiry:
    db = mongomock_motor.AsyncMongoMockClient()["website_inquiry"]
    await _M0192.up(db)
    ids = iter(f"contact-{n}" for n in range(10))
    return SubmitWebsiteInquiry(
        CreateContact(MongoCrmContactRepository(db), clock=lambda: NOW, new_id=lambda: next(ids))
    )


def _form(**overrides: Any) -> WebsiteInquiryForm:
    fields: dict[str, Any] = {
        "name": "Jamie Testparent",
        "email": "jamie@example.test",
        "phone": None,
        "player_age": "9",
        "class_id": None,
        "message": None,
        "contact_about_request": True,
        "marketing_opt_in": False,
    }
    fields.update(overrides)
    return WebsiteInquiryForm(**fields)


async def test_writes_a_website_contact_with_consent_and_no_child_name() -> None:
    use_case = await _use_case()
    with tenant_scope(ACADEMY):
        result = await use_case.execute(
            _form(marketing_opt_in=True),
            requested_session_id="sess-1",
            pipeline_status="trial",
            privacy_notice_url="https://riverside.example.test/privacy",
        )
        again = await use_case.execute(
            _form(), requested_session_id="sess-1", pipeline_status="trial", privacy_notice_url=None
        )
    assert result.field_errors == {} and result.created is True
    contact = result.contact
    assert contact is not None
    assert (contact.source, contact.academy_id, contact.child_name) == ("website", ACADEMY, None)
    assert contact.consent.contact_about_request is True
    assert contact.consent.marketing is True
    assert contact.consent.captured_at == NOW
    assert contact.consent.privacy_notice_url == "https://riverside.example.test/privacy"
    assert again.created is False and again.contact == contact


async def test_all_field_errors_come_back_together_and_nothing_is_written() -> None:
    use_case = await _use_case()
    with tenant_scope(ACADEMY):
        result = await use_case.execute(
            _form(name=" ", email="nope", player_age=None, contact_about_request=False),
            requested_session_id=None,
            pipeline_status="lead",
            privacy_notice_url=None,
        )
    assert result.contact is None and result.created is False
    assert set(result.field_errors) == {"name", "email", "player_age", "contact_about_request"}
