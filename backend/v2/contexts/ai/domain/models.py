"""AI domain models: a completion result and one ``ai_calls`` audit row."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

#: The one model every feature uses until a per-feature choice is needed.
DEFAULT_MODEL = "claude-sonnet-5-5"


class LlmResult(BaseModel):
    model_config = {"frozen": True}

    text: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_cents: int = Field(ge=0)
    model: str


class AiCallRecord(BaseModel):
    """One audited model call. ``academy_id`` is stamped by the repository
    from the tenant scope, never by the caller."""

    model_config = {"frozen": True}

    feature: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_cents: int = Field(ge=0)
    approver: str | None = None
    created_at: datetime
    #: The row's id once written; the repository stamps it so an approval can
    #: set ``approver`` later. ``None`` before ``record``.
    call_id: str | None = None
