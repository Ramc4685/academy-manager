"""AI application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.v2.contexts.ai.domain.models import AiCallRecord, LlmResult


class LlmPort(Protocol):
    async def complete(
        self, *, prompt_version: str, system: str, user: str, max_tokens: int
    ) -> LlmResult: ...


class AiCallRepository(Protocol):
    async def record(self, call: AiCallRecord) -> None: ...
    async def count_since(self, since: datetime) -> int: ...
    async def set_approver(self, call_id: str, approver: str) -> bool: ...


class MonthlyCapSource(Protocol):
    """The academy in scope's monthly AI call cap."""

    async def monthly_cap(self) -> int: ...


class DailyCapSource(Protocol):
    """The academy in scope's per-feature daily AI call ceiling
    (``ai.daily_call_cap.<feature>``); None means no daily ceiling."""

    async def daily_cap(self, feature: str) -> int | None: ...


class AiCallCounterRepository(Protocol):
    """Atomic reservation counters for the hard cap, one per key in scope."""

    async def reserve(self, key: str, cap: int) -> bool:
        """Take one slot when the key's count is under ``cap``; False at the cap."""
        ...

    async def release(self, key: str) -> None:
        """Give back one slot taken by ``reserve``."""
        ...


class EntitlementSource(Protocol):
    """Whether the academy in scope holds a plan feature (``"ai"``)."""

    async def has_feature(self, feature: str) -> bool: ...


class AiEntitlement(Protocol):
    """Whether the academy in scope may use paid AI features."""

    async def has_ai(self) -> bool: ...


class ImportValueSharing(Protocol):
    """Whether the academy in scope lets the roster-import copilot see real
    spreadsheet values (``ai.share_import_values``); False means headers and
    masked samples only."""

    async def share_values(self) -> bool: ...
