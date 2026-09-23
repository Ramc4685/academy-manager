"""``CreateContact`` against the real Mongo repository and the 0192 indexes.

No hand-written fake: the dedupe behaviour lives in the unique index, and a
permissive fake would hide exactly the bug this use case exists to prevent.
Names are obviously fake.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import mongomock_motor
import pytest

from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.domain.errors import InvalidContact
from backend.v2.contexts.crm.domain.models import (
    CONTACT_SOURCES,
    PIPELINE_STATUSES,
    ContactConsent,
    compute_dedupe_key,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")

ACADEMY = "acad-crm-test"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


async def _db() -> Any:
    db = mongomock_motor.AsyncMongoMockClient()["crm_test"]
    await _M0192.up(db)
    return db


def _use_case(db: Any) -> CreateContact:
    ids = iter(f"contact-{n}" for n in range(100))
    return CreateContact(MongoCrmContactRepository(db), clock=lambda: NOW, new_id=lambda: next(ids))


def _website(**overrides: Any) -> CreateContactCommand:
    base: dict[str, Any] = {
        "name": "Testy Parentson",
        "source": "website",
        "email": "Testy.Parent@Example.test",
        "phone": "(555) 010-2030",
        "child_age": "9",
        "requested_session_id": "sess-1",
        "pipeline_status": "trial",
        "consent": ContactConsent(contact_about_request=True),
    }
    base.update(overrides)
    return CreateContactCommand(**base)


def test_vocabularies_are_the_spec_values() -> None:
    assert CONTACT_SOURCES == {"website", "whatsapp_or_phone", "referral", "other"}
    assert PIPELINE_STATUSES == {"lead", "trial", "enrolled"}


async def test_website_trial_request_creates_a_normalised_row() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        result = await _use_case(db).execute(_website())

    assert result.created is True
    c = result.contact
    assert c.academy_id == ACADEMY
    assert c.email == "testy.parent@example.test"
    assert c.phone_digits == "5550102030"
    assert c.source == "website"
    assert c.pipeline_status == "trial"
    assert c.child_name is None
    assert c.created_by is None
    assert c.consent.contact_about_request is True
    assert c.consent.marketing is False
    assert c.consent.captured_at == NOW
    assert c.linked_family_id is None and c.linked_user_id is None
    assert c.converted_parent_id is None and c.referrer_parent_id is None

    row = await db["crm_contacts"].find_one({"contact_id": c.contact_id})
    assert row["academy_id"] == ACADEMY
    assert row["dedupe_key"] == c.dedupe_key
    assert row["consent"]["contact_about_request"] is True


async def test_double_submit_returns_the_existing_row_without_a_second_write() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        use_case = _use_case(db)
        first = await use_case.execute(_website())
        # Same inquiry, typed a little differently: case, spacing, phone punctuation,
        # a corrected spelling of the parent's own name.
        again = await use_case.execute(
            _website(
                name="Testy  Parentsen",
                email="  testy.parent@example.TEST ",
                phone="555-010-2030",
            )
        )

    assert again.created is False
    assert again.contact.contact_id == first.contact.contact_id
    assert again.contact.name == "Testy Parentson"
    assert await db["crm_contacts"].count_documents({}) == 1


async def test_a_different_class_or_age_is_a_new_lead() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        use_case = _use_case(db)
        await use_case.execute(_website())
        other_class = await use_case.execute(_website(requested_session_id="sess-2"))
        other_age = await use_case.execute(_website(child_age="12"))

    assert other_class.created is True and other_age.created is True
    assert await db["crm_contacts"].count_documents({}) == 3


async def test_same_inquiry_in_another_academy_is_not_deduped_against_this_one() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        first = await _use_case(db).execute(_website())
    with tenant_scope("acad-crm-other"):
        second = await _use_case(db).execute(_website())

    assert second.created is True
    assert second.contact.academy_id == "acad-crm-other"
    assert first.contact.dedupe_key == second.contact.dedupe_key
    assert await db["crm_contacts"].count_documents({}) == 2


async def test_staff_quick_add_by_phone_only() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        result = await _use_case(db).execute(
            CreateContactCommand(
                name="Quick Addperson",
                source="whatsapp_or_phone",
                phone="+1 555 010 9999",
                child_name="Kiddo Addperson",
                created_by="user-staff-1",
            )
        )
    assert result.created is True
    assert result.contact.email is None
    assert result.contact.pipeline_status == "lead"
    assert result.contact.created_by == "user-staff-1"


async def test_referral_records_the_referrer() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        result = await _use_case(db).execute(
            CreateContactCommand(
                name="Referred Person",
                source="referral",
                email="referred@example.test",
                referrer_parent_id="parent-9",
                created_by="user-staff-1",
            )
        )
    assert result.contact.referrer_parent_id == "parent-9"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "   "}, "name"),
        ({"name": "x" * 121}, "name"),
        ({"email": None, "phone": None}, "email"),
        ({"email": "not-an-email"}, "email"),
        ({"email": "a b@example.test"}, "email"),
        ({"phone": "12-34"}, "phone"),
        ({"source": "facebook"}, "source"),
        ({"pipeline_status": "enrolled"}, "pipeline_status"),
        ({"child_age": "9" * 21}, "child_age"),
        ({"requested_session_id": "s" * 65}, "requested_session_id"),
        ({"created_by": "user-1"}, "created_by"),
        ({"referrer_parent_id": "parent-1"}, "referrer_parent_id"),
    ],
)
async def test_invalid_input_is_rejected_before_any_write(
    overrides: dict[str, Any], field: str
) -> None:
    db = await _db()
    with tenant_scope(ACADEMY), pytest.raises(InvalidContact) as exc:
        await _use_case(db).execute(_website(**overrides))
    assert exc.value.details["field"] == field
    assert await db["crm_contacts"].count_documents({}) == 0


def test_dedupe_key_normalises_and_ignores_the_person_name() -> None:
    a = compute_dedupe_key(
        source="website",
        email="A@Example.test ",
        phone_digits="(555) 010-2030",
        child_name=None,
        child_age=" 9 ",
        requested_session_id="sess-1",
    )
    b = compute_dedupe_key(
        source="website",
        email="a@example.test",
        phone_digits="5550102030",
        child_name="",
        child_age="9",
        requested_session_id="sess-1",
    )
    assert a == b
    assert len(a) == 64
    assert a != compute_dedupe_key(
        source="other",
        email="a@example.test",
        phone_digits="5550102030",
        child_name=None,
        child_age="9",
        requested_session_id="sess-1",
    )


async def test_repo_reads_back_and_lists_by_stage_newest_first() -> None:
    db = await _db()
    with tenant_scope(ACADEMY):
        use_case = _use_case(db)
        trial = await use_case.execute(_website())
        lead = await use_case.execute(
            _website(pipeline_status="lead", requested_session_id=None, child_age="7")
        )
        repo = MongoCrmContactRepository(db)
        assert await repo.get(trial.contact.contact_id) == trial.contact
        assert await repo.find_by_dedupe_key(lead.contact.dedupe_key) == lead.contact
        assert [c.contact_id for c in await repo.list_by_pipeline_status("trial")] == [
            trial.contact.contact_id
        ]
        assert len(await repo.list_by_pipeline_status()) == 2
