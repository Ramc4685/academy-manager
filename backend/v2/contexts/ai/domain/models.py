"""AI domain models: a completion result and one ``ai_calls`` audit row."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.v2.shared.ids import new_ulid

#: The one model every feature uses until a per-feature choice is needed.
DEFAULT_MODEL = "claude-haiku-5-5"


class LlmResult(BaseModel):
    model_config = {"frozen": True}

    text: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_cents: int = Field(ge=0)
    model: str
    #: List price in millionths of a cent; ``cost_cents`` rounds every call up.
    cost_microcents: int = Field(default=0, ge=0)
    #: The provider stopped at ``max_tokens``: the answer is cut off.
    truncated: bool = False


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
    cost_microcents: int = Field(default=0, ge=0)
    approver: str | None = None
    created_at: datetime
    #: Minted at construction so a later approval can set ``approver`` on the row.
    call_id: str = Field(default_factory=new_ulid)
