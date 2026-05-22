"""Shared comms module — messages + announcements.

Lives in shared/ rather than as a context because there are no invariants
worth a write-side aggregate; it's a thin CRUD module per ADR-0005
deferred-context rules.

Stored in `messages` and `announcements` collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository

MessageKind = Literal["dm", "announcement"]
Persona = Literal["admin", "coach", "parent"]


class Message(BaseModel):
    model_config = {"frozen": True}
    message_id: str
    academy_id: str
    kind: MessageKind
    sender_id: str
    sender_persona: Persona
    recipient_id: str | None  # None for broadcasts
    body: str
    created_at: datetime
    read_by: list[str] = Field(default_factory=list)
    scope_type: str | None = None
    scope_label: str | None = None
    recipient_count: int | None = None
    delivery_status: str | None = None


class MongoMessageRepository(TenantScopedRepository):
    collection_name = "messages"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> Message:
        return Message(
            message_id=str(doc["message_id"]),
            academy_id=str(doc["academy_id"]),
            kind=doc.get("kind", "dm"),  # type: ignore[arg-type]
            sender_id=str(doc["sender_id"]),
            sender_persona=doc.get("sender_persona", "admin"),  # type: ignore[arg-type]
            recipient_id=doc.get("recipient_id"),  # type: ignore[arg-type]
            body=str(doc.get("body", "")),
            created_at=doc["created_at"],  # type: ignore[arg-type]
            read_by=list(doc.get("read_by", [])),
            scope_type=(str(doc["scope_type"]) if doc.get("scope_type") else None),
            scope_label=(str(doc["scope_label"]) if doc.get("scope_label") else None),
            recipient_count=(
                int(doc["recipient_count"]) if doc.get("recipient_count") is not None else None
            ),
            delivery_status=(str(doc["delivery_status"]) if doc.get("delivery_status") else None),
        )

    async def insert(self, m: Message) -> None:
        await self._insert_one(
            {k: v for k, v in m.model_dump(mode="python").items() if k != "academy_id"}
        )

    async def for_recipient(self, recipient_id: str) -> list[Message]:
        cursor = self._find_many(
            {"$or": [{"recipient_id": recipient_id}, {"kind": "announcement"}]},
            sort=[("created_at", -1)],
            limit=200,
        )
        return [self._to_domain(d) async for d in cursor]

    async def list_announcements(self) -> list[Message]:
        cursor = self._find_many({"kind": "announcement"}, sort=[("created_at", -1)], limit=200)
        return [self._to_domain(d) async for d in cursor]


@dataclass
class CommsService:
    """Thin CRUD service used by admin/parent/coach BFFs alike."""

    messages: MongoMessageRepository
    academy_id: str

    async def send_dm(
        self,
        *,
        sender_id: str,
        sender_persona: Persona,
        recipient_id: str,
        body: str,
    ) -> Message:
        m = Message(
            message_id=str(new_ulid()),
            academy_id=self.academy_id,
            kind="dm",
            sender_id=sender_id,
            sender_persona=sender_persona,
            recipient_id=recipient_id,
            body=body,
            created_at=datetime.now(UTC),
        )
        await self.messages.insert(m)
        return m

    async def send_broadcast(
        self,
        *,
        sender_id: str,
        body: str,
        scope_type: str = "academy",
        scope_label: str | None = None,
    ) -> Message:
        m = Message(
            message_id=str(new_ulid()),
            academy_id=self.academy_id,
            kind="announcement",
            sender_id=sender_id,
            sender_persona="admin",
            recipient_id=None,
            body=body,
            created_at=datetime.now(UTC),
            scope_type=scope_type,
            scope_label=scope_label or "Whole academy announcement",
            recipient_count=None,
            delivery_status="recorded",
        )
        await self.messages.insert(m)
        return m

    async def list_for(self, user_id: str) -> list[Message]:
        return await self.messages.for_recipient(user_id)
