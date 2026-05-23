"""Admin message campaign/scope read-model tests."""

from __future__ import annotations

from backend.v2.shared.comms import CommsService, Message


class FakeMessageRepo:
    def __init__(self) -> None:
        self.rows: list[Message] = []

    async def insert(self, message: Message) -> None:
        self.rows.append(message)

    async def for_recipient(self, recipient_id: str) -> list[Message]:
        return [
            message
            for message in self.rows
            if message.recipient_id == recipient_id or message.kind == "announcement"
        ]


async def test_broadcast_records_scope_and_delivery_status_without_fake_recipient_count() -> None:
    repo = FakeMessageRepo()
    service = CommsService(messages=repo, academy_id="acad")  # type: ignore[arg-type]

    message = await service.send_broadcast(
        sender_id="admin-1",
        body="Schedule update",
        scope_type="academy",
        scope_label="Whole academy announcement",
    )

    assert message.kind == "announcement"
    assert message.scope_type == "academy"
    assert message.scope_label == "Whole academy announcement"
    assert message.delivery_status == "recorded"
    assert message.recipient_count is None


async def test_direct_message_keeps_scope_off_campaign_fields() -> None:
    repo = FakeMessageRepo()
    service = CommsService(messages=repo, academy_id="acad")  # type: ignore[arg-type]

    message = await service.send_dm(
        sender_id="admin-1",
        sender_persona="admin",
        recipient_id="parent-1",
        body="Please review your waiver.",
    )

    assert message.kind == "dm"
    assert message.recipient_id == "parent-1"
    assert message.scope_type is None
    assert message.recipient_count is None
