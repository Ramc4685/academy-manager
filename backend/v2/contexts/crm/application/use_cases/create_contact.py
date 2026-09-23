"""CreateContact: the ONE way a ``crm_contacts`` row is created.

Callers: the anonymous public trial-request endpoint (source ``website``) and
the People CRM quick-add (staff sources). Both go through here so validation,
normalisation and the dedupe key are identical. See ``contexts/crm/README.md``.

Idempotent for ``website`` only: a repeat of the same public inquiry (same
normalised email, phone digits, child name, child age and requested class)
returns the row that already exists with ``created=False``; it never raises
and never writes a second row. The unique ``(academy_id, dedupe_key)`` index
decides, so two concurrent submissions cannot both insert. Staff quick-add
sources get no ``dedupe_key`` and always insert a new row: the key ignores
the person's name, so it would merge two different people who share a
household phone or email.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from backend.v2.contexts.crm.application.ports import CrmContactRepository
from backend.v2.contexts.crm.domain.errors import InvalidContact
from backend.v2.contexts.crm.domain.models import (
    CONTACT_SOURCES,
    CREATABLE_PIPELINE_STATUSES,
    DEDUPED_SOURCES,
    MAX_CHILD_AGE_LEN,
    MAX_EMAIL_LEN,
    MAX_ID_LEN,
    MAX_NAME_LEN,
    MAX_PHONE_DIGITS,
    MAX_URL_LEN,
    MIN_PHONE_DIGITS,
    ContactConsent,
    ContactSource,
    CrmContact,
    PipelineStatus,
    compute_dedupe_key,
    normalize_email,
    normalize_phone_digits,
    normalize_text,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id


@dataclass(frozen=True)
class CreateContactCommand:
    """Input for ``CreateContact``. Raw values; the use case normalises them.

    There is deliberately no ``academy_id`` field: the tenant comes only from
    the request's tenant scope (``current_academy_id()``).
    """

    name: str
    source: str
    email: str | None = None
    phone: str | None = None
    child_name: str | None = None
    child_age: str | None = None
    requested_session_id: str | None = None
    pipeline_status: str = "lead"
    referrer_parent_id: str | None = None
    consent: ContactConsent | None = None
    created_by: str | None = None


@dataclass(frozen=True)
class CreateContactResult:
    contact: CrmContact
    #: False when the same inquiry already existed and was returned instead.
    created: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_millis(value: datetime) -> datetime:
    return value.replace(microsecond=value.microsecond - value.microsecond % 1000)


class CreateContact:
    def __init__(
        self,
        repo: CrmContactRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._new_id = new_id

    async def execute(self, cmd: CreateContactCommand) -> CreateContactResult:
        name = normalize_text(cmd.name)
        email = normalize_email(cmd.email)
        phone_digits = normalize_phone_digits(cmd.phone)
        child_name = normalize_text(cmd.child_name)
        child_age = normalize_text(cmd.child_age)
        requested_session_id = normalize_text(cmd.requested_session_id)
        referrer_parent_id = normalize_text(cmd.referrer_parent_id)
        created_by = normalize_text(cmd.created_by)

        _validate(
            cmd,
            name=name,
            email=email,
            phone_digits=phone_digits,
            child_name=child_name,
            child_age=child_age,
            requested_session_id=requested_session_id,
            referrer_parent_id=referrer_parent_id,
            created_by=created_by,
        )
        assert name is not None  # _validate guarantees it

        # BSON stores milliseconds; truncate so the returned row equals a read-back.
        now = _to_millis(self._clock())
        consent = cmd.consent or ContactConsent()
        if consent.captured_at is None:
            consent = consent.model_copy(update={"captured_at": now})

        contact = CrmContact(
            contact_id=self._new_id(),
            academy_id=current_academy_id(),
            name=name,
            email=email,
            phone_digits=phone_digits,
            source=cast(ContactSource, cmd.source),  # checked by _validate
            child_name=child_name,
            child_age=child_age,
            requested_session_id=requested_session_id,
            pipeline_status=cast(PipelineStatus, cmd.pipeline_status),  # checked by _validate
            referrer_parent_id=referrer_parent_id,
            consent=consent,
            created_by=created_by,
            dedupe_key=(
                compute_dedupe_key(
                    source=cmd.source,
                    email=email,
                    phone_digits=phone_digits,
                    child_name=child_name,
                    child_age=child_age,
                    requested_session_id=requested_session_id,
                )
                if cmd.source in DEDUPED_SOURCES
                else None
            ),
            created_at=now,
            updated_at=now,
        )
        stored, created = await self._repo.add_if_absent(contact)
        return CreateContactResult(contact=stored, created=created)


def _validate(
    cmd: CreateContactCommand,
    *,
    name: str | None,
    email: str | None,
    phone_digits: str | None,
    child_name: str | None,
    child_age: str | None,
    requested_session_id: str | None,
    referrer_parent_id: str | None,
    created_by: str | None,
) -> None:
    if cmd.source not in CONTACT_SOURCES:
        raise InvalidContact("Unknown contact source.", field="source")
    if cmd.pipeline_status not in CREATABLE_PIPELINE_STATUSES:
        raise InvalidContact("A new contact starts as a lead or a trial.", field="pipeline_status")
    if name is None:
        raise InvalidContact("Name is required.", field="name")
    if len(name) > MAX_NAME_LEN:
        raise InvalidContact("Name is too long.", field="name")
    if email is None and phone_digits is None:
        raise InvalidContact("An email or a phone number is required.", field="email")
    if email is not None and (
        len(email) > MAX_EMAIL_LEN
        or " " in email
        or email.count("@") != 1
        or email.startswith("@")
        or email.endswith("@")
    ):
        raise InvalidContact("Email address is not valid.", field="email")
    if phone_digits is not None and not (MIN_PHONE_DIGITS <= len(phone_digits) <= MAX_PHONE_DIGITS):
        raise InvalidContact("Phone number is not valid.", field="phone")
    if child_name is not None and len(child_name) > MAX_NAME_LEN:
        raise InvalidContact("Child name is too long.", field="child_name")
    if child_age is not None and len(child_age) > MAX_CHILD_AGE_LEN:
        raise InvalidContact("Age is too long.", field="child_age")
    for field, value in (
        ("requested_session_id", requested_session_id),
        ("referrer_parent_id", referrer_parent_id),
        ("created_by", created_by),
    ):
        if value is not None and len(value) > MAX_ID_LEN:
            raise InvalidContact(f"{field} is too long.", field=field)
    if referrer_parent_id is not None and cmd.source != "referral":
        raise InvalidContact(
            "Only a referral records who referred the contact.", field="referrer_parent_id"
        )
    if cmd.source == "website" and (created_by is not None or referrer_parent_id is not None):
        raise InvalidContact("A website contact is anonymous.", field="created_by")
    url = cmd.consent.privacy_notice_url if cmd.consent else None
    if url is not None and len(url) > MAX_URL_LEN:
        raise InvalidContact("Privacy notice URL is too long.", field="consent")
