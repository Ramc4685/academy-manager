"""The Pipeline board read and quick add on a real ``mongod`` (People CRM L3b).

``real_db`` replays every migration, so the ``crm_contacts`` indexes are the
production ones. Checks, against the real ``MongoCrmContactRepository``:

* the board lists only the caller's academy's contacts, newest first, with
  the column a staff override (L3a) put them in;
* quick add (the existing ``CreateContact`` with a staff source) stamps the
  tenant and never dedupes two staff entries sharing a phone;
* a card moved by ``MoveCardOnPipeline`` shows in its new column on the next
  board read.

Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.contexts.crm.application.pipeline_board import GetPipelineBoard
from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.application.use_cases.pipeline_moves import (
    MoveCardCommand,
    MoveCardOnPipeline,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-l3b-a"
B = "acad-l3b-b"
NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)


def _cmd(name: str, *, phone: str = "555-010-2030") -> CreateContactCommand:
    return CreateContactCommand(
        name=name, source="whatsapp_or_phone", phone=phone, created_by="staff-1"
    )


async def test_board_is_tenant_scoped_newest_first_and_follows_moves(real_db: Any) -> None:
    repo = MongoCrmContactRepository(real_db)
    ticks = iter(NOW + timedelta(minutes=i) for i in range(10))
    create = CreateContact(repo, clock=lambda: next(ticks))

    with tenant_scope(A):
        first = (await create.execute(_cmd("Sample Parent One"))).contact
        second = (await create.execute(_cmd("Sample Parent Two"))).contact
    with tenant_scope(B):
        other = (await create.execute(_cmd("Other Academy Parent"))).contact

    # Staff quick-add rows are never deduped, even on a shared phone.
    assert first.contact_id != second.contact_id
    assert first.dedupe_key is None and second.dedupe_key is None

    board = GetPipelineBoard(repo, None, clock=lambda: NOW + timedelta(hours=1))
    with tenant_scope(A):
        result = await board.execute(A)
    ids = [card.contact_id for card in result.cards]
    assert ids == [second.contact_id, first.contact_id]
    assert other.contact_id not in ids
    assert {card.column for card in result.cards} == {"inquiry"}
    assert result.cards[0].move_targets == ("trial_booked",)

    with tenant_scope(A):
        await MoveCardOnPipeline(repo, clock=lambda: NOW).execute(
            MoveCardCommand(
                contact_id=first.contact_id, to_column="trial_booked", actor_id="staff-1"
            )
        )
        moved = {c.contact_id: c for c in (await board.execute(A)).cards}[first.contact_id]
    assert (moved.column, moved.override_set_by) == ("trial_booked", "staff-1")
    assert moved.move_targets == ("inquiry", "trial_done")

    stored = await real_db["crm_contacts"].find_one({"contact_id": first.contact_id})
    assert stored["academy_id"] == A
    assert stored["created_by"] == "staff-1"
    assert stored["source"] == "whatsapp_or_phone"
