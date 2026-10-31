"""The Pipeline board read (People CRM spec §3.4, roadmap L3b).

One card per lead or prospective family, in five columns::

    inquiry -> trial_booked -> trial_done -> registered -> enrolled

Two sources, merged here and nowhere else:

* **``crm_contacts``** (the lead store). The column is
  ``domain.pipeline.current_column``: the system's ``enrolled`` wins, then a
  staff ``pipeline_override`` (L3a), then the column implied by the stage.
  These cards can be moved (``move_targets``); the move itself is
  ``MoveCardOnPipeline`` behind ``POST /admin/crm/contacts/{id}/pipeline-move``.
* **The family index stage roll-up** (the same index ``/admin/families``
  reads). A family whose rolled-up stage is ``trial`` shows in Trial booked;
  a family with an account and no children yet (``never_enrolled``, shown as
  "Lead", spec §6) shows in Inquiry. These cards are read-only on the board:
  their stage is a system write (approve a trial, Came / Didn't come,
  register) made on the family record or the Inbox, never an override. A
  family a contact already links to (``linked_family_id`` /
  ``converted_parent_id``) is not shown twice.

Enrolled cards leave the board seven days after their last change (spec
§3.4). Active families are not cards: the Families view lists them.

No money: a card carries no amount, so front desk sees the same board.
Pure over its two ports; the family index is optional (a failed read is the
``families_unavailable`` warning, never an empty funnel presented as fact).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContactCommand
from backend.v2.contexts.crm.domain.family_index import FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.domain.pipeline import (
    PIPELINE_COLUMNS,
    PipelineColumn,
    current_column,
    refuse_move,
)

#: Spec §3.4: "Enrolled (the card leaves the board after 7 days)".
ENROLLED_CARD_DAYS: Final = 7
#: How many contacts one board read loads (newest first). The board is a
#: working view, not an archive; the reports page counts everything.
BOARD_CONTACT_LIMIT: Final = 500

_FAMILY_STAGE_COLUMN: Final[dict[str, PipelineColumn]] = {
    "trial": "trial_booked",
    "never_enrolled": "inquiry",
}

CardKind = Literal["contact", "family"]


class BoardContactSource(Protocol):
    async def list_by_pipeline_status(
        self, status: None = None, *, limit: int = 200
    ) -> list[CrmContact]: ...


class BoardFamilySource(Protocol):
    async def build(self, academy_id: str) -> FamilyIndex: ...


@dataclass(frozen=True)
class PipelineCard:
    card_id: str
    kind: CardKind
    column: PipelineColumn
    name: str
    #: Contact cards only.
    contact_id: str | None = None
    #: The family record this card opens, when there is one.
    family_id: str | None = None
    child: str | None = None
    child_age: str | None = None
    source: str | None = None
    created_at: datetime | None = None
    lead_age_days: int | None = None
    override_column: str | None = None
    override_set_by: str | None = None
    override_set_at: datetime | None = None
    #: Columns a staff move may take this card to now (empty = read-only).
    move_targets: tuple[PipelineColumn, ...] = ()


@dataclass(frozen=True)
class PipelineBoard:
    generated_at: datetime
    cards: tuple[PipelineCard, ...]
    warnings: tuple[str, ...] = ()


def move_targets(column: PipelineColumn, *, enrolled: bool) -> tuple[PipelineColumn, ...]:
    """Every column ``refuse_move`` lets this card go to, board order."""
    return tuple(
        target
        for target in PIPELINE_COLUMNS
        if target != column and refuse_move(column, target, enrolled=enrolled) is None
    )


def contact_card(contact: CrmContact, *, now: datetime) -> PipelineCard:
    column = current_column(contact)
    enrolled = contact.pipeline_status == "enrolled"
    override = contact.pipeline_override
    created = _aware(contact.created_at)
    return PipelineCard(
        card_id=f"contact:{contact.contact_id}",
        kind="contact",
        column=column,
        name=contact.name,
        contact_id=contact.contact_id,
        family_id=contact.linked_family_id or contact.converted_parent_id,
        child=contact.child_name,
        child_age=contact.child_age,
        source=contact.source,
        created_at=created,
        lead_age_days=max(0, (now - created).days),
        override_column=override.column if override and not enrolled else None,
        override_set_by=override.set_by if override and not enrolled else None,
        override_set_at=_aware(override.set_at) if override and not enrolled else None,
        move_targets=move_targets(column, enrolled=enrolled),
    )


def family_card(family: FamilyRecord) -> PipelineCard | None:
    column = _FAMILY_STAGE_COLUMN.get(family.stage)
    if column is None:
        return None
    if family.stage == "never_enrolled" and not family.has_account:
        return None
    children = ", ".join(child.name for child in family.children if child.name) or None
    return PipelineCard(
        card_id=f"family:{family.family_id}",
        kind="family",
        column=column,
        name=family.parent_name or family.email or "Family",
        family_id=family.family_id,
        child=children,
    )


def build_pipeline_board(
    contacts: list[CrmContact],
    index: FamilyIndex | None,
    *,
    now: datetime,
    warnings: tuple[str, ...] = (),
) -> PipelineBoard:
    """The board: contact cards (newest first), then family cards (by name)."""
    now = _aware(now)
    leave_before = now - timedelta(days=ENROLLED_CARD_DAYS)
    cards: list[PipelineCard] = []
    linked: set[str] = set()
    for contact in contacts:
        for family_id in (contact.linked_family_id, contact.converted_parent_id):
            if family_id:
                linked.add(family_id)
        if contact.pipeline_status == "enrolled" and _aware(contact.updated_at) < leave_before:
            continue
        cards.append(contact_card(contact, now=now))
    if index is not None:
        # A contact may hold any alias of the parent; compare canonical ids.
        linked_families = {index.family_by_alias.get(ref, ref) for ref in linked}
        for family in sorted(index.families, key=lambda f: f.sort_key):
            if family.family_id in linked_families:
                continue
            card = family_card(family)
            if card is not None:
                cards.append(card)
    return PipelineBoard(generated_at=now, cards=tuple(cards), warnings=warnings)


def quick_add_command(
    *,
    name: str,
    source: str,
    actor_id: str,
    phone: str | None = None,
    email: str | None = None,
    child_name: str | None = None,
    child_age: str | None = None,
) -> CreateContactCommand:
    """The board's quick add lead as a ``CreateContact`` command: a staff
    source, stage ``lead``, ``created_by`` the caller. The person asked the
    academy about classes, so ``contact_about_request`` is recorded; never a
    marketing opt-in."""
    return CreateContactCommand(
        name=name,
        source=source,
        email=email,
        phone=phone,
        child_name=child_name,
        child_age=child_age,
        pipeline_status="lead",
        consent=ContactConsent(contact_about_request=True, marketing=False),
        created_by=actor_id,
    )


class GetPipelineBoard:
    """Read the board for the request's academy (tenant-scoped contacts)."""

    def __init__(
        self,
        contacts: BoardContactSource,
        families: BoardFamilySource | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._contacts = contacts
        self._families = families
        self._clock = clock

    async def execute(self, academy_id: str) -> PipelineBoard:
        contacts = await self._contacts.list_by_pipeline_status(None, limit=BOARD_CONTACT_LIMIT)
        index: FamilyIndex | None = None
        warnings: tuple[str, ...] = ()
        if self._families is None:
            warnings = ("families_unavailable",)
        else:
            try:
                index = await self._families.build(academy_id)
            except FamilyIndexUnavailable:
                warnings = ("families_unavailable",)
        return build_pipeline_board(contacts, index, now=self._clock(), warnings=warnings)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
