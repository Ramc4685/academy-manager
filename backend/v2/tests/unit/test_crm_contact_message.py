"""The optional ``message`` on a CRM contact (Lane B4, the public form's note).

Kept out of ``test_crm_create_contact.py`` so that suite runs unmodified.
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
from backend.v2.contexts.crm.domain.models import MAX_MESSAGE_LEN
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
ACADEMY = "acad-crm-message"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


async def _use_case() -> tuple[CreateContact, MongoCrmContactRepository]:
    db = mongomock_motor.AsyncMongoMockClient()["crm_message"]
    await _M0192.up(db)
    ids = iter(f"contact-{n}" for n in range(10))
    repo = MongoCrmContactRepository(db)
    return CreateContact(repo, clock=lambda: NOW, new_id=lambda: next(ids)), repo


def _cmd(**overrides: Any) -> CreateContactCommand:
    base: dict[str, Any] = {
        "name": "Testy Parentson",
        "source": "website",
        "email": "testy@example.test",
        "child_age": "9",
        "pipeline_status": "trial",
    }
    base.update(overrides)
    return CreateContactCommand(**base)


async def test_message_is_trimmed_keeps_line_breaks_and_round_trips() -> None:
    use_case, repo = await _use_case()
    with tenant_scope(ACADEMY):
        result = await use_case.execute(_cmd(message="  Hello   there \n\n second line  "))
        stored = await repo.get(result.contact.contact_id)
    assert result.contact.message == "Hello   there\n\n second line"
    assert stored is not None and stored.message == result.contact.message


async def test_blank_message_is_none_and_long_message_is_refused() -> None:
    use_case, _ = await _use_case()
    with tenant_scope(ACADEMY):
        blank = await use_case.execute(_cmd(message="   "))
        assert blank.contact.message is None
        with pytest.raises(InvalidContact) as exc:
            await use_case.execute(
                _cmd(email="other@example.test", message="x" * (MAX_MESSAGE_LEN + 1))
            )
    assert exc.value.details["field"] == "message"


async def test_message_is_not_part_of_the_dedupe_key() -> None:
    use_case, _ = await _use_case()
    with tenant_scope(ACADEMY):
        first = await use_case.execute(_cmd(message="one"))
        again = await use_case.execute(_cmd(message="reworded"))
    assert again.created is False
    assert again.contact.contact_id == first.contact.contact_id
    assert again.contact.message == "one"
