"""L9 A6-4 / A6-10 / A6-11: repeat website inquiries, attribution, alert due marker."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock_motor

from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    SubmitWebsiteInquiry,
    WebsiteInquiryForm,
)
from backend.v2.contexts.crm.domain.models import clean_attribution
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
ACADEMY = "acad-repeat-inquiry"
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def _use_case(clock: _Clock) -> tuple[SubmitWebsiteInquiry, MongoCrmContactRepository]:
    db = mongomock_motor.AsyncMongoMockClient()["repeat_inquiry"]
    await _M0192.up(db)
    repo = MongoCrmContactRepository(db)
    return SubmitWebsiteInquiry(CreateContact(repo, clock=clock), repo, clock=clock), repo


def _form(**overrides: Any) -> WebsiteInquiryForm:
    fields: dict[str, Any] = {
        "name": "Jamie Testparent",
        "email": "jamie@example.test",
        "phone": None,
        "player_age": "9",
        "class_id": None,
        "message": "Is Saturday ok?",
        "contact_about_request": True,
        "marketing_opt_in": False,
    }
    fields.update(overrides)
    return WebsiteInquiryForm(**fields)


async def _submit(use_case: SubmitWebsiteInquiry, stage: str = "lead", **form: Any) -> Any:
    with tenant_scope(ACADEMY):
        return await use_case.execute(
            _form(**form),
            requested_session_id="sess-1",
            pipeline_status=stage,  # type: ignore[arg-type]
            privacy_notice_url=None,
            attribution={"utm_source": "facebook", "heard_from": "friend"},
        )


async def test_a_new_inquiry_alerts_and_is_due_until_sent() -> None:
    clock = _Clock()
    use_case, repo = await _use_case(clock)
    result = await _submit(use_case)
    assert result.created and result.alert_owner
    assert result.contact.owner_alert_due_at == T0
    assert result.contact.attribution.utm_source == "facebook"
    with tenant_scope(ACADEMY):
        assert [
            c.contact_id
            for c in await repo.list_owner_alerts_due(
                due_from=T0 - timedelta(days=3), due_before=T0 + timedelta(minutes=1)
            )
        ] == [result.contact.contact_id]
        await repo.mark_owner_alerted(result.contact.contact_id, at=T0)
        stored = await repo.get(result.contact.contact_id)
        assert (
            await repo.list_owner_alerts_due(
                due_from=T0 - timedelta(days=3), due_before=T0 + timedelta(minutes=1)
            )
            == []
        )
    assert stored is not None
    assert stored.owner_alert_due_at is None and stored.owner_alert_sent_at == T0


async def test_a_double_tap_inside_a_day_changes_nothing() -> None:
    clock = _Clock()
    use_case, _repo = await _use_case(clock)
    first = await _submit(use_case)
    clock.now = T0 + timedelta(hours=2)
    again = await _submit(use_case, message="Another note")
    assert again.created is False and again.alert_owner is False
    assert again.contact.message == first.contact.message
    assert again.contact.updated_at == first.contact.updated_at


async def test_asking_again_after_a_day_bumps_appends_upgrades_and_realerts_once() -> None:
    clock = _Clock()
    use_case, _repo = await _use_case(clock)
    first = await _submit(use_case, stage="lead")
    clock.now = T0 + timedelta(days=30)
    again = await _submit(use_case, stage="trial", message="Any seats now?")
    clock.now = T0 + timedelta(days=30, hours=1)
    third = await _submit(use_case, stage="trial", message="Hello?")

    assert again.created is False and again.alert_owner is True
    contact = again.contact
    assert contact.contact_id == first.contact.contact_id
    assert contact.message == "Is Saturday ok?\n\nAny seats now?"
    assert contact.pipeline_status == "trial"
    assert contact.updated_at == T0 + timedelta(days=30)
    assert contact.owner_alert_due_at == T0 + timedelta(days=30)
    # First touch wins: the attribution on file is kept.
    assert contact.attribution == first.contact.attribution
    # A third ask an hour later is a double tap of the second.
    assert third.alert_owner is False


async def test_a_trial_contact_is_never_moved_down_to_lead() -> None:
    clock = _Clock()
    use_case, _repo = await _use_case(clock)
    await _submit(use_case, stage="trial")
    clock.now = T0 + timedelta(days=2)
    again = await _submit(use_case, stage="lead")
    assert again.alert_owner is True
    assert again.contact.pipeline_status == "trial"


def test_attribution_keeps_only_short_plain_values() -> None:
    cleaned = clean_attribution(
        {
            "utm_source": "facebook",
            "utm_medium": "paid social",  # a space: dropped
            "utm_campaign": "fall-26.v1_a",
            "heard_from": "x" * 81,  # too long: dropped
            "referral_code": "<script>",
            "gclid": "ignored-unknown-key",
        }
    )
    assert cleaned is not None
    assert cleaned.model_dump() == {
        "heard_from": None,
        "utm_source": "facebook",
        "utm_medium": None,
        "utm_campaign": "fall-26.v1_a",
        "referral_code": None,
    }
    assert clean_attribution({"heard_from": "x" * 80}) is not None
    assert clean_attribution({"utm_source": "a/b"}) is None
    assert clean_attribution(None) is None


def test_registration_heard_from_takes_the_same_short_plain_tokens() -> None:
    import pytest
    from pydantic import ValidationError

    from backend.v2.contexts.onboarding.domain.models import ParentProfile

    assert ParentProfile(heard_from="friend").heard_from == "friend"
    assert ParentProfile().heard_from == ""
    for bad in ("<script>", "a b", "x" * 81):
        with pytest.raises(ValidationError):
            ParentProfile(heard_from=bad)
