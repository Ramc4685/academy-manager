"""CRM application ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol

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
