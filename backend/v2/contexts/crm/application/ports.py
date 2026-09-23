"""CRM application ports."""

from __future__ import annotations

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
