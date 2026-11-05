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


class MonthlyCapSource(Protocol):
    """The academy in scope's monthly AI call cap."""

    async def monthly_cap(self) -> int: ...


class AiEntitlement(Protocol):
    """Whether the academy in scope may use paid AI features."""

    async def has_ai(self) -> bool: ...
