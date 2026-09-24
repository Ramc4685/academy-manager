"""MoveCardOnPipeline: a staff move on the Pipeline board (People CRM L3a).

Spec §3.4: "Moves that correspond to a real write (approve trial, Came /
Didn't come) call the existing use cases; moves without one write
``crm_contacts.pipeline_override`` with author and time so the board never
lies about the system state." This is the second half: the override write,
behind the stage-skip guard in ``domain/pipeline.py``.

* The contact is read through the tenant-scoped repository; another
  academy's id is ``Crm.ContactNotFound`` (404), like an unknown one.
* A move to the column the card already shows is a no-op (no write, the
  original author and time kept).
* A refused move is ``Crm.PipelineMoveNotAllowed`` (409, ``details.reason``).
* The write is a compare-and-swap on the override the use case read, so a
  concurrent move (or an enrolment) makes this one fail with
  ``reason="changed"`` instead of silently overwriting it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.crm.domain.errors import ContactNotFound, PipelineMoveNotAllowed
from backend.v2.contexts.crm.domain.models import CrmContact, PipelineOverride
from backend.v2.contexts.crm.domain.pipeline import PipelineColumn, current_column, refuse_move


class PipelineContactRepository(Protocol):
    async def get(self, contact_id: str) -> CrmContact | None: ...

    async def set_pipeline_override(
        self,
        contact_id: str,
        override: PipelineOverride,
        *,
        expected_column: str | None,
        updated_at: datetime,
    ) -> CrmContact | None: ...


class MoveCardCommand(BaseModel):
    model_config = {"frozen": True}

    contact_id: str
    to_column: str
    actor_id: str


class MoveCardResult(BaseModel):
    """The contact after the move and the column its card now shows."""

    model_config = {"frozen": True}

    contact: CrmContact
    column: PipelineColumn


class MoveCardOnPipeline:
    def __init__(
        self,
        contacts: PipelineContactRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._contacts = contacts
        self._now = clock

    async def execute(self, cmd: MoveCardCommand) -> MoveCardResult:
        contact = await self._move(cmd)
        return MoveCardResult(contact=contact, column=current_column(contact))

    async def _move(self, cmd: MoveCardCommand) -> CrmContact:
        contact = await self._contacts.get(cmd.contact_id)
        if contact is None:
            raise ContactNotFound("contact not found", contact_id=cmd.contact_id)

        from_column = current_column(contact)
        if from_column == cmd.to_column:
            return contact
        reason = refuse_move(
            from_column, cmd.to_column, enrolled=contact.pipeline_status == "enrolled"
        )
        if reason is not None:
            raise PipelineMoveNotAllowed(
                "this move is not allowed",
                contact_id=cmd.contact_id,
                reason=reason,
                from_column=from_column,
                to_column=cmd.to_column,
            )

        now = self._now()
        updated = await self._contacts.set_pipeline_override(
            cmd.contact_id,
            PipelineOverride(column=cmd.to_column, set_by=cmd.actor_id, set_at=now),
            expected_column=(
                contact.pipeline_override.column if contact.pipeline_override else None
            ),
            updated_at=now,
        )
        if updated is None:
            if await self._contacts.get(cmd.contact_id) is None:  # pragma: no cover - race
                raise ContactNotFound("contact not found", contact_id=cmd.contact_id)
            raise PipelineMoveNotAllowed(
                "the card moved while saving; reload and try again",
                contact_id=cmd.contact_id,
                reason="changed",
            )
        return updated
