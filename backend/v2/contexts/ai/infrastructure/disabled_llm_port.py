"""The port wired whenever AI is off: every call raises ``AiDisabled``."""

from __future__ import annotations

from backend.v2.contexts.ai.domain.errors import AiDisabled
from backend.v2.contexts.ai.domain.models import LlmResult


class DisabledLlmPort:
    async def complete(
        self, *, prompt_version: str, system: str, user: str, max_tokens: int
    ) -> LlmResult:
        raise AiDisabled("AI is disabled: set V2_AI_ENABLED and V2_ANTHROPIC_API_KEY")
