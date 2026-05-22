"""DomainEvent base class.

See docs/event-rules.md for the contract. Every concrete event subclasses
DomainEvent with a typed payload and a `Literal` `name` + `schema_version`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.v2.shared.ids import new_ulid


def _new_event_id() -> str:
    return str(new_ulid())


def _now() -> datetime:
    return datetime.now(UTC)


class DomainEvent(BaseModel):
    """Base for all domain events.

    Subclasses MUST set ``name`` and ``schema_version`` to ``Literal`` types and
    define a typed ``payload`` model.
    """

    event_id: str = Field(default_factory=_new_event_id)
    name: str
    schema_version: int
    aggregate_id: str
    academy_id: str
    occurred_at: datetime = Field(default_factory=_now)
    payload: BaseModel | dict[str, Any]

    model_config = {"frozen": True}
