"""CRM application ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol

from backend.v2.contexts.crm.domain.family_notes import (
    FamilyFollowUp,
    FamilyNote,
    FollowUpStatus,
)
from backend.v2.contexts.crm.domain.models import CrmContact, PipelineStatus


class CrmContactRepository(Protocol):
    async def add_if_absent(self, contact: CrmContact) -> tuple[CrmContact, bool]:
        """Insert ``contact`` unless a row with its ``dedupe_key`` already exists
        in the current academy. Returns ``(stored_row, created)``: the new row
        and True, or the EXISTING row and False. Race-safe: the unique
        ``(academy_id, dedupe_key)`` index decides, never a read-then-insert.
        A contact with no ``dedupe_key`` (staff sources) is always inserted."""
        ...

    async def get(self, contact_id: str) -> CrmContact | None: ...

    async def find_by_dedupe_key(self, dedupe_key: str) -> CrmContact | None: ...

    async def list_by_pipeline_status(
        self, status: PipelineStatus | None = None, *, limit: int = 200
    ) -> list[CrmContact]: ...


# --------------------------------------------------------------------------
# Family index (People CRM spec §3.2, Phase 2). The CRM may not import the
# identity, enrollment or billing contexts (tests/structural/test_layering.py),
# so each source is a structural protocol here and composition/families_crm.py
# hands in the owning context's implementation. Attributes are read-only
# properties so the owners' frozen models and dataclasses satisfy them.
# --------------------------------------------------------------------------


class ResolvedParent(Protocol):
    """A users document and every id a family row may reference it by."""

    @property
    def canonical_id(self) -> str: ...

    @property
    def aliases(self) -> frozenset[str]: ...

    @property
    def display_name(self) -> str | None: ...

    @property
    def email(self) -> str | None: ...

    @property
    def phone(self) -> str | None: ...


class ParentAliasResolver(Protocol):
    """Identity: resolve stored parent references with one equality lookup per
    field (never an ``$or`` across fields, #878/#894)."""

    async def resolve_parent_aliases(
        self, raw_ids: Sequence[str]
    ) -> Mapping[str, ResolvedParent]: ...


class ChildLifecycle(Protocol):
    @property
    def state(self) -> str: ...

    @property
    def as_of(self) -> date | None: ...

    @property
    def live_session_ids(self) -> tuple[str, ...]: ...


class ChildLifecycleReader(Protocol):
    """Enrollment: the ``/admin/students`` lifecycle derivation, batched."""

    async def lifecycle_snapshots(
        self, *, academy_id: str, student_ids: Sequence[str]
    ) -> Mapping[str, ChildLifecycle]: ...


class FamilyMoneyFacts(Protocol):
    @property
    def balance_cents(self) -> int: ...

    @property
    def open_invoice_count(self) -> int: ...

    @property
    def overdue_invoice_count(self) -> int: ...

    @property
    def overdue_cents(self) -> int: ...

    @property
    def oldest_overdue_due_on(self) -> date | None: ...

    @property
    def last_failed_payment_at(self) -> datetime | None: ...

    @property
    def card_on_file(self) -> bool | None: ...

    @property
    def registration(self) -> str: ...


class FamilyMoneyReader(Protocol):
    """Billing: every family's money in a fixed number of academy-wide reads,
    using the same balance rule as the Billing tab."""

    async def summaries(
        self,
        *,
        academy_id: str,
        family_by_alias: Mapping[str, str],
        today: date,
    ) -> Mapping[str, FamilyMoneyFacts]: ...


# --------------------------------------------------------------------------
# Family notes and follow-ups (People CRM spec §5, Phase 4a). Repositories
# read the academy from the tenant context; every read also filters
# ``parent_id`` so a note or follow-up is only ever found on its own family.
# --------------------------------------------------------------------------


class FamilyNoteRepository(Protocol):
    async def add(self, note: FamilyNote) -> FamilyNote:
        """Insert. Raises ``DuplicateCrmRecordId`` when ``note_id`` exists in
        this academy (the unique ``(academy_id, note_id)`` index decides)."""
        ...

    async def get(self, parent_id: str, note_id: str) -> FamilyNote | None:
        """A live (not deleted) note of this family, or None."""
        ...

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyNote]:
        """Live notes of this family, newest first."""
        ...

    async def update_body(
        self, parent_id: str, note_id: str, *, body: str, updated_at: datetime
    ) -> FamilyNote | None:
        """Rewrite a live note's body. None when there is no such live note."""
        ...

    async def soft_delete(
        self, parent_id: str, note_id: str, *, deleted_by: str, deleted_at: datetime
    ) -> bool:
        """Mark a live note deleted. False when there is no such live note."""
        ...


class FamilyFollowUpRepository(Protocol):
    async def add(self, follow_up: FamilyFollowUp) -> FamilyFollowUp:
        """Insert. Raises ``DuplicateCrmRecordId`` when ``follow_up_id`` exists
        in this academy."""
        ...

    async def get(self, parent_id: str, follow_up_id: str) -> FamilyFollowUp | None: ...

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyFollowUp]:
        """Every follow-up of this family, newest first."""
        ...

    async def update(
        self, parent_id: str, follow_up_id: str, *, changes: Mapping[str, object]
    ) -> FamilyFollowUp | None:
        """Set ``changes`` (already validated field values). None when absent."""
        ...

    async def list_by_status(
        self,
        status: FollowUpStatus,
        *,
        assignee_user_id: str | None = None,
        due_before: date | None = None,
        due_on: date | None = None,
        due_after: date | None = None,
        limit: int = 200,
    ) -> list[FamilyFollowUp]:
        """Academy-wide follow-ups in ``status``, optionally one assignee's and
        one due-date window. Open rows sort by ``due_on`` ascending, done rows
        by ``done_at`` descending."""
        ...


class FamilyRef(Protocol):
    @property
    def family_id(self) -> str: ...

    @property
    def parent_name(self) -> str | None: ...


class FamilyDirectory(Protocol):
    """Is this id a family of the academy? Answers with the canonical family
    (an alias such as a firebase uid resolves to it), or None. Built from the
    academy's own rows, so another academy's family is never found."""

    async def find(self, academy_id: str, family_id: str) -> FamilyRef | None: ...

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        """Canonical family id to parent name, for labelling a cross-family list."""
        ...


class StaffDirectory(Protocol):
    """Identity: is this user an active staff member (admin or owner) here?"""

    async def is_staff(self, academy_id: str, user_id: str) -> bool: ...
