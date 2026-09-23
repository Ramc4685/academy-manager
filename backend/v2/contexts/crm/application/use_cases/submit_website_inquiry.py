"""SubmitWebsiteInquiry: the public trial form's write into ``crm_contacts`` (Lane B4).

A thin application-layer wrapper over :class:`CreateContact` for the ONE
anonymous writer (source ``website``). It owns what the public form needs on
top of the contact contract, so the ``interfaces/public`` route never reaches
into the CRM domain:

* **Per-field validation** in the form's own vocabulary (``player_age``,
  ``class_id``, ``contact_about_request``), all errors at once, with messages
  a parent can act on. Values are never echoed.
* **Consent**: ``contact_about_request`` must be literally true; marketing is
  off unless ticked; the privacy notice shown is recorded; ``captured_at`` is
  stamped by ``CreateContact``.
* **No child name**, no ``created_by``, no referrer, ever: the command it
  builds has no way to carry them.

Dedupe stays in ``CreateContact`` and its unique index. The result's
``created`` flag must not reach the anonymous caller (see the README).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.domain.errors import InvalidContact
from backend.v2.contexts.crm.domain.models import (
    MAX_CHILD_AGE_LEN,
    MAX_EMAIL_LEN,
    MAX_ID_LEN,
    MAX_MESSAGE_LEN,
    MAX_NAME_LEN,
    MAX_PHONE_DIGITS,
    MIN_PHONE_DIGITS,
    ContactConsent,
    CrmContact,
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NON_DIGIT = re.compile(r"\D")
#: Longest phone as typed (punctuation included) worth reading.
_MAX_PHONE_TEXT = 40

#: CreateContact's field names, as the public form calls them.
_FORM_FIELD = {"child_age": "player_age", "requested_session_id": "class_id"}


@dataclass(frozen=True)
class WebsiteInquiryForm:
    """What the anonymous form sent, loosely typed; validated by :meth:`errors`."""

    name: str | None
    email: str | None
    phone: str | None
    player_age: str | None
    class_id: str | None
    message: str | None
    contact_about_request: bool
    marketing_opt_in: bool

    def errors(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        name = _text(self.name)
        if name is None:
            errors["name"] = "Enter your name."
        elif len(name) > MAX_NAME_LEN:
            errors["name"] = f"Keep your name to {MAX_NAME_LEN} characters or fewer."
        email = _text(self.email)
        if email is None:
            errors["email"] = "Enter your email address."
        elif len(email) > MAX_EMAIL_LEN or not _EMAIL.match(email):
            errors["email"] = "Enter an email address like name@example.com."
        phone = _text(self.phone)
        if phone is not None:
            digits = _NON_DIGIT.sub("", phone)
            if len(phone) > _MAX_PHONE_TEXT or not (
                MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS
            ):
                errors["phone"] = (
                    f"Enter a phone number with {MIN_PHONE_DIGITS} to {MAX_PHONE_DIGITS} "
                    "digits, or leave it blank."
                )
        age = _text(self.player_age)
        if age is None:
            errors["player_age"] = "Enter the player's age."
        elif len(age) > MAX_CHILD_AGE_LEN:
            errors["player_age"] = f"Keep the age to {MAX_CHILD_AGE_LEN} characters or fewer."
        class_id = _text(self.class_id)
        if class_id is not None and len(class_id) > MAX_ID_LEN:
            errors["class_id"] = "Choose a class from the list, or leave it blank."
        if self.message is not None and len(self.message.strip()) > MAX_MESSAGE_LEN:
            errors["message"] = f"Keep the message to {MAX_MESSAGE_LEN} characters or fewer."
        if self.contact_about_request is not True:
            errors["contact_about_request"] = (
                "Tick this box so the academy can contact you about your request."
            )
        return errors


@dataclass(frozen=True)
class WebsiteInquiryResult:
    #: Set when accepted; None when ``field_errors`` is not empty.
    contact: CrmContact | None
    #: Server-side only: never tell the anonymous caller.
    created: bool
    field_errors: dict[str, str]


class SubmitWebsiteInquiry:
    def __init__(self, create_contact: CreateContact) -> None:
        self._create_contact = create_contact

    async def execute(
        self,
        form: WebsiteInquiryForm,
        *,
        requested_session_id: str | None,
        pipeline_status: Literal["lead", "trial"],
        privacy_notice_url: str | None,
    ) -> WebsiteInquiryResult:
        """Validate and write; the tenant is the caller's tenant scope (the host)."""
        errors = form.errors()
        if errors:
            return WebsiteInquiryResult(contact=None, created=False, field_errors=errors)
        try:
            result = await self._create_contact.execute(
                CreateContactCommand(
                    name=form.name or "",
                    source="website",
                    email=form.email,
                    phone=form.phone,
                    child_age=_text(form.player_age),
                    requested_session_id=requested_session_id,
                    message=form.message,
                    pipeline_status=pipeline_status,
                    consent=ContactConsent(
                        contact_about_request=True,
                        marketing=form.marketing_opt_in is True,
                        privacy_notice_url=privacy_notice_url,
                    ),
                )
            )
        except InvalidContact as exc:
            field = str(exc.details.get("field") or "form")
            return WebsiteInquiryResult(
                contact=None,
                created=False,
                field_errors={_FORM_FIELD.get(field, field): exc.message},
            )
        return WebsiteInquiryResult(contact=result.contact, created=result.created, field_errors={})


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None
